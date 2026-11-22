"""
Seletor de cor livre (tema escuro): quadrado saturação/brilho + barra de matiz
+ campo #RRGGBB, sincronizados nos dois sentidos.
get() -> '#RRGGBB'; set(hex); ao_mudar(hex) a cada alteração válida.
Anti-flicker: o gradiente é atualizado no lugar (paste), só quando a matiz muda;
marcas criadas uma vez; ao_mudar limitado durante o arraste (+ 1 final ao soltar).
"""
import colorsys
import re
import tkinter as tk
from typing import Callable, Optional

import customtkinter as ctk
from PIL import Image, ImageTk

from ui import theme as T
from ui import widgets as W

_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_LARG, _ALT, _BARRA = 260, 150, 16
_ATRASO_MS = 60
_PASSOS_MATIZ = 360


def _hex_rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def _rgb_hex(r: float, g: float, b: float) -> str:
    return "#{:02X}{:02X}{:02X}".format(round(r * 255), round(g * 255), round(b * 255))


def _gradiente_sv(hue: float) -> Image.Image:
    cor = tuple(round(c * 255) for c in colorsys.hsv_to_rgb(hue, 1, 1))
    vert = Image.linear_gradient("L")                      # valor = y
    horiz = vert.transpose(Image.Transpose.TRANSPOSE)      # valor = x
    mistura = Image.composite(Image.new("RGB", (256, 256), cor),
                              Image.new("RGB", (256, 256), "white"), horiz)
    img = Image.composite(Image.new("RGB", (256, 256), "black"), mistura, vert)
    return img.resize((_LARG, _ALT))


def _barra_matiz() -> Image.Image:
    img = Image.new("RGB", (_LARG, 1))
    for x in range(_LARG):
        r, g, b = colorsys.hsv_to_rgb(x / (_LARG - 1), 1, 1)
        img.putpixel((x, 0), (round(r * 255), round(g * 255), round(b * 255)))
    return img.resize((_LARG, _BARRA))


class SeletorCor(ctk.CTkFrame):
    def __init__(self, master, cor: str = T.NEON,
                 ao_mudar: Optional[Callable[[str], None]] = None):
        super().__init__(master, fg_color="transparent")
        self._cb = ao_mudar
        self._h = self._s = self._v = 0.0
        self._matiz_q: Optional[int] = None
        self._emitida: Optional[str] = None
        self._job: Optional[str] = None

        self._sv = tk.Canvas(self, width=_LARG, height=_ALT, highlightthickness=1,
                             highlightbackground=T.BORDER, bd=0, cursor="crosshair")
        self._sv.grid(row=0, column=0, columnspan=2, sticky="w")
        self._img_sv = ImageTk.PhotoImage(_gradiente_sv(0.0))
        self._sv.create_image(0, 0, anchor="nw", image=self._img_sv)
        self._marca_sv = self._sv.create_oval(0, 0, 0, 0, outline="white", width=2)

        self._hue = tk.Canvas(self, width=_LARG, height=_BARRA, highlightthickness=1,
                              highlightbackground=T.BORDER, bd=0, cursor="sb_h_double_arrow")
        self._hue.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 8))
        self._img_h = ImageTk.PhotoImage(_barra_matiz())
        self._hue.create_image(0, 0, anchor="nw", image=self._img_h)
        self._marca_h = self._hue.create_rectangle(0, 0, 0, 0, outline="white", width=2)

        self._amostra = ctk.CTkFrame(self, width=36, height=36, corner_radius=8,
                                     border_width=1, border_color=T.BORDER)
        self._amostra.grid(row=2, column=0, sticky="w")
        self._campo = ctk.CTkEntry(self, width=_LARG - 48, height=36, font=T.font(14),
                                   fg_color=T.BG_ITEM, border_color=T.BORDER,
                                   text_color=T.TXT, corner_radius=10)
        self._campo.grid(row=2, column=1, sticky="e")
        self._campo.bind("<KeyRelease>", self._digitado)

        for ev in ("<Button-1>", "<B1-Motion>"):
            self._sv.bind(ev, self._clique_sv)
            self._hue.bind(ev, self._clique_hue)
        for cv in (self._sv, self._hue):
            cv.bind("<ButtonRelease-1>", lambda _e: self._emitir())
        self.set(cor)

    # ---- API -----------------------------------------------------------
    def get(self) -> str:
        return _rgb_hex(*colorsys.hsv_to_rgb(self._h, self._s, self._v))

    def set(self, cor: str) -> None:
        cor = cor if isinstance(cor, str) and _HEX_RE.match(cor) else T.NEON
        r, g, b = (c / 255 for c in _hex_rgb(cor))
        self._h, self._s, self._v = colorsys.rgb_to_hsv(r, g, b)
        self._emitida = self.get()
        self._render_sv()
        self._atualizar(campo=True, avisar=False)

    def destroy(self) -> None:
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:  # noqa: BLE001
                pass
            self._job = None
        super().destroy()

    # ---- Eventos ---------------------------------------------------------
    def _clique_sv(self, e) -> None:
        self._s = min(max(e.x / (_LARG - 1), 0), 1)
        self._v = 1 - min(max(e.y / (_ALT - 1), 0), 1)
        self._atualizar(campo=True)

    def _clique_hue(self, e) -> None:
        self._h = min(max(e.x / (_LARG - 1), 0), 1)
        self._render_sv()
        self._atualizar(campo=True)

    def _digitado(self, _e=None) -> None:
        txt = self._campo.get().strip()
        if not txt.startswith("#"):
            txt = "#" + txt
        if _HEX_RE.match(txt):
            r, g, b = (c / 255 for c in _hex_rgb(txt))
            h, self._s, self._v = colorsys.rgb_to_hsv(r, g, b)
            if self._s > 0:                       # cinza mantém a matiz atual
                self._h = h
            self._render_sv()
            self._atualizar(campo=False)

    # ---- Desenho -----------------------------------------------------------
    def _render_sv(self) -> None:
        q = round(self._h * (_PASSOS_MATIZ - 1))
        if q == self._matiz_q:
            return                                 # mesma matiz: nada a redesenhar
        self._matiz_q = q
        self._img_sv.paste(_gradiente_sv(q / (_PASSOS_MATIZ - 1)))   # no lugar

    def _atualizar(self, campo: bool, avisar: bool = True) -> None:
        x, y = self._s * (_LARG - 1), (1 - self._v) * (_ALT - 1)
        self._sv.coords(self._marca_sv, x - 6, y - 6, x + 6, y + 6)
        hx = self._h * (_LARG - 1)
        self._hue.coords(self._marca_h, hx - 3, 1, hx + 3, _BARRA)
        cor = self.get()
        W.configurar(self._amostra, fg_color=cor)
        if campo and self._campo.get() != cor:
            self._campo.delete(0, "end")
            self._campo.insert(0, cor)
        if avisar and self._cb and not self._job:
            self._job = self.after(_ATRASO_MS, self._emitir)

    def _emitir(self) -> None:
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:  # noqa: BLE001
                pass
            self._job = None
        cor = self.get()
        if self._cb and cor != self._emitida:
            self._emitida = cor
            self._cb(cor)
