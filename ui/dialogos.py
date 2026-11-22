"""
Diálogos padronizados.
- confirmar()/avisar(): sobreposição na janela principal (bloqueiam até fechar).
- modal(): CTkToplevel invisível (alpha 0) até estar centralizado; sem mexer no
  anti-flicker da principal (o estilo é por janela; alternar repintava tudo).
"""
import logging
from tkinter import TclError

import customtkinter as ctk

from ui.confirmacao import Confirmacao

log = logging.getLogger(__name__)

_ESPERA_MS = 50
_TENTATIVAS = 20


def app_vivo(w) -> bool:
    try:
        return bool(w.winfo_exists())
    except TclError:
        return False


def _alpha(janela, valor: float) -> None:
    try:
        janela.attributes("-alpha", valor)
    except TclError:
        pass


def modal(janela: ctk.CTkToplevel, master) -> None:
    """Centraliza sobre a principal, mostra já posicionada e captura o foco."""
    try:
        raiz = master.winfo_toplevel()
        janela.transient(raiz)
    except TclError as exc:
        log.warning("modal: transient falhou: %s", exc)
        return
    _alpha(janela, 0.0)
    estado = {"n": 0}

    def aplicar():
        try:
            if not janela.winfo_exists():
                return
            if not janela.winfo_viewable():
                estado["n"] += 1
                if estado["n"] < _TENTATIVAS:
                    janela.after(_ESPERA_MS, aplicar)
                    return
                janela.deiconify()
            janela.update_idletasks()
            x = raiz.winfo_rootx() + (raiz.winfo_width() - janela.winfo_width()) // 2
            y = raiz.winfo_rooty() + (raiz.winfo_height() - janela.winfo_height()) // 3
            janela.geometry(f"+{max(0, x)}+{max(0, y)}")
            janela.lift()
            janela.attributes("-topmost", True)
            janela.after(150, lambda: app_vivo(janela) and janela.attributes("-topmost", False))
            janela.after(16, lambda: app_vivo(janela) and _alpha(janela, 1.0))
            janela.grab_set()
            janela.focus_force()
        except TclError as exc:
            log.warning("modal: %s", exc)
            _alpha(janela, 1.0)

    janela.after(_ESPERA_MS, aplicar)


def _exibir(master, titulo: str, mensagem: str, **kw) -> bool:
    if not app_vivo(master):
        return False
    try:
        c = Confirmacao(master, titulo, mensagem, **kw)
        c.wait_window()
        return c.resultado
    except TclError:
        return False


def confirmar(master, titulo: str, mensagem: str, ok: str = "Confirmar",
              perigo: bool = False) -> bool:
    return _exibir(master, titulo, mensagem, ok=ok, perigo=perigo)


def avisar(master, titulo: str, mensagem: str) -> None:
    _exibir(master, titulo, mensagem, ok="OK", cancelar=None)
