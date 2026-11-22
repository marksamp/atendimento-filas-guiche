"""
Regras do cadastro de mídias (somente gestor).

Cadastro: valida -> analisa/prepara o arquivo -> garante token -> envia aos
painéis online (pelo menos um precisa receber) -> INSERT + versão + auditoria
na mesma transação. O INSERT precisa ocorrer antes da carência de órfãos dos
painéis (10 min). Toda alteração incrementa config.slideshow.versao.
GIF = tipo "imagem"; avisos do arquivo (ex.: quadros demais) não bloqueiam.

Progresso (opcional, chamado na thread de trabalho):
  ("etapa", texto) | ("analisado", ArquivoMidia) | ("destinos", [maquinas])
  ("envio", maquina, enviados, total) | ("recebido", maquina, novo) | ("falha", maquina, msg)
"""
import logging
import math
import time
from pathlib import Path
from typing import Callable, Optional

from config_slideshow import EXT_IMAGEM, EXT_VIDEO, SLIDESHOW
from database import db, descrever_erro
from services import (auditoria, midias_arquivo, midias_repo, miniaturas, paineis_service,
                      token_midias)
from services.auth import Usuario
from services.midias_arquivo import ArquivoMidia, ErroArquivo
from services.painel_cliente import ErroPainel

log = logging.getLogger(__name__)

Progresso = Optional[Callable[..., None]]


class ErroMidias(Exception):
    """Mensagem segura para a tela."""


def mensagem(exc: BaseException) -> str:
    if isinstance(exc, (ErroMidias, ErroArquivo, ErroPainel)):
        return str(exc)
    return descrever_erro(exc, db.settings)


def _exigir_gestor(usuario: Usuario) -> None:
    if not usuario.gestor:
        raise ErroMidias("Somente gestores podem alterar as mídias.")


def _nada(*_a) -> None:
    pass


def listar() -> list[dict]:
    return midias_repo.listar()


def padroes() -> tuple[int, bool]:
    return midias_repo.padroes()


def tipo_por_extensao(caminho: str) -> str:
    ext = Path(caminho).suffix.lstrip(".").lower()
    if ext in EXT_IMAGEM:
        return "imagem"
    if ext in EXT_VIDEO:
        return "video"
    aceitos = ", ".join(sorted(EXT_IMAGEM | EXT_VIDEO))
    raise ErroArquivo(f"Formato não suportado. Use: {aceitos}.")


def valores_iniciais(arq: ArquivoMidia) -> dict:
    dur, mudo = padroes()
    if arq.tipo == "video" and arq.duracao_video:
        lo, hi = SLIDESHOW.duracao_limite
        dur = max(lo, min(hi, math.ceil(arq.duracao_video)))
    titulo = arq.nome_original.rsplit(".", 1)[0][:120]
    return {"titulo": titulo, "duracao_seg": dur, "mudo": mudo, "ajuste": "conter",
            "ativo": True, "valido_de": None, "valido_ate": None}


def validar(d: dict, tipo: str) -> dict[str, str]:
    erros: dict[str, str] = {}
    titulo = (d.get("titulo") or "").strip()
    if not titulo:
        erros["titulo"] = "Informe o título."
    elif len(titulo) > 120:
        erros["titulo"] = "Título com no máximo 120 caracteres."
    lo, hi = SLIDESHOW.duracao_limite
    dur = d.get("duracao_seg")
    if not isinstance(dur, int) or not lo <= dur <= hi:
        erros["duracao_seg"] = f"Tempo na tela entre {lo} e {hi} s."
    if d.get("ajuste") not in ("conter", "cobrir"):
        erros["ajuste"] = "Ajuste inválido."
    de, ate = d.get("valido_de"), d.get("valido_ate")
    if de and ate and ate < de:
        erros["valido_ate"] = "A data final deve ser igual ou posterior à inicial."
    if tipo not in ("imagem", "video"):
        erros["tipo"] = "Tipo de mídia inválido."
    return erros


def _checar(d: dict, tipo: str) -> dict:
    d = dict(d, titulo=(d.get("titulo") or "").strip())
    erros = validar(d, tipo)
    if erros:
        raise ErroMidias(next(iter(erros.values())))
    if tipo == "imagem":
        d["mudo"] = True
    return d


def _limite(cur) -> None:
    if midias_repo.contar_ativas(cur, travar=True) >= SLIDESHOW.max_midias:
        raise ErroMidias(f"Limite de {SLIDESHOW.max_midias} mídias ativas atingido. "
                         "Desative ou exclua alguma antes.")


def cadastrar_caminho(usuario: Usuario, caminho: str, dados: dict,
                      progresso: Progresso = None) -> dict:
    """Valida, analisa o arquivo, envia e cadastra (use fora da GUI)."""
    avisar = progresso or _nada
    _exigir_gestor(usuario)
    avisar("etapa", "Validando os dados…")
    _checar(dados, tipo_por_extensao(caminho))
    avisar("etapa", "Analisando o arquivo…")
    arq = midias_arquivo.preparar(caminho)
    try:
        avisar("analisado", arq)
        return cadastrar(usuario, arq, dados, progresso)
    finally:
        arq.descartar()


def cadastrar(usuario: Usuario, arq: ArquivoMidia, dados: dict,
              progresso: Progresso = None) -> dict:
    """{'id', 'recebido_por': [maquinas], 'avisos': [str]}."""
    avisar = progresso or _nada
    _exigir_gestor(usuario)
    d = _checar(dados, arq.tipo)
    avisar("etapa", "Verificando limite e duplicidade…")
    with db.cursor() as cur:
        if d["ativo"]:
            _limite(cur)
        if midias_repo.sha_cadastrado(cur, arq.sha256):
            raise ErroMidias("Esta mídia já está cadastrada.")

    avisar("etapa", "Localizando painéis online…")
    token = token_midias.garantir(usuario.id)
    destinos = paineis_service.destinos()
    if not destinos:
        raise ErroMidias("Nenhum painel online com servidor de mídias. Abra um painel "
                         "no modo Slideshow e tente novamente.")
    avisar("destinos", [p.maquina for p in destinos])
    recebido, falhas, t0 = [], [], None
    for p in destinos:
        def por_bloco(enviados: int, total: int, maquina: str = p.maquina) -> None:
            avisar("envio", maquina, enviados, total)
        try:
            novo = paineis_service.enviar(p, token, arq.caminho, arq.nome_cache, por_bloco)
            recebido.append(p.maquina)
            t0 = t0 or time.monotonic()
            avisar("recebido", p.maquina, novo)
        except ErroPainel as exc:
            falhas.append(f"{p.maquina}: {exc}")
            avisar("falha", p.maquina, str(exc))
    if not recebido:
        raise ErroMidias("Nenhum painel recebeu o arquivo:\n" + "\n".join(falhas))

    avisar("etapa", "Registrando no banco…")
    with db.cursor() as cur:
        if d["ativo"]:
            _limite(cur)
        if midias_repo.sha_cadastrado(cur, arq.sha256):
            raise ErroMidias("Esta mídia já foi cadastrada por outro gestor.")
        mid = midias_repo.inserir(cur, arq, d, usuario.id)
        midias_repo.incrementar_versao(cur)
        auditoria.registrar(cur, "midia_cadastrar", usuario.id,
                            detalhe=f"id={mid} {arq.tipo}/{arq.extensao} {arq.sha256[:12]}")
    log.info("Mídia %s cadastrada (%s); recebida por %s.", mid, arq.nome_cache, recebido)

    avisos = list(arq.avisos) + [f"Não recebido por {f}" for f in falhas]
    if time.monotonic() - t0 > SLIDESHOW.carencia_orfao_segundos:
        avisos.append("O envio levou mais de 10 min: algum painel pode ter descartado o "
                      "arquivo. Use Reenviar na aba Status dos painéis.")
    if arq.tipo == "imagem":
        avisar("etapa", "Gerando miniatura…")
        miniaturas.gerar(arq.caminho, arq.sha256)
    return {"id": mid, "recebido_por": recebido, "avisos": avisos}


def editar(usuario: Usuario, mid: int, dados: dict) -> None:
    _exigir_gestor(usuario)
    with db.cursor() as cur:
        atual = midias_repo.obter(cur, mid, travar=True)
        if not atual:
            raise ErroMidias("Mídia não encontrada (pode ter sido excluída).")
        d = _checar(dados, atual["tipo"])
        if d["ativo"] and not atual["ativo"]:
            _limite(cur)
        midias_repo.atualizar(cur, mid, d)
        midias_repo.incrementar_versao(cur)
        auditoria.registrar(cur, "midia_editar", usuario.id, detalhe=f"id={mid}")


def excluir(usuario: Usuario, mid: int) -> None:
    _exigir_gestor(usuario)
    with db.cursor() as cur:
        atual = midias_repo.obter(cur, mid, travar=True)
        if not atual:
            return
        midias_repo.excluir(cur, mid)
        midias_repo.incrementar_versao(cur)
        auditoria.registrar(cur, "midia_excluir", usuario.id,
                            detalhe=f"id={mid} {atual['sha256'][:12]}")
    miniaturas.remover(atual["sha256"])


def mover(usuario: Usuario, mid: int, delta: int) -> None:
    _exigir_gestor(usuario)
    with db.cursor() as cur:
        ids = midias_repo.ids_ordenados(cur)
        if mid not in ids:
            raise ErroMidias("Mídia não encontrada.")
        i = ids.index(mid)
        j = i + delta
        if not 0 <= j < len(ids):
            return
        ids[i], ids[j] = ids[j], ids[i]
        midias_repo.definir_ordem(cur, ids)
        midias_repo.incrementar_versao(cur)
        auditoria.registrar(cur, "midia_editar", usuario.id, detalhe=f"id={mid} ordem")


def obter_opcional(mid: int) -> Optional[dict]:
    with db.cursor() as cur:
        return midias_repo.obter(cur, mid)
