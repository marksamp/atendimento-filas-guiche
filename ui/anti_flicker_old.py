"""Double buffering da janela no Windows (WS_EX_COMPOSITED): elimina o flicker do CTk."""
import logging
import sys

log = logging.getLogger(__name__)

_GWL_EXSTYLE = -20
_WS_EX_COMPOSITED = 0x02000000


def aplicar(janela) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        janela.update_idletasks()
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(janela.winfo_id()) or janela.winfo_id()
        estilo = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        if not estilo & _WS_EX_COMPOSITED:
            user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, estilo | _WS_EX_COMPOSITED)
    except Exception as exc:  # noqa: BLE001
        log.warning("Anti-flicker indisponível: %s", exc)
