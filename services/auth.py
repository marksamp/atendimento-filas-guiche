"""
Autenticação dos usuários do Guichê.

- bcrypt; senha_hash NULL = primeiro acesso com a senha provisória 'admin'
  (troca obrigatória).
- Bloqueio após login_max_tentativas erros, por login_bloqueio_min minutos.
- Mensagem genérica para usuário inexistente/senha errada (não revela logins).
- Setores atendidos: ativos + inativos com senhas pendentes hoje (esvaziar a fila).
  Sem vínculos → todos esses; com vínculos → só os vinculados.
"""
import logging
from dataclasses import dataclass, field

import bcrypt

from database import db
from services import auditoria, parametros
from services.erros import ErroNegocio

log = logging.getLogger(__name__)

SENHA_PROVISORIA = "admin"
_INVALIDO = "Usuário ou senha inválidos."
_HASH_FALSO = bcrypt.hashpw(b"tempo-constante", bcrypt.gensalt())
_ATENDIVEL = (
    "(st.ativo = 1 OR EXISTS (SELECT 1 FROM senhas s WHERE s.setor_id = st.id "
    "AND s.status IN ('aguardando','chamando','em_atendimento','ausente') "
    "AND s.emitida_em >= CURDATE() AND s.emitida_em < CURDATE() + INTERVAL 1 DAY))"
)


class ErroLogin(ErroNegocio):
    """Mensagem segura para a tela."""


@dataclass
class Usuario:
    id: int
    login: str
    nome: str
    perfil: str
    trocar_senha: bool
    setores: list[dict] = field(default_factory=list)

    @property
    def gestor(self) -> bool:
        return self.perfil == "gestor"

    @property
    def setor_ids(self) -> list[int]:
        return [int(s["id"]) for s in self.setores]


def _confere(senha: str, hash_: str | None) -> bool:
    if hash_ is None:
        return senha == SENHA_PROVISORIA
    try:
        return bcrypt.checkpw(senha.encode("utf-8"), hash_.encode("ascii"))
    except ValueError:
        return False


def _setores(cur, usuario_id: int) -> tuple[list[dict], bool]:
    """(setores atendíveis, possui_vinculos)."""
    cur.execute("SELECT COUNT(*) AS n FROM usuario_setores WHERE usuario_id = %s",
                (usuario_id,))
    vinculado = int(cur.fetchone()["n"]) > 0
    if vinculado:
        cur.execute(
            "SELECT st.id, st.nome, st.prefixo, st.cor, st.ativo FROM usuario_setores us "
            "JOIN setores st ON st.id = us.setor_id "
            f"WHERE us.usuario_id = %s AND {_ATENDIVEL} ORDER BY st.ordem, st.nome",
            (usuario_id,),
        )
    else:
        cur.execute("SELECT st.id, st.nome, st.prefixo, st.cor, st.ativo FROM setores st "
                    f"WHERE {_ATENDIVEL} ORDER BY st.ordem, st.nome")
    return cur.fetchall(), vinculado


def autenticar(login: str, senha: str) -> Usuario:
    login = (login or "").strip().lower()
    if not login or not senha:
        raise ErroLogin("Informe usuário e senha.")
    p = parametros.obter()
    erro, usuario, vinculado = None, None, False

    with db.cursor() as cur:
        cur.execute(
            "SELECT id, login, nome, senha_hash, perfil, ativo, trocar_senha, "
            "       tentativas_falhas, COALESCE(bloqueado_ate > NOW(), 0) AS bloqueado, "
            "       CEIL(GREATEST(0, TIMESTAMPDIFF(SECOND, NOW(), bloqueado_ate)) / 60) AS resta "
            "FROM usuarios WHERE login = %s FOR UPDATE",
            (login,),
        )
        u = cur.fetchone()
        if not u or not u["ativo"]:
            bcrypt.checkpw(b"x", _HASH_FALSO)
            raise ErroLogin(_INVALIDO)
        if u["bloqueado"]:
            raise ErroLogin(f"Usuário bloqueado. Tente novamente em {int(u['resta'] or 1)} min.")

        if _confere(senha, u["senha_hash"]):
            cur.execute(
                "UPDATE usuarios SET tentativas_falhas = 0, bloqueado_ate = NULL, "
                "ultimo_login_em = NOW() WHERE id = %s", (u["id"],))
            setores, vinculado = _setores(cur, u["id"])
            usuario = Usuario(u["id"], u["login"], u["nome"], u["perfil"],
                              bool(u["trocar_senha"]) or u["senha_hash"] is None, setores)
        else:
            falhas = int(u["tentativas_falhas"]) + 1
            if falhas >= p.login_max_tentativas:
                cur.execute(
                    "UPDATE usuarios SET tentativas_falhas = 0, "
                    "bloqueado_ate = NOW() + INTERVAL %s MINUTE WHERE id = %s",
                    (p.login_bloqueio_min, u["id"]))
                erro = f"Muitas tentativas. Usuário bloqueado por {p.login_bloqueio_min} min."
                log.warning("Login '%s' bloqueado por excesso de tentativas.", login)
            else:
                cur.execute("UPDATE usuarios SET tentativas_falhas = %s WHERE id = %s",
                            (falhas, u["id"]))
                erro = _INVALIDO

    if erro:
        raise ErroLogin(erro)
    if not usuario.setores:
        raise ErroLogin("Os setores vinculados ao usuário estão inativos. Procure o gestor."
                        if vinculado else "Nenhum setor ativo no sistema. Procure o gestor.")
    return usuario


def validar_nova_senha(atual: str, nova: str, confirmacao: str) -> dict[str, str]:
    p = parametros.obter()
    erros: dict[str, str] = {}
    if not atual:
        erros["atual"] = "Informe a senha atual."
    if len(nova) < p.senha_min:
        erros["nova"] = f"Mínimo de {p.senha_min} caracteres."
    elif nova == atual or nova.lower() == SENHA_PROVISORIA:
        erros["nova"] = "Escolha uma senha diferente."
    if nova != confirmacao:
        erros["confirmacao"] = "As senhas não conferem."
    return erros


def trocar_senha(usuario_id: int, atual: str, nova: str, confirmacao: str) -> None:
    erros = validar_nova_senha(atual, nova, confirmacao)
    if erros:
        raise ErroLogin(next(iter(erros.values())))
    novo_hash = bcrypt.hashpw(nova.encode("utf-8"), bcrypt.gensalt(12)).decode("ascii")
    with db.cursor() as cur:
        cur.execute("SELECT senha_hash FROM usuarios WHERE id = %s AND ativo = 1 FOR UPDATE",
                    (usuario_id,))
        u = cur.fetchone()
        if not u or not _confere(atual, u["senha_hash"]):
            raise ErroLogin("Senha atual incorreta.")
        cur.execute("UPDATE usuarios SET senha_hash = %s, trocar_senha = 0 WHERE id = %s",
                    (novo_hash, usuario_id))
        auditoria.registrar(cur, "troca_senha", usuario_id)
    log.info("Senha alterada (usuário %s).", usuario_id)
