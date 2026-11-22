"""
Menu de gestão (somente gestor): barra fixa no topo, no padrão dos outros apps.

- Ocupa a linha 0 da janela; as telas ficam abaixo (nada é encoberto).
- marcar(): destaca em neon o item da tela atual.
"""
from typing import Callable, Optional

import customtkinter as ctk

from ui import theme as T
from ui import widgets as W
from ui.icones import icone

ALTURA = 52


class MenuGestao(ctk.CTkFrame):
    def __init__(self, master, itens: list[tuple[str, str, str, Callable[[], None]]]):
        """itens: (chave, texto, icone, comando)."""
        super().__init__(master, fg_color=T.BG_CARD, corner_radius=0, height=ALTURA)
        self._marcado: Optional[str] = None
        self._botoes: dict[str, tuple[ctk.CTkButton, str]] = {}

        self.grid_propagate(False)
        self.grid_rowconfigure(0, weight=1)
        W.rotulo(self, "MENU GESTÃO", 12, "bold", T.NEON).grid(row=0, column=0, padx=(20, 14))

        for col, (chave, texto, ico, cmd) in enumerate(itens, 1):
            b = ctk.CTkButton(self, text=texto, command=cmd, height=36, corner_radius=10,
                              font=T.font(14), fg_color="transparent",
                              hover_color=T.BG_CARD_HOV, text_color=T.TXT,
                              image=icone(ico, 18, T.TXT), compound="left")
            b.grid(row=0, column=col, padx=4)
            self._botoes[chave] = (b, ico)

        ctk.CTkFrame(self, height=2, corner_radius=0, fg_color=T.BORDER).place(
            relx=0, rely=1, relwidth=1, anchor="sw")

    def marcar(self, chave: Optional[str]) -> None:
        if chave == self._marcado:
            return
        self._marcado = chave
        for k, (b, ico) in self._botoes.items():
            cor = T.NEON if k == chave else T.TXT
            b.configure(text_color=cor, image=icone(ico, 18, cor))
