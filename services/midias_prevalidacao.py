"""
Checagens instantâneas antes da análise (sem abrir/decodificar o arquivo):
existência, formato e tamanho do original. Erro aqui aparece direto no
formulário, sem trocar de tela (evita o flicker formulário -> loading -> formulário).
Imagens reduzíveis (JPG/PNG/WEBP) só têm o tamanho checado após a redução.
"""
from pathlib import Path

from config_slideshow import EXT_IMAGEM, EXT_REDUZIVEL, EXT_VIDEO, SLIDESHOW
from services.midias_arquivo import ErroArquivo

_MB = 1024 * 1024


def pre_validar(caminho: str) -> None:
    p = Path(caminho)
    if not p.is_file():
        raise ErroArquivo("Arquivo não encontrado.")
    ext = p.suffix.lstrip(".").lower()
    if ext not in EXT_IMAGEM | EXT_VIDEO:
        aceitos = ", ".join(sorted(EXT_IMAGEM | EXT_VIDEO))
        raise ErroArquivo(f"Formato não suportado. Use: {aceitos}.")
    try:
        tamanho = p.stat().st_size
    except OSError as exc:
        raise ErroArquivo("Não foi possível ler o arquivo.") from exc
    if tamanho <= 0:
        raise ErroArquivo("Arquivo vazio.")
    if ext in EXT_REDUZIVEL:
        return
    limite = SLIDESHOW.limite_mb(ext)
    if tamanho > limite * _MB:
        rotulo = "GIF" if ext == "gif" else ("Vídeo" if ext in EXT_VIDEO else "Imagem")
        raise ErroArquivo(f"{rotulo} maior que {limite} MB.")
