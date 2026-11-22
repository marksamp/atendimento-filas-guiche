"""
Gera o PNG do ícone do setor gravado em setores.icone_png (contrato com o Totem).

- RGBA 128x128, fundo totalmente transparente; glifo branco puro (#FFFFFF).
  Forma e antialiasing ficam só no canal alfa (o Totem recolore).
- Glifo centralizado em 110 px (margem ~8%), proporção preservada.
- optimize=True, sem metadados. Hash = SHA-256 (hex minúsculo) dos bytes.
Fontes: 'tabler:<nome>', nome legado (mapeado para Tabler) ou arquivo do gestor.
"""
import hashlib
import io
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

log = logging.getLogger(__name__)

LADO, AREA = 128, 110
TAM_MAX = 64 * 1024
PREFIXO_TABLER, PREFIXO_ARQUIVO = "tabler:", "arquivo:"
FORMATOS_ARQUIVO = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".ico", ".gif")
ARQUIVO_MAX = 5 * 1024 * 1024

_BASE = Path(__file__).resolve().parent.parent / "assets" / "tabler"
_RENDER = 512          # desenha grande e reduz (antialiasing limpo)
_RUIDO = 12            # alfa abaixo disto vira 0 (bordas/fundos quase transparentes)
_LEGADO = {
    "user": ("user",), "file-text": ("file-text",), "calendar": ("calendar",),
    "info": ("info-circle",), "credit-card": ("credit-card",),
    "shield-check": ("shield-check",), "syringe": ("vaccine", "syringe"),
    "id-card": ("id", "id-badge-2"),
}


@lru_cache(maxsize=1)
def _mapa() -> dict[str, str]:
    try:
        return json.loads((_BASE / "tabler-icons.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("tabler-icons.json ausente ou inválido em %s.", _BASE)
        return {}


@lru_cache(maxsize=1)
def _fonte() -> Optional[ImageFont.FreeTypeFont]:
    caminho = _BASE / "tabler-icons.ttf"
    if not caminho.exists():
        caminho = next(iter(sorted(_BASE.glob("*.ttf"))), None)
    if not caminho:
        log.warning("Fonte Tabler (.ttf) não encontrada em %s.", _BASE)
        return None
    try:
        return ImageFont.truetype(str(caminho), _RENDER)
    except OSError:
        log.exception("Falha ao abrir a fonte Tabler.")
        return None


def hash_png(png: bytes) -> str:
    return hashlib.sha256(bytes(png)).hexdigest()


def icone_arquivo(png: bytes) -> str:
    """Valor da coluna icone para imagem escolhida pelo gestor."""
    return f"{PREFIXO_ARQUIVO}{hash_png(png)[:16]}"


def _limpar(mascara: Image.Image) -> Image.Image:
    return mascara.point(lambda v: 0 if v < _RUIDO else v)


def _montar(mascara: Image.Image) -> Optional[bytes]:
    caixa = mascara.getbbox()
    if not caixa:
        return None
    glifo = ImageOps.contain(mascara.crop(caixa), (AREA, AREA), Image.Resampling.LANCZOS)
    alfa = Image.new("L", (LADO, LADO), 0)
    alfa.paste(glifo, ((LADO - glifo.width) // 2, (LADO - glifo.height) // 2))
    branco = Image.new("L", (LADO, LADO), 255)
    buf = io.BytesIO()
    Image.merge("RGBA", (branco, branco, branco, alfa)).save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _glifo(nome: str) -> Optional[Image.Image]:
    codigo, fonte = _mapa().get(nome), _fonte()
    if not codigo or fonte is None:
        return None
    try:
        ch = chr(int(codigo, 16))
    except ValueError:
        return None
    img = Image.new("L", (_RENDER * 2, _RENDER * 2), 0)
    ImageDraw.Draw(img).text((_RENDER // 2, _RENDER // 2), ch, font=fonte, fill=255)
    return _limpar(img)


def gerar_png(icone: Optional[str]) -> Optional[bytes]:
    """Função pura. None = vazio, inválido, inexistente ou 'arquivo:' (não regenerável)."""
    nome = (icone or "").strip().lower()
    if not nome or nome.startswith(PREFIXO_ARQUIVO):
        return None
    if nome.startswith(PREFIXO_TABLER):
        candidatos = (nome[len(PREFIXO_TABLER):],)
    else:
        candidatos = _LEGADO.get(nome, ())
    for candidato in candidatos:
        mascara = _glifo(candidato)
        if mascara is not None:
            return _montar(mascara)
    return None


def _mascara_imagem(img: Image.Image) -> Image.Image:
    alfa = img.getchannel("A")
    if alfa.getextrema()[0] < 250:                  # tem transparência: silhueta pelo alfa
        return _limpar(alfa)
    cinza = ImageOps.grayscale(img)                 # opaca: desenho escuro em fundo claro
    w, h = cinza.size
    cantos = [cinza.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    return _limpar(ImageOps.invert(cinza) if sum(cantos) / 4 >= 128 else cinza)


def gerar_png_arquivo(caminho: str | Path) -> bytes:
    """Converte a imagem do gestor para o contrato. ValueError com mensagem amigável."""
    p = Path(caminho)
    if p.suffix.lower() not in FORMATOS_ARQUIVO:
        raise ValueError("Formato não suportado. Use PNG, JPG, WEBP, BMP, ICO ou GIF.")
    if p.stat().st_size > ARQUIVO_MAX:
        raise ValueError("Imagem acima de 5 MB.")
    try:
        with Image.open(p) as im:
            img = ImageOps.exif_transpose(im).convert("RGBA")
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError("Não foi possível abrir a imagem.") from exc
    png = _montar(_mascara_imagem(img))
    if not png:
        raise ValueError("A imagem não tem desenho visível.")
    if len(png) > TAM_MAX:
        raise ValueError(f"O ícone ficou com {len(png) // 1024} KB "
                         f"(máximo {TAM_MAX // 1024} KB). Use uma imagem mais simples.")
    return png
