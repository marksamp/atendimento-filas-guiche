"""
Miniaturas das imagens: pasta_config()/miniaturas/<sha256>.png.

- Geradas no cadastro a partir do arquivo local.
- Ausentes: a imagem é baixada de um painel online (só a miniatura fica).
- GIF: usa só o primeiro quadro (transparência vira preto).
- Vídeos: sem miniatura (a tela usa um ícone fixo).
- Download limitado por SLIDESHOW.limite_mb(ext) (mesma regra do Painel).
- Falhas não são repetidas por _ESPERA_SEG (evita downloads em cada refresh).
"""
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps

from config_slideshow import EXT_IMAGEM, SLIDESHOW
from services import painel_cliente, paineis_service, token_midias
from services.config_store import pasta_config

log = logging.getLogger(__name__)

_MB = 1024 * 1024
_ESPERA_SEG = 120
_falhas: dict[str, float] = {}
_lock = threading.Lock()


def _pasta() -> Path:
    p = pasta_config() / "miniaturas"
    p.mkdir(exist_ok=True)
    return p


def caminho(sha: str) -> Path:
    return _pasta() / f"{sha.lower()}.png"


def _rgb(img: Image.Image) -> Image.Image:
    """Primeiro quadro em RGB; transparência sobre fundo preto."""
    img.seek(0)
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
        rgba = img.convert("RGBA")
        fundo = Image.new("RGB", rgba.size, (0, 0, 0))
        fundo.paste(rgba, mask=rgba.getchannel("A"))
        return fundo
    return img.convert("RGB")


def gerar(origem: Path, sha: str) -> Optional[Path]:
    destino = caminho(sha)
    try:
        with Image.open(origem) as img:
            mini = ImageOps.pad(_rgb(img), SLIDESHOW.miniatura, Image.LANCZOS, color=(0, 0, 0))
        tmp = destino.with_suffix(f".{os.getpid()}.tmp")
        mini.save(tmp, "PNG")
        os.replace(tmp, destino)
        return destino
    except (OSError, ValueError, EOFError) as exc:
        log.warning("Miniatura não gerada para %s: %s", sha[:12], exc)
        return None


def obter(sha: str, ext: str) -> Optional[Path]:
    """Caminho da miniatura (pode baixar de um painel; use fora da GUI)."""
    p = caminho(sha)
    if p.is_file():
        return p
    ext = ext.lower()
    if ext not in EXT_IMAGEM:
        return None
    with _lock:
        if time.monotonic() - _falhas.get(sha, -_ESPERA_SEG) < _ESPERA_SEG:
            return None
    token = token_midias.ler()
    for painel in (paineis_service.destinos() if token else []):
        fd, tmp = tempfile.mkstemp(prefix="mini_", suffix=f".{ext}")
        os.close(fd)
        tmp = Path(tmp)
        try:
            painel_cliente.baixar(painel.ip, painel.porta, token, f"{sha}.{ext}", tmp,
                                  SLIDESHOW.limite_mb(ext) * _MB)
            if gerar(tmp, sha):
                return p
        except painel_cliente.ErroPainel as exc:
            log.debug("Miniatura %s indisponível em %s: %s", sha[:12], painel.maquina, exc)
        finally:
            tmp.unlink(missing_ok=True)
    with _lock:
        _falhas[sha] = time.monotonic()
    return None


def remover(sha: str) -> None:
    caminho(sha).unlink(missing_ok=True)
