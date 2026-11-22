"""
Preparação do arquivo de mídia antes do envio aos painéis.

- Imagem acima de 1920x1080: reduzida (EXIF aplicado). PNG/JPG -> JPG
  (transparência vira preto); WEBP continua WEBP. Abaixo disso: arquivo original.
- GIF: conteúdo validado pelo Pillow (format == "GIF"); enviado SEM alteração
  (preserva a animação). Mais de gif_max_quadros quadros -> aviso (não bloqueia).
- Vídeo: tamanho, duração e resolução (pymediainfo; ausente -> só o tamanho).
- Tamanho máximo sempre por SLIDESHOW.limite_mb(ext) (mesma regra do Painel).
- SHA-256 calculado do arquivo FINAL (é o nome no cache dos painéis).
"""
import hashlib
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps, UnidentifiedImageError

from config_slideshow import EXT_IMAGEM, EXT_REDUZIVEL, EXT_VIDEO, SLIDESHOW

log = logging.getLogger(__name__)
_MB = 1024 * 1024


class ErroArquivo(Exception):
    """Mensagem segura para a tela."""


@dataclass
class ArquivoMidia:
    caminho: Path
    nome_original: str
    tipo: str
    extensao: str
    sha256: str
    tamanho: int
    largura: Optional[int] = None
    altura: Optional[int] = None
    duracao_video: Optional[float] = None
    temporario: bool = False
    quadros: Optional[int] = None               # só GIF
    avisos: list = field(default_factory=list)  # não bloqueiam o cadastro

    @property
    def nome_cache(self) -> str:
        return f"{self.sha256}.{self.extensao}"

    def descartar(self) -> None:
        if self.temporario:
            self.caminho.unlink(missing_ok=True)


def sha256_arquivo(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for bloco in iter(lambda: f.read(SLIDESHOW.bloco_bytes), b""):
            h.update(bloco)
    return h.hexdigest()


def _temporario(ext: str) -> Path:
    fd, nome = tempfile.mkstemp(prefix="midia_", suffix=f".{ext}")
    os.close(fd)
    return Path(nome)


def _rotulo(tipo: str, ext: str) -> str:
    return "GIF" if ext == "gif" else tipo.capitalize()


def _reduzir(img: Image.Image, ext: str) -> tuple[Path, str, tuple[int, int]]:
    img = ImageOps.exif_transpose(img)
    img.thumbnail(SLIDESHOW.imagem_max_res, Image.LANCZOS)
    if ext == "webp":
        destino_ext, formato = "webp", "WEBP"
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
    else:
        destino_ext, formato = "jpg", "JPEG"
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            fundo = Image.new("RGB", rgba.size, (0, 0, 0))
            fundo.paste(rgba, mask=rgba.getchannel("A"))
            img = fundo
        else:
            img = img.convert("RGB")
    destino = _temporario(destino_ext)
    try:
        img.save(destino, formato, quality=SLIDESHOW.jpeg_qualidade, optimize=True)
    except Exception:
        destino.unlink(missing_ok=True)
        raise
    return destino, destino_ext, img.size


def _gif(img: Image.Image) -> tuple[int, int, int]:
    """(largura, altura, quadros). Só lê; o arquivo segue intacto."""
    if img.format != "GIF":
        raise ErroArquivo("O arquivo não é um GIF válido (conteúdo não confere com a extensão).")
    largura, altura = img.size
    quadros = int(getattr(img, "n_frames", 1) or 1)
    img.seek(0)
    img.load()
    return largura, altura, quadros


def _imagem(p: Path, ext: str) -> tuple[Path, str, int, int, bool, Optional[int]]:
    try:
        with Image.open(p) as img:
            if ext == "gif":
                largura, altura, quadros = _gif(img)
                return p, ext, largura, altura, False, quadros
            img.load()
            largura, altura = img.size
            lmax, amax = SLIDESHOW.imagem_max_res
            if largura > lmax or altura > amax:
                final, ext_final, (largura, altura) = _reduzir(img, ext)
                return final, ext_final, largura, altura, True, None
    except (UnidentifiedImageError, OSError, EOFError, Image.DecompressionBombError) as exc:
        raise ErroArquivo("Imagem inválida ou corrompida.") from exc
    return p, ext, largura, altura, False, None


def _numero(valor) -> Optional[float]:
    try:
        return float(valor) if valor not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _video(p: Path) -> tuple[Optional[int], Optional[int], Optional[float]]:
    try:
        from pymediainfo import MediaInfo
    except ImportError:
        log.warning("pymediainfo ausente: duração e resolução do vídeo não validadas.")
        return None, None, None
    try:
        info = MediaInfo.parse(str(p))
    except Exception as exc:  # noqa: BLE001
        log.warning("MediaInfo indisponível (%s): vídeo não analisado.", exc)
        return None, None, None
    video = next((t for t in info.tracks if t.track_type == "Video"), None)
    if video is None:
        raise ErroArquivo("O arquivo não contém trilha de vídeo.")
    geral = next((t for t in info.tracks if t.track_type == "General"), None)
    w, h = _numero(video.width), _numero(video.height)
    dur_ms = _numero(video.duration) or _numero(getattr(geral, "duration", None))
    w, h = (int(w) if w else None), (int(h) if h else None)
    dur = round(dur_ms / 1000, 2) if dur_ms else None
    lmax, amax = SLIDESHOW.video_max_res
    if w and h and (max(w, h) > lmax or min(w, h) > amax):
        raise ErroArquivo(f"Resolução {w}x{h} acima do limite de {lmax}x{amax}.")
    if dur and dur > SLIDESHOW.video_max_seg:
        raise ErroArquivo(f"Vídeo com {dur:.0f} s; o limite é {SLIDESHOW.video_max_seg} s.")
    return w, h, dur


def _checar_original(p: Path, tipo: str, ext: str) -> None:
    """Arquivos enviados sem alteração: recusa cedo (antes de decodificar)."""
    if ext in EXT_REDUZIVEL:
        return
    limite = SLIDESHOW.limite_mb(ext)
    if p.stat().st_size > limite * _MB:
        raise ErroArquivo(f"{_rotulo(tipo, ext)} maior que {limite} MB.")


def _avisos(ext: str, quadros: Optional[int]) -> list[str]:
    if ext == "gif" and quadros and quadros > SLIDESHOW.gif_max_quadros:
        return [f"GIF com {quadros} quadros: o painel exibe só os "
                f"{SLIDESHOW.gif_max_quadros} primeiros."]
    return []


def preparar(caminho: str) -> ArquivoMidia:
    """Valida e prepara o arquivo (pode levar alguns segundos: use fora da GUI)."""
    p = Path(caminho)
    if not p.is_file():
        raise ErroArquivo("Arquivo não encontrado.")
    ext = p.suffix.lstrip(".").lower()
    dur = quadros = None
    if ext in EXT_IMAGEM:
        tipo = "imagem"
        _checar_original(p, tipo, ext)
        final, ext_final, w, h, tmp, quadros = _imagem(p, ext)
    elif ext in EXT_VIDEO:
        tipo = "video"
        _checar_original(p, tipo, ext)
        final, ext_final, tmp = p, ext, False
        w, h, dur = _video(p)
    else:
        aceitos = ", ".join(sorted(EXT_IMAGEM | EXT_VIDEO))
        raise ErroArquivo(f"Formato não suportado. Use: {aceitos}.")
    try:
        tamanho = final.stat().st_size
        if tamanho <= 0:
            raise ErroArquivo("Arquivo vazio.")
        limite = SLIDESHOW.limite_mb(ext_final)
        if tamanho > limite * _MB:
            raise ErroArquivo(f"{_rotulo(tipo, ext_final)} maior que {limite} MB.")
        sha = sha256_arquivo(final)
    except Exception:
        if tmp:
            final.unlink(missing_ok=True)
        raise
    return ArquivoMidia(final, p.name, tipo, ext_final, sha, tamanho, w, h, dur, tmp,
                        quadros, _avisos(ext_final, quadros))
