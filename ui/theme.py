"""Identidade visual: dark grafite + neon #00FFCC."""
import customtkinter as ctk

BG_APP = "#0B0D10"
BG_CARD = "#16191D"
BG_CARD_HOV = "#20242A"
BG_ITEM = "#1C2025"
BORDER = "#2A2F36"
NEON = "#00FFCC"
NEON_DARK = "#00BFA0"
TXT = "#E6EAEE"
TXT_MUTED = "#8B939C"
DANGER = "#FF4D6D"
WARN = "#FFB84D"

# Estado desabilitado (botões sem destaque)
BG_OFF = "#111418"
BORDER_OFF = "#22262C"
TXT_OFF = "#565E67"

RADIUS = 16
FAMILIA = "Segoe UI"

_fontes: dict[tuple, ctk.CTkFont] = {}


def font(size: int, weight: str = "normal") -> ctk.CTkFont:
    chave = (size, weight)
    if chave not in _fontes:
        _fontes[chave] = ctk.CTkFont(family=FAMILIA, size=size, weight=weight)
    return _fontes[chave]


def cor_segura(cor: str | None, padrao: str = NEON) -> str:
    return cor if isinstance(cor, str) and len(cor) == 7 and cor.startswith("#") else padrao
