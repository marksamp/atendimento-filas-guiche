"""
Regras do cadastro de guichês (somente gestor).
- Guichê sem setor: os setores atendidos vêm do usuário (usuario_setores).
- Exclusão física só para guichê sem histórico (senhas/sessões); o banco é a
  última barreira (FK -> ER_ROW_IS_REFERENCED). Com histórico: desativar.
- Não desativa com sessão aberta ou senha chamando/em atendimento.
- Nome único: checado aqui e garantido por uq_guiches_nome (corrida entre gestores).
"""
import logging
from typing import Optional

from mysql.connector import errorcode, errors

from database import db, descrever_erro
from services import auditoria, guiches_repo
from services.auth import Usuario
from services.erros import ErroNegocio

log = logging.getLogger(__name__)

NOME_MAX = 40
_DUPLICADO = "Já existe um guichê com este nome."
_COM_HISTORICO = "Guichê com histórico. Use Desativar."
_RECUSADO = "O banco recusou a exclusão: o guichê possui registros vinculados. Use Desativar."
_FK_REFERENCIADO = (errorcode.ER_ROW_IS_REFERENCED, errorcode.ER_ROW_IS_REFERENCED_2)


class ErroGuiches(ErroNegocio):
    """Mensagem segura para a tela."""


def mensagem(exc: BaseException) -> str:
    if isinstance(exc, ErroGuiches):
        return str(exc)
    if isinstance(exc, errors.IntegrityError):
        if exc.errno == errorcode.ER_DUP_ENTRY:
            return _DUPLICADO
        if exc.errno in _FK_REFERENCIADO:
            return _RECUSADO
    return descrever_erro(exc, db.settings)


def _exigir_gestor(usuario: Usuario) -> None:
    if not usuario.gestor:
        raise ErroGuiches("Somente gestores podem alterar os guichês.")


def _normalizar(nome: Optional[str]) -> str:
    return " ".join((nome or "").split())


def listar() -> list[dict]:
    with db.cursor() as cur:
        return guiches_repo.listar(cur)


def validar(d: dict) -> dict[str, str]:
    erros: dict[str, str] = {}
    nome = _normalizar(d.get("nome"))
    if not nome:
        erros["nome"] = "Informe o nome."
    elif len(nome) > NOME_MAX:
        erros["nome"] = f"Nome com no máximo {NOME_MAX} caracteres."
    return erros


def _checar(cur, d: dict, gid: Optional[int]) -> str:
    erros = validar(d)
    if erros:
        raise ErroGuiches(next(iter(erros.values())))
    nome = _normalizar(d["nome"])
    if guiches_repo.nome_em_uso(cur, nome, gid):
        raise ErroGuiches(_DUPLICADO)
    return nome


def cadastrar(usuario: Usuario, dados: dict) -> int:
    _exigir_gestor(usuario)
    with db.cursor() as cur:
        nome = _checar(cur, dados, None)
        gid = guiches_repo.inserir(cur, nome)
        auditoria.registrar(cur, "guiche_cadastrar", usuario.id, guiche_id=gid,
                            detalhe=f"id={gid}")
    log.info("Guichê %s cadastrado por %s.", gid, usuario.id)
    return gid


def editar(usuario: Usuario, gid: int, dados: dict) -> None:
    _exigir_gestor(usuario)
    with db.cursor() as cur:
        atual = guiches_repo.obter(cur, gid, travar=True)
        if not atual:
            raise ErroGuiches("Guichê não encontrado.")
        nome = _checar(cur, dados, gid)
        if nome == atual["nome"]:
            return
        guiches_repo.atualizar(cur, gid, nome)
        auditoria.registrar(cur, "guiche_editar", usuario.id, guiche_id=gid,
                            detalhe=f"id={gid} nome={atual['nome']}->{nome}"[:255])


def definir_ativo(usuario: Usuario, gid: int, ativo: bool) -> None:
    _exigir_gestor(usuario)
    with db.cursor() as cur:
        atual = guiches_repo.obter(cur, gid, travar=True)
        if not atual:
            raise ErroGuiches("Guichê não encontrado.")
        if bool(atual["ativo"]) == ativo:
            return
        if not ativo:
            if atual["em_uso"]:
                raise ErroGuiches("Guichê com sessão aberta. Encerre a sessão antes.")
            if atual["atendendo"]:
                raise ErroGuiches("Guichê com senha chamando ou em atendimento.")
        guiches_repo.definir_ativo(cur, gid, ativo)
        auditoria.registrar(cur, "guiche_ativar" if ativo else "guiche_desativar",
                            usuario.id, guiche_id=gid, detalhe=f"id={gid}")


def excluir(usuario: Usuario, gid: int) -> None:
    """Exclui só guichê sem histórico; recusa do banco vira _RECUSADO via mensagem()."""
    _exigir_gestor(usuario)
    with db.cursor() as cur:
        atual = guiches_repo.obter(cur, gid, travar=True)
        if not atual:
            raise ErroGuiches("Guichê não encontrado.")
        if atual["tem_historico"]:
            raise ErroGuiches(_COM_HISTORICO)
        if not guiches_repo.excluir(cur, gid):
            raise ErroGuiches("Guichê não encontrado.")
        auditoria.registrar(cur, "guiche_excluir", usuario.id, guiche_id=None,
                            detalhe=f"id={gid} nome={atual['nome']}"[:255])
    log.info("Guichê %s excluído por %s.", gid, usuario.id)
