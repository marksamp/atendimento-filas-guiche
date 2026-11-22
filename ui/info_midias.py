"""
Especificações das mídias (textos montados a partir do config_slideshow).
- requisitos(tipo, ext): resumo de uma linha para o formulário.
- verificar(...): compara o arquivo com os limites -> [(texto, estado)]
  estado: True = dentro, False = fora, None = não identificado, AVISO = alerta
  que não bloqueia (ex.: GIF com quadros demais).
- CartaoEspecificacoes: quadro recolhível (tema escuro/neon).
"""
from functools import lru_cache
from typing import Optional, Union

import customtkinter as ctk

from config_slideshow import SLIDESHOW as S
from services import formato
from ui import theme as T

_MB = 1024 * 1024
AVISO = "aviso"
Estado = Union[bool, None, str]
AJUSTE_DICA = {
    "conter": "Mostra a mídia inteira, sem cortes (pode sobrar faixa preta).",
    "cobrir": "Preenche a tela toda (as bordas podem ser cortadas).",
}


def _res(r: tuple) -> str:
    return f"{r[0]}×{r[1]}"


def _ext(exts) -> str:
    return ", ".join(e.lstrip(".").upper() for e in exts)


def _tempo(seg: int) -> str:
    m, s = divmod(seg, 60)
    return f"{seg} s ({m} min{f' {s} s' if s else ''})" if m else f"{seg} s"


def _sem_gif() -> tuple:
    return tuple(e for e in S.imagem_ext if e.lower() != ".gif")


@lru_cache(maxsize=1)
def mediainfo_ok() -> bool:
    try:
        from pymediainfo import MediaInfo
        return bool(MediaInfo.can_parse())
    except Exception:  # noqa: BLE001
        return False


def linhas_imagem() -> list[str]:
    return [f"Formatos: {_ext(_sem_gif())} • até {S.imagem_max_mb} MB",
            f"Resolução ideal: {_res(S.imagem_max_res)} (16:9)",
            "Maiores que isso são reduzidas automaticamente",
            f"GIF (animado ou não): até {S.gif_max_mb} MB",
            f"GIF animado repete durante o tempo na tela "
            f"(usa até {S.gif_max_quadros} quadros, máx. {1000 // S.gif_quadro_min_ms} fps)"]


def linhas_video() -> list[str]:
    return [f"Formatos: {_ext(S.video_ext)} (recomendado MP4 H.264)",
            f"Tamanho máximo: {S.video_max_mb} MB",
            f"Duração máxima: {_tempo(S.video_max_seg)}",
            f"Resolução máxima: {_res(S.video_max_res)}",
            "Sem som por padrão (pode ser ativado)"]


def linhas_gerais() -> list[str]:
    a, b = S.duracao_limite
    return [f"Tempo na tela: de {a} a {b} s",
            f"Até {S.max_midias} mídias ativas (inclui agendadas/vencidas)",
            f"Alerta acima de {S.alerta_total_mb / 1024:g} GB no total",
            "Conter: inteira, sem cortes • Cobrir: preenche a tela",
            "Validade em branco = sem limite de data"]


def requisitos(tipo: str, ext: str = "") -> str:
    if tipo == "video":
        return (f"Vídeo: {_ext(S.video_ext)} • até {S.video_max_mb} MB • "
                f"até {_tempo(S.video_max_seg)} • até {_res(S.video_max_res)}")
    if ext.lstrip(".").lower() == "gif":
        return (f"GIF: até {S.gif_max_mb} MB • animado repete durante o tempo na tela • "
                f"até {S.gif_max_quadros} quadros (excedentes ignorados)")
    return (f"Imagem: {_ext(_sem_gif())} • até {S.imagem_max_mb} MB • "
            f"ideal {_res(S.imagem_max_res)} (maiores são reduzidas)")


def verificar(tipo: str, tamanho: Optional[int], largura: Optional[int],
              altura: Optional[int], duracao: Optional[float] = None,
              reduzida: bool = False, ext: str = "",
              quadros: Optional[int] = None) -> list[tuple[str, Estado]]:
    video = tipo == "video"
    gif = ext.lstrip(".").lower() == "gif"
    max_mb = S.limite_mb(ext) if ext else (S.video_max_mb if video else S.imagem_max_mb)
    max_res = S.video_max_res if video else S.imagem_max_res
    itens: list[tuple[str, Estado]] = []

    if tamanho:
        itens.append((f"Tamanho: {formato.mb(tamanho)} (máx. {max_mb} MB)",
                      tamanho <= max_mb * _MB))
    else:
        itens.append(("Tamanho: não identificado", None))

    if largura and altura:
        ok = largura <= max_res[0] and altura <= max_res[1]
        txt = f"Resolução: {largura}×{altura} (ideal até {_res(max_res)})"
        if reduzida:
            txt += " • reduzida automaticamente"
        if gif and not ok:
            itens.append((txt + " • o painel reduz ao exibir", AVISO))
        else:
            itens.append((txt, ok))
    else:
        itens.append(("Resolução: não identificada", None))

    if gif:
        if not quadros:
            itens.append(("Quadros: não identificados", None))
        elif quadros > S.gif_max_quadros:
            itens.append((f"Quadros: {quadros} (o painel usa os {S.gif_max_quadros} primeiros)",
                          AVISO))
        else:
            itens.append((f"Quadros: {quadros}" + (" (animado)" if quadros > 1 else " (estático)"),
                          True))

    if video:
        if duracao:
            itens.append((f"Duração: {duracao:.0f} s (máx. {S.video_max_seg} s)",
                          duracao <= S.video_max_seg))
        else:
            itens.append(("Duração: não identificada", None))
    return itens


class CartaoEspecificacoes(ctk.CTkFrame):
    def __init__(self, master, aberto: bool = False):
        super().__init__(master, fg_color=T.BG_ITEM, corner_radius=12)
        self.grid_columnconfigure(0, weight=1)
        self._aberto = aberto
        self._btn = ctk.CTkButton(self, text="", anchor="w", height=36, corner_radius=10,
                                  font=T.font(14, "bold"), fg_color="transparent",
                                  hover_color=T.BG_CARD_HOV, text_color=T.NEON,
                                  command=self.alternar)
        self._btn.grid(row=0, column=0, sticky="ew", padx=6, pady=4)

        self._corpo = ctk.CTkFrame(self, fg_color="transparent")
        for col, (titulo, linhas) in enumerate((("Imagens e GIFs", linhas_imagem()),
                                                ("Vídeos", linhas_video()),
                                                ("Regras gerais", linhas_gerais()))):
            self._corpo.grid_columnconfigure(col, weight=1, uniform="esp")
            bloco = ctk.CTkFrame(self._corpo, fg_color=T.BG_APP, corner_radius=10)
            bloco.grid(row=0, column=col, sticky="nsew", padx=6, pady=(0, 6))
            ctk.CTkLabel(bloco, text=titulo, font=T.font(13, "bold"),
                         text_color=T.NEON).pack(anchor="w", padx=12, pady=(10, 4))
            for ln in linhas:
                ctk.CTkLabel(bloco, text=f"• {ln}", font=T.font(12), text_color=T.TXT_MUTED,
                             wraplength=300, justify="left").pack(anchor="w", padx=12)
            ctk.CTkFrame(bloco, height=8, fg_color="transparent").pack()
        if not mediainfo_ok():
            ctk.CTkLabel(self._corpo, text="⚠ pymediainfo indisponível: resolução e duração "
                                           "dos vídeos não serão verificadas.",
                         font=T.font(12, "bold"), text_color=T.WARN).grid(
                row=1, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 8))
        self._aplicar()

    def alternar(self) -> None:
        self._aberto = not self._aberto
        self._aplicar()

    def _aplicar(self) -> None:
        seta = "▴" if self._aberto else "▾"
        self._btn.configure(text=f"ⓘ  Especificações das mídias  {seta}")
        if self._aberto:
            self._corpo.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 6))
        else:
            self._corpo.grid_remove()
