"""
Tela de loading opaca que cobre a janela inteira (inclusive o Menu Gestão).
tk puro (sem CustomTkinter): pinta instantaneamente, sem desenho em etapas.
"""
import tkinter as tk

from ui import theme as T


def _cor(c) -> str:
    return c[1] if isinstance(c, (tuple, list)) else c


class TelaCarregando(tk.Frame):
    def __init__(self, master):
        fundo = _cor(T.BG_APP)
        super().__init__(master, bg=fundo, bd=0, highlightthickness=0)
        caixa = tk.Frame(self, bg=fundo)
        caixa.place(relx=0.5, rely=0.5, anchor="center")
        self._cv = tk.Canvas(caixa, width=64, height=64, bg=fundo, highlightthickness=0)
        self._cv.pack()
        self._cv.create_oval(6, 6, 58, 58, outline=_cor(T.BORDER), width=5)
        self._arco = self._cv.create_arc(6, 6, 58, 58, start=90, extent=100, style="arc",
                                         outline=_cor(T.NEON), width=5)
        self._lbl = tk.Label(caixa, text="Carregando…", bg=fundo, fg=_cor(T.TXT_MUTED),
                             font=("Segoe UI", 14))
        self._lbl.pack(pady=(14, 0))
        self._ang = 90
        self._job = None
        self.visivel = False

    def mostrar(self, texto: str = "Carregando…") -> None:
        self._lbl.configure(text=texto)
        if not self.visivel:
            self.visivel = True
            self.place(x=0, y=0, relwidth=1, relheight=1)
            self._girar()
        self.lift()

    def esconder(self) -> None:
        if not self.visivel:
            return
        self.visivel = False
        if self._job:
            self.after_cancel(self._job)
            self._job = None
        self.place_forget()

    def _girar(self) -> None:
        self._ang = (self._ang - 12) % 360
        self._cv.itemconfigure(self._arco, start=self._ang)
        self._job = self.after(30, self._girar)
