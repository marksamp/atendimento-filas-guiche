"""
Tela "Mídias do painel" (somente gestor): abas Mídias e Status dos painéis.
Abas empilhadas na mesma célula; trocar = tkraise (sem remontar → sem flash).
abrir() ao exibir, ocultar() ao sair (App), encerrar() no logout.
Prontidão: quando_pronto() delega à aba atual (carga da lista concluída, ok OU erro).
"""
from typing import Callable

import customtkinter as ctk

from services.auth import Usuario
from ui import tarefa
from ui import theme as T
from ui import widgets as W
from ui.aba_midias import AbaMidias
from ui.aba_paineis import AbaPaineis
from ui.icones import icone


class TelaMidias(ctk.CTkFrame):
    def __init__(self, master, usuario: Usuario):
        super().__init__(master, fg_color=T.BG_APP)
        if not usuario.gestor:
            raise PermissionError("Tela restrita a gestores.")
        tarefa.instalar(self)
        self._exibida = False
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 12))
        W.rotulo(topo, "Mídias do painel", 22, "bold").pack(side="left")
        self._abas: dict[str, tuple[ctk.CTkButton, str, ctk.CTkFrame]] = {}
        corpo = W.card(self)
        corpo.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 24))
        corpo.grid_columnconfigure(0, weight=1)
        corpo.grid_rowconfigure(0, weight=1)

        for chave, texto, ico, classe in (("paineis", "Status dos painéis", "monitor", AbaPaineis),
                                          ("midias", "Mídias", "image", AbaMidias)):
            b = ctk.CTkButton(topo, text=texto, height=38, corner_radius=10, font=T.font(14),
                              compound="left", command=lambda k=chave: self.mostrar(k))
            b.pack(side="right", padx=4)
            aba = classe(corpo, usuario)
            aba.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
            self._abas[chave] = (b, ico, aba)
        self._atual = None
        self.mostrar("midias", atualizar=False)

    def quando_pronto(self, cb: Callable[[], None]) -> None:
        if self._atual:
            self._abas[self._atual][2].pronto.quando(cb)
        else:
            cb()

    def abrir(self) -> None:
        """Chamado pelo App a cada exibição: recarrega a aba atual."""
        self._exibida = True
        self._visibilidade()
        if self._atual:
            self._abas[self._atual][2].atualizar()

    def ocultar(self) -> None:
        self._exibida = False
        self._visibilidade()

    def encerrar(self) -> None:
        self.ocultar()

    def _visibilidade(self) -> None:
        for k, (_b, _i, aba) in self._abas.items():
            if hasattr(aba, "visivel"):
                aba.visivel(self._exibida and k == self._atual)

    def mostrar(self, chave: str, atualizar: bool = True) -> None:
        if chave == self._atual:
            return
        self._atual = chave
        for k, (b, ico, aba) in self._abas.items():
            sel = k == chave
            W.configurar(b, fg_color=T.NEON if sel else "transparent",
                         hover_color=T.NEON_DARK if sel else T.BG_CARD_HOV,
                         text_color=T.BG_APP if sel else T.TXT,
                         image=icone(ico, 18, T.BG_APP if sel else T.TXT))
            if sel:
                aba.tkraise()
                if atualizar:
                    aba.atualizar()
        self._visibilidade()
