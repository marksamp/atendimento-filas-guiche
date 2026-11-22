"""
Barreira de prontidão de uma tela (contrato com o App: quando_pronto(cb)).
- iniciar() antes de disparar uma carga obrigatória.
- concluir() ao fim dela, SEMPRE (sucesso ou erro), depois de renderizar.
- quando(cb): chama cb já se nada estiver pendente; senão, ao zerar o contador.
Roda na thread da UI; cada cb é chamado uma única vez.
"""
import logging
from typing import Callable

log = logging.getLogger(__name__)


class Prontidao:
    def __init__(self):
        self._pendentes = 0
        self._espera: list[Callable[[], None]] = []

    @property
    def pronto(self) -> bool:
        return self._pendentes == 0

    def iniciar(self) -> None:
        self._pendentes += 1

    def concluir(self) -> None:
        if self._pendentes == 0:
            return
        self._pendentes -= 1
        if self._pendentes == 0:
            self._liberar()

    def quando(self, cb: Callable[[], None]) -> None:
        if self._pendentes == 0:
            cb()
        else:
            self._espera.append(cb)

    def _liberar(self) -> None:
        cbs, self._espera = self._espera, []
        for cb in cbs:
            try:
                cb()
            except Exception:  # noqa: BLE001
                log.exception("Falha no aviso de prontidão.")
