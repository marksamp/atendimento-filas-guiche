"""
Double buffering da janela no Windows (WS_EX_COMPOSITED): elimina o flicker do CTk.
- preferir(): estado desejado pela navegação (ex.: desligado no Letreiro).
- suspender()/retomar(): só para animações contínuas (contador; aninhável).
- hwnd em cache: não força update_idletasks() no meio de transições.
- Diagnóstico: GUICHE_SEM_ANTIFLICKER=1 desliga o recurso por completo.
"""
import logging
import os
import sys

log = logging.getLogger(__name__)

_GWL_EXSTYLE = -20
_WS_EX_COMPOSITED = 0x02000000
_SWP = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020   # NOSIZE|NOMOVE|NOZORDER|NOACTIVATE|FRAMECHANGED
_DESATIVADO = os.environ.get("GUICHE_SEM_ANTIFLICKER") == "1"

if _DESATIVADO:
    log.warning("Anti-flicker DESATIVADO por GUICHE_SEM_ANTIFLICKER=1 (diagnóstico).")


def _hwnd(janela) -> int:
    h = getattr(janela, "_af_hwnd", None)
    if h:
        return h
    import ctypes
    janela.update_idletasks()
    h = ctypes.windll.user32.GetParent(janela.winfo_id()) or janela.winfo_id()
    janela._af_hwnd = h
    return h


def ligado(janela) -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        estilo = ctypes.windll.user32.GetWindowLongW(_hwnd(janela), _GWL_EXSTYLE)
        return bool(estilo & _WS_EX_COMPOSITED)
    except Exception:  # noqa: BLE001
        return False


def definir(janela, ligar: bool) -> None:
    if sys.platform != "win32":
        return
    ligar = ligar and not _DESATIVADO
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = _hwnd(janela)
        estilo = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        novo = (estilo | _WS_EX_COMPOSITED) if ligar else (estilo & ~_WS_EX_COMPOSITED)
        if novo != estilo:
            user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, novo)
            user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, _SWP)
            log.info("Anti-flicker %s (hwnd=%s).", "ligado" if ligar else "desligado", hwnd)
    except Exception as exc:  # noqa: BLE001
        log.warning("Anti-flicker indisponível: %s", exc)


def preferir(raiz, ligar: bool) -> None:
    """Estado desejado; aplicado já ou quando a última suspensão terminar."""
    raiz._af_pref = ligar
    if not getattr(raiz, "_af_modais", 0):
        definir(raiz, ligar)


def aplicar(janela) -> None:
    preferir(janela, True)


def suspender(raiz) -> None:
    n = getattr(raiz, "_af_modais", 0)
    if n == 0:
        definir(raiz, False)
    raiz._af_modais = n + 1


def retomar(raiz) -> None:
    n = max(0, getattr(raiz, "_af_modais", 0) - 1)
    raiz._af_modais = n
    if n == 0:
        definir(raiz, getattr(raiz, "_af_pref", True))
