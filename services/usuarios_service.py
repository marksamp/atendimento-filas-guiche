"""
Regras do cadastro de usuários (somente gestor).
- Login: a-z0-9, 6 a 40 (o legado 'admin' é aceito enquanto não for alterado).
- Nome e sobrenome; senha com no mínimo parametros.senha_min (bcrypt).
- Sem setores = atende todos os setores ativos.
- Mínimo de 1 gestor ativo; o gestor não pode desativar/excluir/rebaixar a si mesmo.
- Desativar/excluir: encerra a sessão aberta e libera as senhas do usuário.
- Exclusão só sem histórico de atendimento; com histórico: desativar.
"""
import logging
import re
from typing import Optional

import bcrypt
from mysql.connector import errorcode, errors

from database import db, descrever_erro
from services import auditoria, fila_service, parametros, sessao, usuarios_repo
from services.auth import Usuario
from services.erros import ErroNegocio

log = logging.getLogger(__name__)

LOGIN_MAX, NOME_MAX = 40, 100
PERFIS = ("atendente", "gestor")
_LOGIN_RE = re.compile(r"^[a-z0-9]{6,40}$")
_LEGADO = "admin"
_DUPLICADO = "Já existe um usuário com este login."
_RECUSADO = "O banco recusou a exclusão: o usuário possui registros vinculados. Use Desativar."
_FK_REFERENCIADO = (errorcode.ER_ROW_IS_REFERENCED, errorcode.ER_ROW_IS_REFERENCED_2)


class ErroUsuarios(ErroNegocio):
    """Mensagem segura para a tela."""


def mensagem(exc: BaseException) -> str:
    if isinstance(exc, ErroUsuarios):
        return str(exc)
    if isinstance(exc, errors.IntegrityError):
        if exc.errno == errorcode.ER_DUP_ENTRY:
            return _DUPLICADO
        if exc.errno in _FK_REFERENCIADO:
            return _RECUSADO
    return descrever_erro(exc, db.settings)


def _exigir_gestor(usuario: Usuario) -> None:
    if not usuario.gestor:
        raise ErroUsuarios("Somente gestores podem alterar os usuários.")


def _nome(v: Optional[str]) -> str:
    return " ".join((v or "").split())


def _login(v: Optional[str]) -> str:
    return (v or "").strip().lower()


def _hash(senha: str) -> str:
    return bcrypt.hashpw(senha.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def listar() -> list[dict]:
    with db.cursor() as cur:
        return usuarios_repo.listar(cur)


def listar_setores() -> list[dict]:
    return fila_service.listar_setores()


def validar(d: dict, editar: bool = False, login_atual: str = "") -> dict[str, str]:
    """Validação local (instantânea no formulário). Chaves = campos do formulário."""
    erros: dict[str, str] = {}
    login, nome = _login(d.get("login")), _nome(d.get("nome"))
    if not login:
        erros["login"] = "Informe o login."
    elif not (login == _LEGADO and login == login_atual) and not _LOGIN_RE.match(login):
        erros["login"] = "Login: 6 a 40 letras minúsculas ou números, sem espaços."
    if not nome:
        erros["nome"] = "Informe o nome."
    elif len(nome) > NOME_MAX:
        erros["nome"] = f"Nome com no máximo {NOME_MAX} caracteres."
    elif len(nome.split()) < 2:
        erros["nome"] = "Informe nome e sobrenome."
    if d.get("perfil") not in PERFIS:
        erros["perfil"] = "Perfil inválido."
    senha, conf = d.get("senha") or "", d.get("confirmacao") or ""
    if senha or conf or not editar:
        minimo = parametros.obter().senha_min
        if len(senha) < minimo:
            erros["senha"] = f"Senha com no mínimo {minimo} caracteres."
        elif senha != conf:
            erros["confirmacao"] = "As senhas não conferem."
    return erros


def _checar(cur, d: dict, uid: Optional[int], login_atual: str = "") -> tuple[str, str]:
    erros = validar(d, uid is not None, login_atual)
    if erros:
        raise ErroUsuarios(next(iter(erros.values())))
    login = _login(d["login"])
    if usuarios_repo.login_em_uso(cur, login, uid):
        raise ErroUsuarios(_DUPLICADO)
    return login, _nome(d["nome"])


def _obter(cur, uid: int) -> dict:
    atual = usuarios_repo.obter(cur, uid, travar=True)
    if not atual:
        raise ErroUsuarios("Usuário não encontrado.")
    return atual


def _exigir_outro_gestor(cur, atual: dict) -> None:
    if atual["perfil"] == "gestor" and atual["ativo"] \
            and not usuarios_repo.outros_gestores_ativos(cur, atual["id"]):
        raise ErroUsuarios("É necessário manter ao menos um gestor ativo.")


def _derrubar(cur, gestor: Usuario, uid: int, motivo: str) -> None:
    sessao.encerrar_do_usuario(cur, uid, gestor.id)
    fila_service.liberar_abertas(cur, uid, motivo)


def cadastrar(gestor: Usuario, dados: dict) -> int:
    _exigir_gestor(gestor)
    with db.cursor() as cur:
        login, nome = _checar(cur, dados, None)
        uid = usuarios_repo.inserir(cur, login, nome, dados["perfil"], _hash(dados["senha"]))
        usuarios_repo.gravar_setores(cur, uid, dados.get("setores") or [])
        auditoria.registrar(cur, "usuario_cadastrar", gestor.id,
                            detalhe=f"id={uid} login={login} perfil={dados['perfil']}"[:255])
    log.info("Usuário %s cadastrado por %s.", uid, gestor.id)
    return uid


def editar(gestor: Usuario, uid: int, dados: dict) -> None:
    _exigir_gestor(gestor)
    with db.cursor() as cur:
        atual = _obter(cur, uid)
        login, nome = _checar(cur, dados, uid, atual["login"])
        perfil = dados["perfil"]
        if perfil != "gestor" and atual["perfil"] == "gestor":
            if uid == gestor.id:
                raise ErroUsuarios("Você não pode remover o seu próprio perfil de gestor.")
            _exigir_outro_gestor(cur, atual)
        usuarios_repo.atualizar(cur, uid, login, nome, perfil)
        usuarios_repo.gravar_setores(cur, uid, dados.get("setores") or [])
        if dados.get("senha"):
            usuarios_repo.definir_senha(cur, uid, _hash(dados["senha"]))
        auditoria.registrar(cur, "usuario_editar", gestor.id,
                            detalhe=(f"id={uid} login={atual['login']}->{login} "
                                     f"perfil={perfil}{' senha' if dados.get('senha') else ''}")[:255])


def definir_ativo(gestor: Usuario, uid: int, ativo: bool) -> None:
    _exigir_gestor(gestor)
    with db.cursor() as cur:
        atual = _obter(cur, uid)
        if bool(atual["ativo"]) == ativo:
            return
        if not ativo:
            if uid == gestor.id:
                raise ErroUsuarios("Você não pode desativar o seu próprio usuário.")
            _exigir_outro_gestor(cur, atual)
            _derrubar(cur, gestor, uid, "usuario_desativado")
        usuarios_repo.definir_ativo(cur, uid, ativo)
        auditoria.registrar(cur, "usuario_ativar" if ativo else "usuario_desativar",
                            gestor.id, detalhe=f"id={uid}")


def desbloquear(gestor: Usuario, uid: int) -> None:
    _exigir_gestor(gestor)
    with db.cursor() as cur:
        _obter(cur, uid)
        usuarios_repo.desbloquear(cur, uid)
        auditoria.registrar(cur, "usuario_desbloquear", gestor.id, detalhe=f"id={uid}")


def encerrar_sessao(gestor: Usuario, uid: int) -> None:
    _exigir_gestor(gestor)
    if uid == gestor.id:
        raise ErroUsuarios("Use Sair para encerrar a sua própria sessão.")
    with db.cursor() as cur:
        _obter(cur, uid)
        if not sessao.encerrar_do_usuario(cur, uid, gestor.id):
            raise ErroUsuarios("O usuário não possui sessão aberta.")
        fila_service.liberar_abertas(cur, uid, "sessao_encerrada")


def excluir(gestor: Usuario, uid: int) -> None:
    """Exclui só usuário sem histórico; recusa do banco vira _RECUSADO via mensagem()."""
    _exigir_gestor(gestor)
    if uid == gestor.id:
        raise ErroUsuarios("Você não pode excluir o seu próprio usuário.")
    with db.cursor() as cur:
        atual = _obter(cur, uid)
        if atual["tem_historico"]:
            raise ErroUsuarios("Usuário com histórico de atendimento. Use Desativar.")
        _exigir_outro_gestor(cur, atual)
        _derrubar(cur, gestor, uid, "usuario_excluido")
        if not usuarios_repo.excluir(cur, uid):
            raise ErroUsuarios("Usuário não encontrado.")
        auditoria.registrar(cur, "usuario_excluir", gestor.id,
                            detalhe=f"id={uid} login={atual['login']}"[:255])
    log.info("Usuário %s excluído por %s.", uid, gestor.id)
