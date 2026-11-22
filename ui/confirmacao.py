"""
Confirmação/aviso em sobreposição (padrão login).
ao_confirmar(c): opcional; permite mostrar "Excluindo…" no próprio card
(c.ocupado / c.erro / c.fechar(forcar=True)). Sem ele, fecha ao confirmar.
"""
from typing import Callable, Optional

from ui import theme as T
from ui import widgets as W
from ui.sobreposicao import Sobreposicao

LARGURA = 420


class Confirmacao(Sobreposicao):
    def __init__(self, master, titulo: str, mensagem: str, ok: str = "Confirmar",
                 perigo: bool = False, cancelar: Optional[str] = "Cancelar",
                 ao_confirmar: Optional[Callable[["Confirmacao"], None]] = None):
        super().__init__(master, titulo, cor=T.DANGER if perigo else T.NEON)
        self.resultado = False
        self._cb = ao_confirmar
        W.rotulo(self.corpo, mensagem, 14, cor=T.TXT, justify="left", anchor="w",
                 wraplength=LARGURA).pack(anchor="w", pady=(0, 8))
        self.rodape_padrao(ok, self._ok, LARGURA, perigo=perigo, cancelar=cancelar)
        self.exibir(foco=self.btn_ok)

    def _ok(self) -> None:
        if self.travado or self.fechado:
            return
        self.resultado = True
        if self._cb:
            self._cb(self)
        else:
            self.fechar()

    def ocupado(self, texto: str) -> None:
        self.travar(True)
        self.status(texto)

    def erro(self, msg: str) -> None:
        if not self.fechado:
            self.travar(False)
            self.status(msg, T.DANGER)
