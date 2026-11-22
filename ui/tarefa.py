"""
Execução em segundo plano para as telas (a GUI nunca bloqueia).

- executar(fn, ok, erro): fn roda em thread daemon; ok/erro são chamados NO Tk.
- entregar(cb, *args): agenda cb no Tk a partir de qualquer thread.
Tkinter não é thread-safe: a entrega usa fila consumida por after().
O próximo ciclo é agendado ANTES dos callbacks (modal com wait_window não congela).
Com a janela principal destruída, entregas pendentes são descartadas.
Recusa de regra (ErroNegocio) vai ao log como INFO, sem traceback.
"""
import logging
import queue
import threading
from typing import Callable, Optional

from services.erros import ErroNegocio

log = logging.getLogger(__name__)

_INTERVALO_MS = 80
_fila: "queue.SimpleQueue" = queue.SimpleQueue()
_raiz = None
_ativo = False


def ativo() -> bool:
    return _ativo


def instalar(widget) -> None:
    global _raiz, _ativo
    if _raiz is None:
        _raiz = widget.winfo_toplevel()
        _ativo = True
        _raiz.bind("<Destroy>", _ao_destruir, add="+")
        _raiz.after(_INTERVALO_MS, _bombear)


def _ao_destruir(evento) -> None:
    global _ativo
    if evento.widget is _raiz:
        _ativo = False


def _bombear() -> None:
    if not _ativo:
        return
    try:
        _raiz.after(_INTERVALO_MS, _bombear)
    except Exception:  # noqa: BLE001
        return                                    # janela encerrada
    while _ativo:
        try:
            cb, args = _fila.get_nowait()
        except queue.Empty:
            break
        try:
            cb(*args)
        except Exception:  # noqa: BLE001
            if _ativo:
                log.exception("Falha ao atualizar a tela.")


def entregar(cb: Callable, *args) -> None:
    if _ativo:
        _fila.put((cb, args))


def executar(fn: Callable, ok: Optional[Callable] = None,
             erro: Optional[Callable[[Exception], None]] = None, nome: str = "tarefa-ui") -> None:
    def alvo():
        try:
            resultado = fn()
        except ErroNegocio as exc:
            log.info("Tarefa '%s' recusada: %s", nome, exc)
            if erro:
                entregar(erro, exc)
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("Tarefa '%s' falhou: %s", nome, exc, exc_info=True)
            if erro:
                entregar(erro, exc)
            return
        if ok:
            entregar(ok, resultado)

    threading.Thread(target=alvo, name=nome, daemon=True).start()
