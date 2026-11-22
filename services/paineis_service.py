"""
Status dos painéis (painel_heartbeat), diagnóstico e reenvio de mídias.

- Online: ultimo_ping dentro de parametros.painel_offline_seg (critério do Guichê).
- Encerrado: ultimo_ping '2000-01-01' (painel fechado sem permissão de DELETE).
- Sem IP: servidor de mídias parado ou painel fora do modo Slideshow.
- O Guichê não guarda arquivos: o reenvio copia de outro painel que tenha a mídia.
- Progresso opcional (chamado NA THREAD do serviço; a UI repassa via tarefa.entregar):
  diagnosticar: progresso(indice, None) ao iniciar a etapa; progresso(indice, Etapa) ao concluir.
  reenviar:     progresso(texto, feitos, total).
"""
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from config_slideshow import SLIDESHOW
from database import db
from services import formato, midias_repo, painel_cliente, parametros, token_midias
from services.painel_cliente import ErroPainel

log = logging.getLogger(__name__)

SEM_IP = "Sem IP: servidor de mídias parado ou painel fora do modo Slideshow."
ETAPAS = ("Heartbeat recente", "IP informado pelo painel", "Conexão TCP",
          "Token de acesso", "Mídias no painel")
_SQL = ("SELECT maquina, ip, porta, versao_app, versao_slideshow, espaco_livre_mb, "
        "ultimo_ping < '2001-01-01' AS encerrado, "
        "TIMESTAMPDIFF(SECOND, ultimo_ping, NOW()) AS idade "
        "FROM painel_heartbeat ORDER BY maquina")

ProgressoDiag = Callable[[int, Optional["Etapa"]], None]
ProgressoReenvio = Callable[[str, int, int], None]


@dataclass
class Painel:
    maquina: str
    ip: Optional[str]
    porta: int
    versao_app: str
    versao_slideshow: int
    espaco_livre_mb: Optional[int]
    idade: int
    estado: str                    # online | offline | encerrado
    sincronizado: bool

    @property
    def online(self) -> bool:
        return self.estado == "online"

    @property
    def endereco(self) -> str:
        return f"{self.ip}:{self.porta}" if self.ip else "Sem IP"


@dataclass
class Etapa:
    nome: str
    estado: str                    # ok | falha | aviso | na
    detalhe: str = ""


def listar() -> tuple[list[Painel], int]:
    limite = parametros.obter().painel_offline_seg
    versao = midias_repo.versao()
    paineis = []
    for r in db.fetch_all(_SQL):
        idade = max(0, int(r["idade"] or 0))
        estado = "encerrado" if r["encerrado"] else ("online" if idade <= limite else "offline")
        vs = int(r["versao_slideshow"] or 0)
        paineis.append(Painel(r["maquina"], r["ip"] or None, int(r["porta"] or SLIDESHOW.porta),
                              r["versao_app"] or "", vs, r["espaco_livre_mb"], idade, estado,
                              versao > 0 and vs == versao))
    return paineis, versao


def destinos() -> list[Painel]:
    """Painéis online com servidor de mídias (recebem envios)."""
    return [p for p in listar()[0] if p.online and p.ip]


def enviar(p: Painel, token: str, caminho: Path, nome: str,
           progresso: Optional[Callable[[int, int], None]] = None) -> bool:
    """PUT com nova tentativa enquanto o token recém-gerado não chega ao painel."""
    limite = time.monotonic() + SLIDESHOW.token_cache_segundos + 5
    while True:
        try:
            return painel_cliente.enviar(p.ip, p.porta, token, caminho, nome, progresso)
        except ErroPainel as exc:
            if exc.codigo != 401 or not token_midias.recente() or time.monotonic() > limite:
                raise
            time.sleep(3)


# ---- Reenvio ------------------------------------------------------------
def _fontes(token: str, exceto: str) -> list[tuple[Painel, set]]:
    fontes = []
    for p in destinos():
        if p.maquina == exceto:
            continue
        try:
            fontes.append((p, set(painel_cliente.status(p.ip, p.porta, token).get("midias") or [])))
        except ErroPainel as exc:
            log.debug("Painel %s indisponível como fonte: %s", p.maquina, exc)
    return fontes


def _copiar(sha: str, ext: str, fontes, destino: Painel, token: str) -> Optional[str]:
    nome, ultimo = f"{sha}.{ext}", None
    for fonte, shas in fontes:
        if sha not in shas:
            continue
        fd, tmp = tempfile.mkstemp(prefix="reenvio_", suffix=f".{ext}")
        os.close(fd)
        tmp = Path(tmp)
        try:
            painel_cliente.baixar(fonte.ip, fonte.porta, token, nome, tmp, SLIDESHOW.max_bytes)
            enviar(destino, token, tmp, nome)
            return None
        except ErroPainel as exc:
            ultimo = f"{fonte.maquina}: {exc}"
        finally:
            tmp.unlink(missing_ok=True)
    return ultimo or "nenhum painel online possui o arquivo"


def reenviar(p: Painel, progresso: Optional[ProgressoReenvio] = None) -> str:
    """Copia ao painel as mídias ativas que faltam nele, baixando-as de outro painel online."""
    def avisar(texto: str, feitos: int = 0, total: int = 0) -> None:
        if progresso:
            progresso(texto, feitos, total)

    if not p.ip:
        raise ErroPainel(0, SEM_IP)
    token = token_midias.ler()
    if not token:
        raise ErroPainel(0, "Token ainda não gerado (é criado no primeiro cadastro).")
    avisar(f"Consultando as mídias presentes em {p.maquina}…")
    presentes = set(painel_cliente.status(p.ip, p.porta, token).get("midias") or [])
    faltando = [(s, e) for s, e in midias_repo.ativas() if s not in presentes]
    if not faltando:
        return f"{p.maquina} já possui todas as mídias ativas. Nada foi enviado."
    total = len(faltando)
    avisar(f"Faltam {total} mídia(s). Procurando outro painel que as possua…", 0, total)
    fontes = _fontes(token, p.maquina)
    enviados, erros = 0, []
    for i, (sha, ext) in enumerate(faltando, 1):
        avisar(f"Copiando mídia {i} de {total}…", i - 1, total)
        erro = _copiar(sha, ext, fontes, p, token)
        if erro:
            erros.append(f"{sha[:12]}…: {erro}")
        else:
            enviados += 1
        avisar(f"Copiando mídia {i} de {total}…", i, total)
    texto = f"{enviados} de {total} mídia(s) enviada(s) para {p.maquina}."
    if erros:
        texto += "\n\nFalhas:\n" + "\n".join(erros[:10])
    return texto


# ---- Diagnóstico ------------------------------------------------------
def diagnosticar(p: Optional[Painel] = None, ip: Optional[str] = None,
                 porta: Optional[int] = None,
                 progresso: Optional[ProgressoDiag] = None) -> list[Etapa]:
    etapas: list[Etapa] = []

    def iniciar() -> None:
        if progresso:
            progresso(len(etapas), None)

    def add(estado: str, detalhe: str) -> None:
        e = Etapa(ETAPAS[len(etapas)], estado, detalhe)
        etapas.append(e)
        if progresso:
            progresso(len(etapas) - 1, e)

    def pular() -> list[Etapa]:
        while len(etapas) < len(ETAPAS):
            add("na", "Não executado.")
        return etapas

    if p is None:
        avulso = "Diagnóstico avulso por IP:porta."
        add("na", avulso)
        add("na", avulso)
    else:
        ip, porta = p.ip, p.porta
        iniciar()
        if p.online:
            add("ok", f"Último ping {formato.idade(p.idade)}.")
        elif p.estado == "encerrado":
            add("falha", "Painel encerrado.")
        else:
            add("falha", f"Último ping {formato.idade(p.idade)}.")
        iniciar()
        if not ip:
            add("falha", SEM_IP)
            return pular()
        add("ok", f"{ip}:{porta}")

    iniciar()
    try:
        painel_cliente.testar_tcp(ip, porta)
        add("ok", f"{ip}:{porta} acessível.")
    except ErroPainel as exc:
        add("falha", f"{exc} Verifique o firewall do painel.")
        return pular()

    iniciar()
    token = token_midias.ler()
    if not token:
        add("falha", "Token ainda não gerado (é criado no primeiro cadastro).")
        return pular()
    try:
        st = painel_cliente.status(ip, porta, token)
    except ErroPainel as exc:
        if exc.codigo == 401 and token_midias.recente():
            add("aviso", "Token recém-gerado; aguarde 30 s e repita.")
        elif exc.codigo == 401:
            add("falha", "Token divergente: o painel usa outro banco ou token antigo.")
        else:
            add("falha", str(exc))
        return pular()
    add("ok", f"Token aceito (painel v{st.get('versao_app', '?')}).")

    iniciar()
    ativas = midias_repo.ativas()
    presentes = set(st.get("midias") or [])
    faltam = sum(1 for s, _e in ativas if s not in presentes)
    det = (f"{len(ativas) - faltam} de {len(ativas)} mídia(s) ativa(s) presentes; "
           f"{formato.espaco(st.get('espaco_livre_mb'))}.")
    add("aviso" if faltam else "ok", det + (" Use Reenviar mídias." if faltam else ""))
    return etapas
