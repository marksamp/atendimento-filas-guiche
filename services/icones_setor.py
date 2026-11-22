"""
Cache dos ícones PNG dos setores (setores.icone_png / icone_hash).

FORMATO (schema v9): PNG RGBA 128x128, glifo branco no canal alfa.
  Só o alfa é guardado; a cor é aplicada na hora (tema claro/escuro).

THREADS:
  preparar(setores)  -> thread de background: baixa apenas os hashes novos,
                        confere o SHA-256, decodifica e descarta os órfãos.
  imagem(hash, ...)  -> thread da GUI: cria/reutiliza o CTkImage colorido.
  Sem ícone, hash inválido ou PNG corrompido -> None (card usa o prefixo).
"""
import hashlib
import io
import logging
import threading
from typing import Optional

import customtkinter as ctk
from PIL import Image

from config import SETORES
from services import fila_service

log = logging.getLogger(__name__)

_MAX_BYTES = 2 * 1024 * 1024        # proteção contra BLOBs anômalos
_lock = threading.Lock()
_alfas: dict[str, Image.Image] = {}                # hash -> canal alfa (modo "L")
_imagens: dict[tuple, ctk.CTkImage] = {}           # (hash, claro, escuro, px) -> imagem
_invalidos: set[str] = set()                       # hashes que falharam (não rebaixar)


def _decodificar(png: bytes, esperado: str) -> Optional[Image.Image]:
    if len(png) > _MAX_BYTES:
        log.warning("Ícone %s ignorado: %d bytes.", esperado[:12], len(png))
        return None
    if hashlib.sha256(png).hexdigest() != esperado:
        log.warning("Ícone %s ignorado: hash não confere.", esperado[:12])
        return None
    try:
        with Image.open(io.BytesIO(png)) as img:
            img.load()
            lado = SETORES.icone_origem_px
            if img.size != (lado, lado):
                img = img.resize((lado, lado), Image.LANCZOS)
            return img.convert("RGBA").getchannel("A")
    except Exception as exc:  # noqa: BLE001
        log.warning("Ícone %s corrompido: %s", esperado[:12], exc)
        return None


def preparar(setores: list[dict]) -> None:
    """Background: garante no cache os alfas dos hashes atuais."""
    atuais = {s["icone_hash"] for s in setores if s.get("icone_hash")}
    with _lock:
        faltando = [s["id"] for s in setores
                    if s.get("icone_hash")
                    and s["icone_hash"] not in _alfas
                    and s["icone_hash"] not in _invalidos]
    novos: dict[str, Image.Image] = {}
    falhas: set[str] = set()
    for h, png in fila_service.buscar_icones(faltando).values():
        alfa = _decodificar(png, h)
        if alfa is None:
            falhas.add(h)
        else:
            novos[h] = alfa
    with _lock:
        _alfas.update(novos)
        _invalidos.update(falhas)
        for h in set(_alfas) - atuais:
            del _alfas[h]
        _invalidos.intersection_update(atuais)
        for chave in [k for k in _imagens if k[0] not in atuais]:
            del _imagens[chave]


def _colorir(alfa: Image.Image, cor: str) -> Image.Image:
    cor = cor.lstrip("#")
    rgb = tuple(int(cor[i:i + 2], 16) for i in (0, 2, 4))
    img = Image.new("RGBA", alfa.size, rgb)
    img.putalpha(alfa)
    return img


def imagem(icone_hash: Optional[str], cor_claro: str, cor_escuro: str,
           px: int) -> Optional[ctk.CTkImage]:
    """GUI: CTkImage colorido para os dois temas (None = usar fallback)."""
    if not icone_hash:
        return None
    chave = (icone_hash, cor_claro, cor_escuro, px)
    with _lock:
        if chave in _imagens:
            return _imagens[chave]
        alfa = _alfas.get(icone_hash)
    if alfa is None:
        return None
    img = ctk.CTkImage(light_image=_colorir(alfa, cor_claro),
                       dark_image=_colorir(alfa, cor_escuro), size=(px, px))
    with _lock:
        _imagens[chave] = img
    return img
