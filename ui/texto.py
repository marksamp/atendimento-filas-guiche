"""
Corte de texto por largura real da fonte (pixels lógicos, sem escala).

cortar() quebra por palavras (palavras longas são partidas por caractere),
limita a N linhas e termina a última com "…". As quebras são explícitas
("\n"), então o Tk não reorganiza o texto se o wraplength for um pouco maior.
"""
import tkinter.font as tkfont
from functools import lru_cache
from typing import Callable

RETICENCIAS = "…"


@lru_cache(maxsize=32)
def _fonte(familia: str, tamanho: int, peso: str) -> tkfont.Font:
    # Tamanho negativo = pixels (mesmo critério do CustomTkinter)
    return tkfont.Font(family=familia, size=-abs(tamanho),
                       weight="bold" if peso == "bold" else "normal")


def _quebrar(texto: str, medir: Callable[[str], int], largura: int) -> list[str]:
    linhas, atual = [], ""
    for p in texto.split(" "):
        teste = f"{atual} {p}" if atual else p
        if medir(teste) <= largura:
            atual = teste
            continue
        if atual:
            linhas.append(atual)
        while len(p) > 1 and medir(p) > largura:
            i = len(p)
            while i > 1 and medir(p[:i]) > largura:
                i -= 1
            linhas.append(p[:i])
            p = p[i:]
        atual = p
    if atual:
        linhas.append(atual)
    return linhas


def cortar(texto: str, fonte: tuple, largura: int, linhas: int) -> str:
    """`fonte` = (família, tamanho, peso) como em theme.font()."""
    texto = " ".join((texto or "").split())
    if not texto or largura <= 0 or linhas <= 0:
        return texto
    medir = _fonte(fonte[0], int(fonte[1]), fonte[2] if len(fonte) > 2 else "normal").measure
    partes = _quebrar(texto, medir, largura)
    if len(partes) <= linhas:
        return "\n".join(partes)
    visiveis = partes[:linhas]
    ultima = visiveis[-1]
    while ultima and medir(ultima + RETICENCIAS) > largura:
        ultima = ultima[:-1]
    visiveis[-1] = ultima.rstrip() + RETICENCIAS
    return "\n".join(visiveis)
