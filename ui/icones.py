"""
Ícones de linha (estilo Lucide) do Guichê, desenhados com Pillow.
Grade 24x24 renderizada em alta resolução e reduzida com antialiasing
(nítido em qualquer escala de DPI). Sem arquivos externos; resultado em cache.
Nome desconhecido -> círculo (registrado uma vez no log).
"""
import logging
from functools import lru_cache
from typing import Callable

import customtkinter as ctk
from PIL import Image, ImageDraw

log = logging.getLogger("guiche.icones")

_GRADE = 24
_ESC = 16            # 24 * 16 = 384 px de prancheta
_ESPESSURA = 2.0     # traço Lucide padrão

_avisados: set[str] = set()


class _Caneta:
    def __init__(self, cor: str):
        lado = _GRADE * _ESC
        self.img = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)
        self.cor = cor
        self.w = int(_ESPESSURA * _ESC)
        self.m = self.w / 2

    def _caixa(self, x0, y0, x1, y1):
        m = self.m
        return (x0 * _ESC - m, y0 * _ESC - m, x1 * _ESC + m, y1 * _ESC + m)

    def linha(self, *pts, fechar: bool = False):
        p = [(x * _ESC, y * _ESC) for x, y in pts]
        if fechar:
            p.append(p[0])
        self.d.line(p, fill=self.cor, width=self.w, joint="curve")
        for x, y in (p[0], p[-1]):
            self.d.ellipse((x - self.m, y - self.m, x + self.m, y + self.m), fill=self.cor)

    def circ(self, cx, cy, r):
        self.d.ellipse(self._caixa(cx - r, cy - r, cx + r, cy + r),
                       outline=self.cor, width=self.w)

    def ponto(self, cx, cy):
        r = self.m * 1.1
        x, y = cx * _ESC, cy * _ESC
        self.d.ellipse((x - r, y - r, x + r, y + r), fill=self.cor)

    def arco(self, x0, y0, x1, y1, ini, fim):
        """Ângulos em graus, sentido horário a partir das 3 h (padrão Pillow)."""
        self.d.arc((x0 * _ESC, y0 * _ESC, x1 * _ESC, y1 * _ESC), start=ini, end=fim,
                   fill=self.cor, width=self.w)


# ---- Desenhos ---------------------------------------------------------
def _megaphone(c):
    c.linha((3, 11), (21, 6), (21, 18), (3, 14), fechar=True)
    c.linha((11.6, 16.8), (10.8, 19), (8.6, 20), (6.4, 19), (5.8, 16.4))


def _repeat(c):
    c.arco(4, 4, 20, 20, 30, 330)
    c.linha((15, 3.5), (19.5, 6.5), (16.5, 11))


def _play(c):
    c.linha((7, 4), (19, 12), (7, 20), fechar=True)


def _pause(c):
    c.linha((9, 5), (9, 19))
    c.linha((15, 5), (15, 19))


def _ban(c):
    c.circ(12, 12, 10)
    c.linha((4.9, 4.9), (19.1, 19.1))


def _check(c):
    c.linha((20, 6), (9, 17), (4, 12))


def _key(c):
    c.circ(7.5, 15.5, 4.5)
    c.linha((10.7, 12.3), (21, 2))
    c.linha((15.5, 7.5), (18.5, 10.5), (22, 7), (19, 4))


def _power(c):
    c.linha((12, 2), (12, 12))
    c.arco(3, 4, 21, 22, -55, 235)


def _undo(c):
    c.linha((9, 14), (4, 9), (9, 4))
    c.linha((4, 9), (14.5, 9))
    c.arco(9, 9, 20, 20, 270, 450)
    c.linha((14.5, 20), (11, 20))


def _monitor(c):
    c.linha((3, 3), (21, 3), (21, 17), (3, 17), fechar=True)
    c.linha((8, 21), (16, 21))
    c.linha((12, 17), (12, 21))


def _message_square(c):
    c.linha((3, 21), (3, 5), (5, 3), (19, 3), (21, 5), (21, 15), (19, 17), (7, 17),
            fechar=True)


def _x(c):
    c.linha((18, 6), (6, 18))
    c.linha((6, 6), (18, 18))


def _calendar(c):
    c.linha((3, 4), (21, 4), (21, 22), (3, 22), fechar=True)
    c.linha((3, 10), (21, 10))
    c.linha((8, 2), (8, 6))
    c.linha((16, 2), (16, 6))


def _image(c):
    c.linha((3, 3), (21, 3), (21, 21), (3, 21), fechar=True)
    c.circ(9, 9, 2)
    c.linha((21, 15), (16, 10), (5, 21))


def _video(c):
    c.linha((2, 6), (16, 6), (16, 18), (2, 18), fechar=True)
    c.linha((16, 10), (22, 7), (22, 17), (16, 14))


def _upload(c):
    c.linha((12, 15), (12, 3))
    c.linha((7, 8), (12, 3), (17, 8))
    c.linha((3, 15), (3, 21), (21, 21), (21, 15))


def _trash(c):
    c.linha((3, 6), (21, 6))
    c.linha((19, 6), (18, 21), (6, 21), (5, 6))
    c.linha((9, 6), (9, 3), (15, 3), (15, 6))
    c.linha((10, 11), (10, 17))
    c.linha((14, 11), (14, 17))


def _edit(c):
    c.linha((17, 3), (21, 7), (8, 20), (3, 21), (4, 16), fechar=True)


def _arrow_up(c):
    c.linha((12, 19), (12, 5))
    c.linha((5, 12), (12, 5), (19, 12))


def _arrow_down(c):
    c.linha((12, 5), (12, 19))
    c.linha((19, 12), (12, 19), (5, 12))


def _refresh(c):
    c.arco(4, 4, 20, 20, 0, 300)
    c.linha((15.5, 1.5), (16, 5.1), (12.5, 6))


def _wifi(c):
    c.arco(2, 6, 22, 26, 225, 315)
    c.arco(5.5, 9.5, 18.5, 22.5, 225, 315)
    c.arco(9, 13, 15, 19, 225, 315)
    c.ponto(12, 19)


def _help(c):
    c.circ(12, 12, 10)
    c.arco(9, 6, 15, 12, 180, 360)
    c.linha((15, 9), (12, 12), (12, 13.5))
    c.ponto(12, 17)


def _copy(c):
    c.linha((8, 8), (21, 8), (21, 21), (8, 21), fechar=True)
    c.linha((16, 8), (16, 3), (3, 3), (3, 16), (8, 16))


def _chevron(c):
    c.linha((9, 6), (15, 12), (9, 18))


def _plus(c):
    c.linha((12, 5), (12, 19))
    c.linha((5, 12), (19, 12))


def _counter(c):
    """Guichê: atendente atrás do balcão."""
    c.circ(12, 5.5, 2.5)
    c.arco(7, 9.5, 17, 19.5, 180, 360)
    c.linha((2, 14), (22, 14))
    c.linha((4, 14), (4, 21))
    c.linha((20, 14), (20, 21))


def _users(c):
    """Usuários: pessoa à frente + pessoa ao fundo (meio perfil)."""
    c.circ(9, 7, 4)
    c.arco(2, 15, 16, 27, 180, 360)
    c.arco(12, 3, 20, 11, 270, 450)
    c.arco(14, 15, 22, 27, 270, 360)


def _circulo(c):
    c.circ(12, 12, 8)


_ICONES: dict[str, Callable] = {
    "megaphone": _megaphone,
    "repeat": _repeat,
    "play": _play,
    "pause": _pause,
    "ban": _ban,
    "check": _check,
    "key": _key,
    "power": _power,
    "undo": _undo,
    "monitor": _monitor,
    "message-square": _message_square,
    "x": _x,
    "calendar": _calendar,
    "image": _image,
    "video": _video,
    "upload": _upload,
    "trash": _trash,
    "edit": _edit,
    "arrow-up": _arrow_up,
    "arrow-down": _arrow_down,
    "refresh": _refresh,
    "wifi": _wifi,
    "help": _help,
    "copy": _copy,
    "chevron": _chevron,
    "plus": _plus,
    "counter": _counter,
    "users": _users,
}


def _desenho(nome: str | None) -> Callable:
    chave = (nome or "").strip().lower()
    desenho = _ICONES.get(chave)
    if desenho is None:
        if chave not in _avisados:
            _avisados.add(chave)
            log.warning("Ícone desconhecido '%s'; usando círculo.", chave)
        return _circulo
    return desenho


@lru_cache(maxsize=256)
def icone(nome: str | None, tamanho: int, cor: str) -> ctk.CTkImage:
    """CTkImage pronto para CTkButton/CTkLabel."""
    caneta = _Caneta(cor)
    _desenho(nome)(caneta)
    img = caneta.img.resize((tamanho * 4, tamanho * 4), Image.LANCZOS)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(tamanho, tamanho))
