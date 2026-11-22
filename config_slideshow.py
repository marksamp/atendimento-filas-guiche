"""
Limites do slideshow no Guichê. DEVEM ser iguais ao config_slideshow.py do Painel
(o painel recusa o que passar dos limites dele).
EXT_IMAGEM / EXT_VIDEO: extensões SEM ponto (cache dos painéis: <sha256>.<ext>).

GIF: cadastrado como tipo "imagem" (animado repete durante duracao_seg).
  Não é reduzido no Guichê (perderia a animação): o Painel reduz ao exibir.
  Acima de gif_max_quadros: só aviso (o Painel usa os primeiros quadros).
"""
from dataclasses import dataclass

_MB = 1024 * 1024


@dataclass(frozen=True)
class SlideshowConfig:
    porta: int = 8765
    cabecalho_token: str = "X-Token"
    max_midias: int = 50                        # ativas (inclui agendadas/vencidas)
    alerta_total_mb: int = 2048
    duracao_limite: tuple = (1, 600)
    imagem_ext: tuple = (".jpg", ".jpeg", ".png", ".webp", ".gif")
    imagem_max_mb: int = 5
    imagem_max_res: tuple = (1920, 1080)        # acima disso a imagem é reduzida (exceto GIF)
    jpeg_qualidade: int = 88
    # GIF (animado ou não) — iguais ao Painel
    gif_max_mb: int = 100
    gif_max_quadros: int = 300                  # o Painel ignora quadros além disto
    gif_memoria_max_mb: int = 150               # o Painel reduz a resolução para caber
    gif_quadro_min_ms: int = 40                 # máx. 25 fps
    video_ext: tuple = (".mp4", ".mkv", ".mov", ".avi", ".webm")
    video_max_mb: int = 100
    video_max_seg: int = 300
    video_max_res: tuple = (1920, 1080)
    bloco_bytes: int = _MB
    carencia_orfao_segundos: int = 600          # INSERT deve ocorrer antes disso
    token_cache_segundos: float = 30.0          # cache do token nos painéis
    timeout_status_s: float = 4.0
    timeout_envio_s: float = 120.0
    miniatura: tuple = (160, 90)

    @property
    def max_bytes(self) -> int:
        return max(self.imagem_max_mb, self.gif_max_mb, self.video_max_mb) * _MB

    def limite_mb(self, ext: str) -> int:
        """Tamanho máximo (MB) pela extensão (com ou sem ponto)."""
        e = "." + ext.lstrip(".").lower()
        if e == ".gif":
            return self.gif_max_mb
        return self.video_max_mb if e in self.video_ext else self.imagem_max_mb


SLIDESHOW = SlideshowConfig()
EXT_IMAGEM = frozenset(e.lstrip(".").lower() for e in SLIDESHOW.imagem_ext)
EXT_VIDEO = frozenset(e.lstrip(".").lower() for e in SLIDESHOW.video_ext)
EXT_REDUZIVEL = EXT_IMAGEM - {"gif"}            # imagens que o Guichê pode reduzir
