"""
Tela "Guichês" (somente gestor): cabeçalho + AbaGuiches no card.
abrir() ao exibir, ocultar() ao sair (App), encerrar() no logout.
Prontidão: quando_pronto() delega à aba (carga da lista concluída, ok OU erro).
"""
from typing import Callable

import customtkinter as ctk

from services.auth import Usuario
from ui import tarefa
from ui import theme as T
from ui import widgets as W
from ui.aba_guiches import AbaGuiches


class TelaGuiches(ctk.CTkFrame):
    def __init__(self, master, usuario: Usuario):
        super().__init__(master, fg_color=T.BG_APP)
        if not usuario.gestor:
            raise PermissionError("Tela restrita a gestores.")
        tarefa.instalar(self)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 12))
        W.rotulo(topo, "Guichês", 22, "bold").pack(side="left")
        W.rotulo(topo, "Desativados não aparecem no login; o histórico é mantido.",
                 13, cor=T.TXT_MUTED).pack(side="right")

        corpo = W.card(self)
        corpo.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 24))
        corpo.grid_columnconfigure(0, weight=1)
        corpo.grid_rowconfigure(0, weight=1)
        self._aba = AbaGuiches(corpo, usuario)
        self._aba.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)

    def quando_pronto(self, cb: Callable[[], None]) -> None:
        self._aba.pronto.quando(cb)

    def abrir(self) -> None:
        """Chamado pelo App a cada exibição: recarrega a lista."""
        self._aba.atualizar()

    def ocultar(self) -> None:
        pass

    def encerrar(self) -> None:
        self.ocultar()
