"""
Sessões do Guichê: abertura, heartbeat, pausa, encerramento e manutenção diária.

- Um guichê por máquina e uma sessão por usuário (UNIQUE em guiche_aberto /
  usuario_aberto). Sessões sem ping há mais de sessao_timeout_seg expiram e
  liberam as senhas abertas; sessões abertas desta máquina (queda do app) são
  encerradas como 'forcada' SEM liberar (o atendimento é restaurado no login).
- encerrar_do_usuario(): gestor encerra a sessão de outro usuário (motivo 'forcada');
  o Heartbeat da máquina afetada detecta pelo ping e volta ao login.
- Heartbeat (thread daemon): ping, status do Painel e manutenção diária.
  Os callbacks são chamados NA THREAD: quem cria deve repassar para a UI.
- Manutenção diária: executada por UMA máquina (UPDATE condicional atômico
  em config.ultima_manutencao). A data vem do relógio do banco e é passada
  como parâmetro (evita o erro 1267 de mistura de collations).
"""
import logging
import socket
import threading
from dataclasses import dataclass
from typing import Callable, Optional

import mysql.connector

from database import db, descrever_erro
from services import auditoria, fila_service, parametros
from services.auth import Usuario

log = logging.getLogger(__name__)

MAQUINA = (socket.gethostname() or "guiche")[:64]


class ErroSessao(Exception):
    """Mensagem segura para a tela."""


@dataclass
class Sessao:
    id: int
    usuario: Usuario
    guiche_id: int
    guiche: str
    status: str = "ativo"

    @property
    def pausada(self) -> bool:
        return self.status == "pausa"


def listar_guiches() -> list[dict]:
    return db.fetch_all("SELECT id, nome FROM guiches WHERE ativo = 1 ORDER BY nome")


def _fechar(cur, sid: int, motivo: str) -> None:
    cur.execute(
        "UPDATE sessoes_guiche SET fim_em = NOW(), motivo_fim = %s, "
        "guiche_aberto = NULL, usuario_aberto = NULL WHERE id = %s AND fim_em IS NULL",
        (motivo, sid),
    )


def _expirar(timeout_seg: int) -> None:
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, usuario_id, guiche_id, maquina FROM sessoes_guiche "
            "WHERE fim_em IS NULL AND (ultimo_ping < NOW() - INTERVAL %s SECOND OR maquina = %s) "
            "FOR UPDATE",
            (timeout_seg, MAQUINA),
        )
        for r in cur.fetchall():
            local = r["maquina"] == MAQUINA
            motivo = "forcada" if local else "expirada"
            _fechar(cur, r["id"], motivo)
            auditoria.registrar(cur, "sessao_expirada", r["usuario_id"], r["guiche_id"],
                                detalhe=f"{motivo}:{r['maquina']}")
            if not local:
                fila_service.liberar_abertas(cur, r["usuario_id"], "sessao_expirada")


def encerrar_do_usuario(cur, usuario_id: int, gestor_id: int) -> int:
    """Dentro da transação recebida: encerra a(s) sessão(ões) aberta(s) do usuário."""
    cur.execute(
        "SELECT id, guiche_id, maquina FROM sessoes_guiche "
        "WHERE usuario_id = %s AND fim_em IS NULL FOR UPDATE",
        (usuario_id,),
    )
    linhas = cur.fetchall()
    for r in linhas:
        _fechar(cur, r["id"], "forcada")
        auditoria.registrar(cur, "sessao_encerrar", gestor_id, r["guiche_id"],
                            detalhe=f"usuario={usuario_id} maquina={r['maquina']}"[:255])
    return len(linhas)


def abrir(usuario: Usuario, guiche_id: int) -> Sessao:
    p = parametros.obter(forcar=True)
    _expirar(p.sessao_timeout_seg)
    try:
        with db.cursor() as cur:
            cur.execute("SELECT nome FROM guiches WHERE id = %s AND ativo = 1", (guiche_id,))
            g = cur.fetchone()
            if not g:
                raise ErroSessao("Guichê inválido ou inativo.")
            cur.execute("SELECT 1 AS ok FROM usuarios WHERE id = %s AND ativo = 1", (usuario.id,))
            if not cur.fetchone():
                raise ErroSessao("Usuário inativo. Procure o gestor.")
            cur.execute(
                "INSERT INTO sessoes_guiche "
                "(usuario_id, guiche_id, maquina, guiche_aberto, usuario_aberto) "
                "VALUES (%s, %s, %s, %s, %s)",
                (usuario.id, guiche_id, MAQUINA, guiche_id, usuario.id),
            )
            sid = cur.lastrowid
            auditoria.registrar(cur, "login", usuario.id, guiche_id, detalhe=MAQUINA)
    except mysql.connector.IntegrityError as exc:
        if "uq_sessao_guiche" in str(exc):
            raise ErroSessao("Este guichê já está em uso em outra máquina.") from exc
        raise ErroSessao("Este usuário já está conectado em outro guichê.") from exc
    log.info("Sessão %s aberta: %s no %s.", sid, usuario.login, g["nome"])
    return Sessao(sid, usuario, guiche_id, g["nome"])


def ping(sessao: Sessao) -> bool:
    """False = a sessão foi encerrada no servidor (expirou/forçada)."""
    return db.execute(
        "UPDATE sessoes_guiche SET ultimo_ping = NOW() WHERE id = %s AND fim_em IS NULL",
        (sessao.id,),
    ) > 0


def _mudar_status(sessao: Sessao, status: str, acao: str) -> str:
    with db.cursor() as cur:
        cur.execute("UPDATE sessoes_guiche SET status = %s WHERE id = %s AND fim_em IS NULL",
                    (status, sessao.id))
        if cur.rowcount == 0:
            raise ErroSessao("Sessão encerrada. Entre novamente.")
        auditoria.registrar(cur, acao, sessao.usuario.id, sessao.guiche_id)
    return status


def pausar(sessao: Sessao) -> str:
    if fila_service.atendimento_aberto(sessao.guiche_id, sessao.usuario.id):
        raise ErroSessao("Finalize o atendimento atual antes de pausar.")
    return _mudar_status(sessao, "pausa", "pausa")


def retomar(sessao: Sessao) -> str:
    return _mudar_status(sessao, "ativo", "retomar")


def encerrar(sessao: Sessao, forcar: bool = False) -> None:
    if not forcar and fila_service.atendimento_aberto(sessao.guiche_id, sessao.usuario.id):
        raise ErroSessao("Finalize o atendimento atual antes de sair.")
    with db.cursor() as cur:
        cur.execute(
            "UPDATE sessoes_guiche SET fim_em = NOW(), motivo_fim = 'logout', "
            "guiche_aberto = NULL, usuario_aberto = NULL WHERE id = %s AND fim_em IS NULL",
            (sessao.id,),
        )
        auditoria.registrar(cur, "logout", sessao.usuario.id, sessao.guiche_id)
    log.info("Sessão %s encerrada.", sessao.id)


def painel_online() -> bool:
    p = parametros.obter()
    row = db.fetch_one(
        "SELECT COUNT(*) AS qtd FROM painel_heartbeat "
        "WHERE ultimo_ping >= NOW() - INTERVAL %s SECOND", (p.painel_offline_seg,))
    return bool(row and row["qtd"])


def manutencao_diaria() -> None:
    row = db.fetch_one("SELECT DATE_FORMAT(CURDATE(), '%Y-%m-%d') AS hoje")
    hoje = str(row["hoje"])                  # relógio do banco; vai como parâmetro
    venceu = db.execute(
        "UPDATE config SET valor = %s WHERE chave = 'ultima_manutencao' AND valor <> %s",
        (hoje, hoje))
    if not venceu:
        return
    log.info("Executando manutenção diária.")
    fila_service.encerrar_dias_anteriores()
    auditoria.limpar_expirados(parametros.obter().retencao_auditoria_dias)


class Heartbeat:
    def __init__(self, sessao: Sessao, ao_perder: Callable[[str], None],
                 ao_painel: Callable[[bool], None]):
        self._sessao = sessao
        self._ao_perder = ao_perder
        self._ao_painel = ao_painel
        self._parar = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def iniciar(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="heartbeat-guiche", daemon=True)
        self._thread.start()

    def parar(self) -> None:
        self._parar.set()

    def _loop(self) -> None:
        falhando = False
        while not self._parar.is_set():
            try:
                if not ping(self._sessao):
                    if not self._parar.is_set():
                        self._ao_perder("Sessão encerrada (expirou, foi encerrada pelo gestor "
                                        "ou aberta em outra máquina).")
                    return
                self._ao_painel(painel_online())
                try:
                    manutencao_diaria()
                except Exception as exc:  # noqa: BLE001
                    log.warning("Falha na manutenção diária: %s", descrever_erro(exc))
                if falhando:
                    log.info("Heartbeat restabelecido.")
                    falhando = False
            except Exception as exc:  # noqa: BLE001
                if not falhando:
                    log.warning("Falha no heartbeat: %s", descrever_erro(exc))
                    falhando = True
                self._ao_painel(False)
            self._parar.wait(max(5, parametros.obter().ping_seg))
