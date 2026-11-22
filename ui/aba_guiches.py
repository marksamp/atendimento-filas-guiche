"""
Aba "Guichês" (somente gestor): lista, cadastro, edição, desativação/reativação
e exclusão (só sem histórico; se o banco recusar, orienta a desativar).
Linhas reaproveitadas (pool), como na aba de mídias.
Guichê não tem setor: os setores atendidos vêm do usuário.
"""
import logging
from tkinter import TclError
from typing import Optional

import customtkinter as ctk

from services import guiches_service as svc
from services.auth import Usuario
from ui import tarefa
from ui import theme as T
from ui import widgets as W
from ui.confirmacao import Confirmacao
from ui.form_guiche import FormGuiche
from ui.prontidao import Prontidao

log = logging.getLogger(__name__)


def _vivo(w) -> bool:
    try:
        return tarefa.ativo() and bool(w.winfo_exists())
    except TclError:
        return False


def _situacao(g: dict) -> tuple[str, str]:
    if not g["ativo"]:
        return "Inativo", T.TXT_MUTED
    if g["em_uso"]:
        return "Em uso", T.WARN
    return "Ativo", T.NEON


class LinhaGuiche(ctk.CTkFrame):
    def __init__(self, master, acoes: dict):
        super().__init__(master, fg_color=T.BG_ITEM, corner_radius=12)
        self.grid_columnconfigure(0, weight=1)
        self._g: Optional[dict] = None
        self._tit = W.rotulo(self, "", 15, "bold", anchor="w")
        self._tit.grid(row=0, column=0, sticky="w", padx=14, pady=12)
        self._sit = W.rotulo(self, "", 13, "bold", width=80)
        self._sit.grid(row=0, column=1, padx=8)
        W.botao(self, "", lambda: self._g and acoes["editar"](self._g), icone="edit",
                height=36, size=12, width=40).grid(row=0, column=2, padx=4)
        self._bt = W.botao(self, "", lambda: self._g and acoes["alternar"](self._g),
                           icone="power", height=36, size=12, width=110)
        self._bt.grid(row=0, column=3, padx=4)
        W.botao(self, "", lambda: self._g and acoes["excluir"](self._g), icone="trash",
                height=36, size=12, width=40).grid(row=0, column=4, padx=(4, 10))

    def mostrar(self, g: dict) -> None:
        self._g = g
        W.configurar(self._tit, text=g["nome"])
        texto, cor = _situacao(g)
        W.configurar(self._sit, text=texto, text_color=cor)
        W.configurar(self._bt, text="Desativar" if g["ativo"] else "Reativar")


class AbaGuiches(ctk.CTkFrame):
    def __init__(self, master, usuario: Usuario):
        super().__init__(master, fg_color="transparent")
        self._usuario = usuario
        self._linhas: list[LinhaGuiche] = []
        self._qtd = 0
        self._carregando = False
        self.pronto = Prontidao()
        self._dialogo = None
        self._acoes = {"editar": self._editar, "alternar": self._alternar,
                       "excluir": self._excluir}
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.grid(row=0, column=0, sticky="ew")
        W.botao(topo, "Novo guichê", self._adicionar, primario=True, icone="plus",
                height=44, size=14).pack(side="left")
        W.botao(topo, "Atualizar", self.atualizar, icone="refresh", height=44,
                size=14).pack(side="left", padx=8)
        self._contador = W.rotulo(topo, "", 13, cor=T.TXT_MUTED)
        self._contador.pack(side="right")
        self._aviso = W.rotulo(self, "", 13, cor=T.TXT_MUTED, anchor="w")
        self._aviso.grid(row=1, column=0, sticky="ew", pady=(8, 4))
        self._lista = W.ListaRolavel(self)
        self._lista.grid(row=2, column=0, sticky="nsew")
        self._vazio = W.rotulo(self._lista, "Carregando guichês…", 14, cor=T.TXT_MUTED)
        self._vazio.pack(pady=24)

    # ---- Carregamento ----------------------------------------------------
    def atualizar(self) -> None:
        if self._carregando:
            return
        self._carregando = True
        self.pronto.iniciar()
        tarefa.executar(lambda: svc.listar(), self._mostrar, self._falha, "guiches-listar")

    def _falha(self, exc: Exception) -> None:
        self._carregando = False
        try:
            if _vivo(self):
                if self._qtd == 0:
                    W.configurar(self._vazio, text="Não foi possível carregar os guichês.")
                self._status(svc.mensagem(exc), T.DANGER)
        finally:
            self.pronto.concluir()

    def _mostrar(self, itens: list[dict]) -> None:
        self._carregando = False
        try:
            if _vivo(self):
                self._render(itens)
        finally:
            self.pronto.concluir()

    def _render(self, itens: list[dict]) -> None:
        n = len(itens)
        while len(self._linhas) < n:
            self._linhas.append(LinhaGuiche(self._lista, self._acoes))
        for linha, g in zip(self._linhas, itens):
            linha.mostrar(g)
        if n:
            self._vazio.pack_forget()
        else:
            W.configurar(self._vazio, text="Nenhum guichê cadastrado.")
            self._vazio.pack(pady=24)
        if n != self._qtd:
            for i in range(self._qtd, n):
                self._linhas[i].pack(fill="x", pady=3, padx=2)
            for i in range(n, self._qtd):
                self._linhas[i].pack_forget()
            self._qtd = n
            self._lista.ajustar_barra()
        ativos = sum(1 for g in itens if g["ativo"])
        W.configurar(self._contador, text=f"{ativos} ativo(s) de {n}")

    def _status(self, texto: str, cor: str = T.TXT_MUTED) -> None:
        W.configurar(self._aviso, text=texto, text_color=cor)

    def _ocupado(self) -> bool:
        return self._dialogo is not None and not self._dialogo.fechado

    # ---- Cadastro / edição -----------------------------------------------
    def _adicionar(self) -> None:
        if not self._ocupado():
            self._dialogo = FormGuiche(self, {}, self._cadastrar)

    def _cadastrar(self, dados: dict, form: FormGuiche) -> None:
        tarefa.executar(lambda: svc.cadastrar(self._usuario, dados),
                        lambda _r: self._salvo(form, "Guichê cadastrado."),
                        lambda e: form.erro(svc.mensagem(e)), "guiches-cadastrar")

    def _editar(self, g: dict) -> None:
        if self._ocupado():
            return
        self._dialogo = FormGuiche(
            self, g,
            lambda d, f: tarefa.executar(
                lambda: svc.editar(self._usuario, g["id"], d),
                lambda _r: self._salvo(f, "Guichê atualizado."),
                lambda e: f.erro(svc.mensagem(e)), "guiches-editar"),
            editar=True)

    def _salvo(self, form: FormGuiche, texto: str) -> None:
        form.concluir()
        if _vivo(self):
            self._status(texto, T.NEON)
            self.atualizar()

    # ---- Desativar / reativar --------------------------------------------
    def _alternar(self, g: dict) -> None:
        if self._ocupado():
            return
        ativar = not g["ativo"]

        def confirmar(c: Confirmacao):
            c.ocupado("Reativando…" if ativar else "Desativando…")
            tarefa.executar(lambda: svc.definir_ativo(self._usuario, g["id"], ativar),
                            lambda _r: self._concluido(
                                c, "Guichê reativado." if ativar else "Guichê desativado."),
                            lambda e: c.erro(svc.mensagem(e)), "guiches-ativo")

        acao = "Reativar" if ativar else "Desativar"
        msg = (f"{acao} \"{g['nome']}\"?" +
               ("" if ativar else "\nEle deixará de aparecer na abertura de sessão."))
        self._dialogo = Confirmacao(self, f"{acao} guichê", msg, ok=acao,
                                    perigo=not ativar, ao_confirmar=confirmar)

    # ---- Exclusão --------------------------------------------------------
    def _excluir(self, g: dict) -> None:
        if self._ocupado():
            return

        def confirmar(c: Confirmacao):
            c.ocupado("Excluindo…")
            tarefa.executar(lambda: svc.excluir(self._usuario, g["id"]),
                            lambda _r: self._concluido(c, "Guichê excluído."),
                            lambda e: c.erro(svc.mensagem(e)), "guiches-excluir")

        msg = (f"Excluir \"{g['nome']}\" definitivamente?\n"
               "Só é permitido para guichê sem histórico; caso contrário, use Desativar.")
        self._dialogo = Confirmacao(self, "Excluir guichê", msg, ok="Excluir",
                                    perigo=True, ao_confirmar=confirmar)

    def _concluido(self, c: Confirmacao, texto: str) -> None:
        c.fechar(forcar=True)
        if _vivo(self):
            self._status(texto, T.NEON)
            self.atualizar()
