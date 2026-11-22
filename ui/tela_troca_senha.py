"""Troca de senha (obrigatória no primeiro acesso ou voluntária)."""
from typing import Callable, Optional

import customtkinter as ctk

from database import descrever_erro
from services import auth
from services.auth import ErroLogin, Usuario
from ui import theme as T
from ui import widgets as W

LARGURA = 380


class TelaTrocaSenha(ctk.CTkFrame):
    def __init__(self, master, executar_bg: Callable):
        super().__init__(master, fg_color="transparent")
        self._bg = executar_bg
        self._usuario: Optional[Usuario] = None
        self._ao_concluir: Callable[[], None] = lambda: None
        self._ao_cancelar: Callable[[], None] = lambda: None
        self._erros: dict[str, ctk.CTkLabel] = {}
        self._campos: dict[str, W.CampoSenha] = {}

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        c = W.card(self)
        c.grid(row=0, column=0)
        c.grid_columnconfigure((0, 1), weight=1, uniform="b")
        px = 40

        W.rotulo(c, "🔑  ALTERAR SENHA", 22, "bold", T.NEON).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=px, pady=(36, 2))
        self.lbl_aviso = W.rotulo(c, "", 14, cor=T.TXT_MUTED, width=LARGURA, anchor="w",
                                  justify="left", wraplength=LARGURA)
        self.lbl_aviso.grid(row=1, column=0, columnspan=2, sticky="w", padx=px, pady=(0, 14))

        linha = 2
        for chave, rotulo in (("atual", "Senha atual"), ("nova", "Nova senha"),
                              ("confirmacao", "Confirme a nova senha")):
            W.rotulo(c, rotulo, 14, "bold").grid(row=linha, column=0, columnspan=2,
                                                 sticky="w", padx=px)
            campo = W.CampoSenha(c, width=LARGURA)
            campo.grid(row=linha + 1, column=0, columnspan=2, sticky="ew", padx=px, pady=(4, 0))
            campo.bind_enter(self._salvar)
            err = W.rotulo(c, "", 12, cor=T.DANGER, width=LARGURA, height=24, anchor="w")
            err.grid(row=linha + 2, column=0, columnspan=2, sticky="w", padx=px)
            self._campos[chave], self._erros[chave] = campo, err
            linha += 3

        self.lbl_status = W.rotulo(c, "", 14, "bold", T.TXT_MUTED, width=LARGURA, height=40,
                                   wraplength=LARGURA)
        self.lbl_status.grid(row=linha, column=0, columnspan=2, padx=px)
        self.btn_cancelar = W.botao(c, "Cancelar", lambda: self._ao_cancelar())
        self.btn_cancelar.grid(row=linha + 1, column=0, sticky="ew", padx=(px, 6), pady=(4, 32))
        self.btn_salvar = W.botao(c, "Salvar", self._salvar, primario=True)
        self.btn_salvar.grid(row=linha + 1, column=1, sticky="ew", padx=(6, px), pady=(4, 32))

    def preparar(self, usuario: Usuario, obrigatoria: bool,
                 ao_concluir: Callable[[], None], ao_cancelar: Callable[[], None]) -> None:
        self._usuario = usuario
        self._ao_concluir, self._ao_cancelar = ao_concluir, ao_cancelar
        self.lbl_aviso.configure(text=(
            f"{usuario.nome}, defina uma nova senha para continuar."
            if obrigatoria else "Informe a senha atual e a nova senha."))
        self.btn_cancelar.configure(text="Voltar ao login" if obrigatoria else "Cancelar")
        for campo in self._campos.values():
            campo.limpar()
        self._mostrar_erros({})
        self._status("")
        self._travar(False)
        self._campos["atual"].entry.focus_set()

    def _mostrar_erros(self, erros: dict[str, str]) -> None:
        for chave, lbl in self._erros.items():
            lbl.configure(text=erros.get(chave, ""))
            self._campos[chave].entry.configure(
                border_color=T.DANGER if chave in erros else T.BORDER)

    def _salvar(self) -> None:
        if self.btn_salvar.cget("state") == "disabled" or not self._usuario:
            return
        atual, nova, conf = (self._campos[k].get() for k in ("atual", "nova", "confirmacao"))
        erros = auth.validar_nova_senha(atual, nova, conf)
        self._mostrar_erros(erros)
        if erros:
            return
        self._travar(True)
        self._status("Salvando...")
        uid = self._usuario.id

        def ok(_r):
            self._travar(False)
            self._usuario.trocar_senha = False
            self._ao_concluir()

        def falha(exc):
            self._travar(False)
            msg = str(exc) if isinstance(exc, ErroLogin) else descrever_erro(exc)
            self._status(f"✖ {msg}", T.DANGER)

        self._bg(lambda: auth.trocar_senha(uid, atual, nova, conf), ok, falha)

    def _status(self, texto: str, cor: str = T.TXT_MUTED) -> None:
        self.lbl_status.configure(text=texto, text_color=cor)

    def _travar(self, travado: bool) -> None:
        estado = "disabled" if travado else "normal"
        self.btn_salvar.configure(state=estado)
        self.btn_cancelar.configure(state=estado)
