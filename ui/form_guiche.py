"""
Formulário de guichê (cadastro/edição) em sobreposição, no padrão de FormMidia.
- Apenas o nome: os setores atendidos vêm do usuário (usuario_setores).
- Validação local instantânea: erro fica no formulário.
- Salvar trava o formulário; erro destrava; sucesso fecha.
"""
from typing import Callable

import customtkinter as ctk

from services import guiches_service
from ui import theme as T
from ui import widgets as W
from ui.sobreposicao import Sobreposicao

_LARG = 360
_SUB = "Informe o nome do guichê. Os setores atendidos são definidos no usuário."


class FormGuiche(Sobreposicao):
    def __init__(self, master, valores: dict,
                 ao_salvar: Callable[[dict, "FormGuiche"], None], editar: bool = False):
        super().__init__(master, "Editar guichê" if editar else "Novo guichê", _SUB)
        self._cb = ao_salvar

        c = self.corpo
        c.grid_columnconfigure(0, weight=1)
        campos = ctk.CTkFrame(c, fg_color="transparent")
        campos.grid(row=0, column=0, sticky="ew")

        W.rotulo(campos, "Nome", 14, "bold").pack(anchor="w", pady=(0, 4))
        self._f_nome = W.entrada(campos, "Nome do guichê", width=_LARG)
        self._f_nome.pack(fill="x")
        self._f_nome.insert(0, valores.get("nome") or "")

        self.rodape_padrao("Salvar", self._salvar, _LARG)
        self.exibir(foco=self._f_nome)

    def _salvar(self) -> None:
        if self.travado or self.fechado:
            return
        d = {"nome": self._f_nome.get()}
        erros = guiches_service.validar(d)
        if erros:
            return self.erro(next(iter(erros.values())))
        self.travar(True)
        self.status("Salvando…")
        self._cb(d, self)

    def erro(self, msg: str) -> None:
        if self.fechado:
            return
        self.travar(False)
        self.status(msg, T.DANGER)

    def concluir(self) -> None:
        if self.fechado:
            return
        self.travar(False)
        self.fechar()
