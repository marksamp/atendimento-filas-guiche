"""
Regras do cadastro de setores (somente gestor).
- Prefixo: 1 ou 2 letras A-Z, único (uq_setores_prefixo). Nome único (checado aqui).
- Cor livre #RRGGBB; ícone 'tabler:<nome>', legado sem prefixo ou 'arquivo:<16 hex>'.
- Ícone PNG (icone_png/icone_hash) gravado na mesma transação; só regera se o ícone mudar.
  Para 'arquivo:', a tela envia dados["icone_png"] (bytes de icone_png.gerar_png_arquivo).
- Desativar: o Totem deixa de emitir; as senhas já emitidas continuam sendo atendidas.
- Mínimo de 1 setor ativo.
- Exclusão só sem senhas (histórico); controle_fila/sequencias/vínculos/letreiro em CASCADE.
- Ordem: mover() troca o setor com o vizinho (botões ↑/↓).
"""
import logging
import re
from typing import Optional

from mysql.connector import errorcode, errors

from database import db, descrever_erro
from services import auditoria, setores_repo
from services import icone_png as gerador
from services.auth import Usuario
from services.erros import ErroNegocio

log = logging.getLogger(__name__)

NOME_MAX, DESC_MAX, ICONE_MAX = 80, 160, 64
_PREFIXO_RE = re.compile(r"^[A-Z]{1,2}$")
_COR_RE = re.compile(r"^#[0-9A-F]{6}$")
_ICONE_RE = re.compile(r"^(tabler:[a-z0-9-]+|arquivo:[0-9a-f]{16}|[a-z0-9-]+)$")
_DUPLICADO = "Já existe um setor com este prefixo."
_RECUSADO = "O banco recusou a exclusão: o setor possui registros vinculados. Use Desativar."
_FK_REFERENCIADO = (errorcode.ER_ROW_IS_REFERENCED, errorcode.ER_ROW_IS_REFERENCED_2)


class ErroSetores(ErroNegocio):
    """Mensagem segura para a tela."""


def mensagem(exc: BaseException) -> str:
    if isinstance(exc, ErroSetores):
        return str(exc)
    if isinstance(exc, errors.IntegrityError):
        if exc.errno == errorcode.ER_DUP_ENTRY:
            return _DUPLICADO
        if exc.errno in _FK_REFERENCIADO:
            return _RECUSADO
    return descrever_erro(exc, db.settings)


def _exigir_gestor(usuario: Usuario) -> None:
    if not usuario.gestor:
        raise ErroSetores("Somente gestores podem alterar os setores.")


def _texto(v: Optional[str]) -> str:
    return " ".join((v or "").split())


def normalizar(d: dict) -> dict:
    return {
        "nome": _texto(d.get("nome")),
        "descricao": _texto(d.get("descricao")) or None,
        "prefixo": (d.get("prefixo") or "").strip().upper(),
        "icone": (d.get("icone") or "").strip().lower() or None,
        "cor": (d.get("cor") or "").strip().upper(),
    }


def validar(d: dict) -> dict[str, str]:
    """Validação local (instantânea no formulário). Chaves = campos do formulário."""
    n = normalizar(d)
    erros: dict[str, str] = {}
    if not n["nome"]:
        erros["nome"] = "Informe o nome."
    elif len(n["nome"]) > NOME_MAX:
        erros["nome"] = f"Nome com no máximo {NOME_MAX} caracteres."
    if n["descricao"] and len(n["descricao"]) > DESC_MAX:
        erros["descricao"] = f"Descrição com no máximo {DESC_MAX} caracteres."
    if not _PREFIXO_RE.match(n["prefixo"]):
        erros["prefixo"] = "Prefixo: 1 ou 2 letras (A-Z)."
    if not _COR_RE.match(n["cor"]):
        erros["cor"] = "Cor no formato #RRGGBB."
    if n["icone"] and (len(n["icone"]) > ICONE_MAX or not _ICONE_RE.match(n["icone"])):
        erros["icone"] = "Ícone inválido."
    return erros


def listar() -> list[dict]:
    with db.cursor() as cur:
        return setores_repo.listar(cur)


def obter_png(sid: int) -> Optional[bytes]:
    """PNG gravado (prévia na tela)."""
    with db.cursor() as cur:
        return setores_repo.obter_png(cur, sid)


def _checar(cur, dados: dict, sid: Optional[int]) -> dict:
    erros = validar(dados)
    if erros:
        raise ErroSetores(next(iter(erros.values())))
    d = normalizar(dados)
    if setores_repo.prefixo_em_uso(cur, d["prefixo"], sid):
        raise ErroSetores(_DUPLICADO)
    if setores_repo.nome_em_uso(cur, d["nome"], sid):
        raise ErroSetores("Já existe um setor com este nome.")
    return d


def _png_do_icone(icone: Optional[str], dados: dict) -> Optional[bytes]:
    """PNG do contrato para o ícone informado (None = sem ícone)."""
    if icone and icone.startswith(gerador.PREFIXO_ARQUIVO):
        png = dados.get("icone_png")
        if not png or gerador.icone_arquivo(png) != icone:
            raise ErroSetores("Escolha o arquivo do ícone novamente.")
        png = bytes(png)
    else:
        png = gerador.gerar_png(icone)
    if png and len(png) > gerador.TAM_MAX:
        raise ErroSetores(f"O ícone ficou com {len(png) // 1024} KB "
                          f"(máximo {gerador.TAM_MAX // 1024} KB). Escolha outro ícone.")
    return png


def _gravar_icone(cur, sid: int, png: Optional[bytes]) -> None:
    setores_repo.gravar_icone(cur, sid, png, gerador.hash_png(png) if png else None)


def _obter(cur, sid: int) -> dict:
    atual = setores_repo.obter(cur, sid, travar=True)
    if not atual:
        raise ErroSetores("Setor não encontrado.")
    return atual


def _exigir_outro_ativo(cur, atual: dict) -> None:
    if atual["ativo"] and not setores_repo.outros_ativos(cur, atual["id"]):
        raise ErroSetores("É necessário manter ao menos um setor ativo.")


def cadastrar(usuario: Usuario, dados: dict) -> int:
    _exigir_gestor(usuario)
    with db.cursor() as cur:
        d = _checar(cur, dados, None)
        png = _png_do_icone(d["icone"], dados)
        sid = setores_repo.inserir(cur, d)
        _gravar_icone(cur, sid, png)
        auditoria.registrar(cur, "setor_cadastrar", usuario.id,
                            detalhe=f"id={sid} prefixo={d['prefixo']}")
    log.info("Setor %s cadastrado por %s.", sid, usuario.id)
    return sid


def editar(usuario: Usuario, sid: int, dados: dict) -> None:
    _exigir_gestor(usuario)
    with db.cursor() as cur:
        atual = _obter(cur, sid)
        d = _checar(cur, dados, sid)
        if all(d[k] == atual[k] for k in d):
            return
        icone_mudou = d["icone"] != atual["icone"]
        png = _png_do_icone(d["icone"], dados) if icone_mudou else None
        setores_repo.atualizar(cur, sid, d)
        if icone_mudou:
            _gravar_icone(cur, sid, png)
        auditoria.registrar(cur, "setor_editar", usuario.id,
                            detalhe=f"id={sid} prefixo={atual['prefixo']}->{d['prefixo']}")


def regenerar_icones(usuario: Usuario) -> tuple[int, int]:
    """Regera icone_png/icone_hash de todos. 'arquivo:' mantém o PNG. -> (gerados, sem_icone)."""
    _exigir_gestor(usuario)
    gerados = sem_icone = 0
    with db.cursor() as cur:
        for r in setores_repo.icones_para_regerar(cur):
            icone = r["icone"] or ""
            if icone.startswith(gerador.PREFIXO_ARQUIVO):
                png = bytes(r["icone_png"]) if r["icone_png"] else None
            else:
                png = gerador.gerar_png(icone)
            if png and len(png) > gerador.TAM_MAX:
                log.warning("Setor %s: ícone acima de %s bytes; gravado NULL.",
                            r["id"], gerador.TAM_MAX)
                png = None
            _gravar_icone(cur, int(r["id"]), png)
            if png:
                gerados += 1
            else:
                sem_icone += 1
        auditoria.registrar(cur, "setor_icones", usuario.id,
                            detalhe=f"gerados={gerados} sem_icone={sem_icone}")
    log.info("Ícones regenerados por %s: %s gerados, %s sem ícone.",
             usuario.id, gerados, sem_icone)
    return gerados, sem_icone


def definir_ativo(usuario: Usuario, sid: int, ativo: bool) -> None:
    _exigir_gestor(usuario)
    with db.cursor() as cur:
        atual = _obter(cur, sid)
        if bool(atual["ativo"]) == ativo:
            return
        if not ativo:
            _exigir_outro_ativo(cur, atual)
        setores_repo.definir_ativo(cur, sid, ativo)
        auditoria.registrar(cur, "setor_ativar" if ativo else "setor_desativar",
                            usuario.id, detalhe=f"id={sid} pendentes={atual['pendentes']}")


def mover(usuario: Usuario, sid: int, passo: int) -> bool:
    """passo -1 = sobe, +1 = desce. False se já está no limite."""
    _exigir_gestor(usuario)
    with db.cursor() as cur:
        ids = setores_repo.ids_ordenados(cur)
        if sid not in ids:
            raise ErroSetores("Setor não encontrado.")
        i = ids.index(sid)
        j = i + (1 if passo > 0 else -1)
        if not 0 <= j < len(ids):
            return False
        ids[i], ids[j] = ids[j], ids[i]
        setores_repo.gravar_ordem(cur, ids)
        auditoria.registrar(cur, "setor_ordem", usuario.id, detalhe=f"id={sid} pos={j + 1}")
    return True


def excluir(usuario: Usuario, sid: int) -> None:
    """Exclui só setor sem senhas; recusa do banco vira _RECUSADO via mensagem()."""
    _exigir_gestor(usuario)
    with db.cursor() as cur:
        atual = _obter(cur, sid)
        if atual["tem_historico"]:
            raise ErroSetores("Setor com senhas emitidas. Use Desativar.")
        _exigir_outro_ativo(cur, atual)
        if not setores_repo.excluir(cur, sid):
            raise ErroSetores("Setor não encontrado.")
        auditoria.registrar(cur, "setor_excluir", usuario.id,
                            detalhe=f"id={sid} prefixo={atual['prefixo']} nome={atual['nome']}"[:255])
    log.info("Setor %s excluído por %s.", sid, usuario.id)
