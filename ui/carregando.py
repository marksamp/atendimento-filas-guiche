"""
Camada de loading sobre um widget (place in_=alvo): spinner neon + textos.
Cobre os campos sem alterar o layout (nada é escondido/reempacotado -> sem flicker).
Tempo mínimo visível (MIN_MS): restante_ms() diz quanto falta para poder sair.
"""
import time
import tkinter as tk
from typing import Optional

import customtkinter as ctk

from ui import theme as T
from ui import widgets as W

MIN_MS = 300
_TICK_MS = 16
_PASSO = 10
_TAM = 56


class Carregando(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, fg_color=T.BG_CARD, corner_radius=0)
        caixa = ctk.CTkFrame(self, fg_color="transparent")
        caixa.place(relx=0.5, rely=0.5, anchor="center")
        self._cv = tk.Canvas(caixa, width=_TAM, height=_TAM, bg=T.BG_CARD,
                             highlightthickness=0, bd=0)
        self._cv.pack(pady=(0, 12))
        m = 6
        self._cv.create_oval(m, m, _TAM - m, _TAM - m, outline=T.BG_ITEM, width=5)
        self._arco = self._cv.create_arc(m, m, _TAM - m, _TAM - m, start=90, extent=100,
                                         style="arc", outline=T.NEON, width=5)
        self._lbl = W.rotulo(caixa, "", 15, "bold", T.TXT)
        self._lbl.pack()
        self._det = W.rotulo(caixa, "", 12, cor=T.TXT_MUTED, wraplength=420, justify="center")
        self._det.pack(pady=(4, 0))
        self._ang = 90
        self._job: Optional[str] = None
        self._t0 = 0.0
        self.visivel = False

    def mostrar(self, sobre, texto: str, detalhe: str = "") -> None:
        self.texto(texto, detalhe)
        if not self.visivel:
            self.visivel = True
            self._t0 = time.monotonic()
            self.place(in_=sobre, x=0, y=0, relwidth=1, relheight=1)
            self.lift()
            self._girar()

    def texto(self, texto: str, detalhe: Optional[str] = None) -> None:
        W.configurar(self._lbl, text=texto)
        if detalhe is not None:
            W.configurar(self._det, text=detalhe)

    def restante_ms(self) -> int:
        if not self.visivel:
            return 0
        return max(0, int(MIN_MS - (time.monotonic() - self._t0) * 1000))

    def esconder(self) -> None:
        self.visivel = False
        self._parar()
        self.place_forget()

    def _girar(self) -> None:
        self._job = None
        if not self.visivel:
            return
        self._ang = (self._ang - _PASSO) % 360
        self._cv.itemconfigure(self._arco, start=self._ang)
        self._job = self.after(_TICK_MS, self._girar)

    def _parar(self) -> None:
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:  # noqa: BLE001
                pass
            self._job = None

    def destroy(self) -> None:
        self._parar()
        super().destroy()
