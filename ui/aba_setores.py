"""
Aba "Setores" (somente gestor): lista ordenada, cadastro, edição, ordem (↑/↓),
desativação/reativação, exclusão (só sem senhas) e regeneração dos ícones PNG.
Linhas reaproveitadas (pool), como na aba de guichês.
Ícones da lista: PNG gravado (obter_png) buscado em segundo plano, com cache por
(id, icone); só busca de novo quando o ícone muda.
Anti-balanço: lista idêntica não redesenha nada; cada linha só se atualiza se os
próprios dados mudaram; textos cortados e colunas com largura fixa.
"""
import logging
from tkinter import TclError
from typing import Optional

import customtkinter as ctk

from services import setores_service as svc
from services.auth import Usuario
from ui import tarefa
from ui import theme as T
from ui import widgets as W
from ui.busca_icone import colorir, curto, vazio
from ui.confirmacao import Confirmacao
from ui.form_setor import FormSetor
from ui.prontidao import Prontidao

log = logging.getLogger(__name__)

_ICONE = 28
_NOME_MAX = 40
_DESC_MAX = 70


def _vivo(w) -> bool:
    try:
        return tarefa.ativo() and bool(w.winfo_exists())
    except TclError:
        return False


def _situacao(s: dict) -> tuple[str, str]:
    if not s["ativo"]:
        return "Inativo", T.TXT_MUTED
    if s["pendentes"]:
        return f"{s['pendentes']} na fila", T.WARN
    return "Ativo", T.NEON


def _chave(s: dict) -> tuple:
    """Tudo que afeta o desenho de uma linha."""
    return (s["id"], s["nome"], s.get("descricao"), s["prefixo"], s["icone"], s.get("cor"),
            bool(s["ativo"]), int(s["pendentes"] or 0), bool(s["tem_png"]))


def _carregar(cache: dict) -> tuple[list[dict], dict]:
    """Roda em thread: lista + PNGs que ainda não estão no cache."""
    itens = svc.listar()
    novo = {}
    for s in itens:
        chave = (int(s["id"]), s["icone"])
        if not s["tem_png"]:
            novo[chave] = None
        elif chave in cache:
            novo[chave] = cache[chave]
        else:
            novo[chave] = svc.obter_png(int(s["id"]))
    return itens, novo


class LinhaSetor(ctk.CTkFrame):
    def __init__(self, master, acoes: dict, vazio_img: ctk.CTkImage):
        super().__init__(master, fg_color=T.BG_ITEM, corner_radius=12, height=64)
        self.grid_columnconfigure(3, weight=1)
        self._s: Optional[dict] = None
        self._estado: Optional[tuple] = None
        self._vazio = vazio_img
        self._barra = ctk.CTkFrame(self, width=6, height=40, corner_radius=3)
        self._barra.grid(row=0, column=0, padx=(10, 10), pady=10)
        self._icone = ctk.CTkLabel(self, text="", image=vazio_img, width=_ICONE + 8)
        self._icone.grid(row=0, column=1)
        self._pref = W.rotulo(self, "", 18, "bold", width=56)
        self._pref.grid(row=0, column=2, padx=(6, 8))
        txt = ctk.CTkFrame(self, fg_color="transparent")
        txt.grid(row=0, column=3, sticky="ew")
        self._nome = W.rotulo(txt, "", 15, "bold", anchor="w")
        self._nome.pack(anchor="w")
        self._desc = W.rotulo(txt, "", 12, cor=T.TXT_MUTED, anchor="w")
        self._desc.pack(anchor="w")
        self._sit = W.rotulo(self, "", 13, "bold", width=110)
        self._sit.grid(row=0, column=4, padx=8)

        def bt(icone, chave, col, largura=40, padx=4):
            b = W.botao(self, "", lambda: self._s and acoes[chave](self._s), icone=icone,
                        height=36, size=12, width=largura)
            b.grid(row=0, column=col, padx=padx)
            return b

        self._sobe = bt("arrow-up", "subir", 5)
        self._desce = bt("arrow-down", "descer", 6)
        bt("edit", "editar", 7)
        self._bt = bt("power", "alternar", 8, 110)
        bt("trash", "excluir", 9, padx=(4, 10))

    def mostrar(self, s: dict, png: Optional[bytes], primeiro: bool, ultimo: bool) -> None:
        self._s = s
        estado = (_chave(s), png, primeiro, ultimo)
        if estado == self._estado:
            return                                  # linha idêntica: zero redesenho
        self._estado = estado
        cor = T.cor_segura(s.get("cor"))
        W.configurar(self._barra, fg_color=cor)
        W.configurar(self._icone, image=colorir(png, cor, _ICONE) or self._vazio)
        W.configurar(self._pref, text=s["prefixo"], text_color=cor)
        W.configurar(self._nome, text=curto(s["nome"], _NOME_MAX))
        W.configurar(self._desc, text=curto(s.get("descricao") or "—", _DESC_MAX))
        texto, cor_sit = _situacao(s)
        W.configurar(self._sit, text=texto, text_color=cor_sit)
        W.configurar(self._bt, text="Desativar" if s["ativo"] else "Reativar")
        W.habilitar(self._sobe, not primeiro)
        W.habilitar(self._desce, not ultimo)


class AbaSetores(ctk.CTkFrame):
    def __init__(self, master, usuario: Usuario):
        super().__init__(master, fg_color="transparent")
        self._usuario = usuario
        self._linhas: list[LinhaSetor] = []
        self._qtd = 0
        self._carregando = False
        self._movendo = False
        self._pngs: dict = {}
        self._assinatura: Optional[tuple] = None
        self._img_vazia = vazio(_ICONE)
        self.pronto = Prontidao()
        self._dialogo = None
        self._acoes = {"editar": self._editar, "alternar": self._alternar,
                       "excluir": self._excluir, "subir": lambda s: self._mover(s, -1),
                       "descer": lambda s: self._mover(s, 1)}
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.grid(row=0, column=0, sticky="ew")
        W.botao(topo, "Novo setor", self._adicionar, primario=True, icone="plus",
                height=44, size=14).pack(side="left")
        W.botao(topo, "Atualizar", self.atualizar, icone="refresh", height=44,
                size=14).pack(side="left", padx=8)
        W.botao(topo, "Regenerar ícones", self._regenerar, icone="image", height=44,
                size=14).pack(side="left")
        self._contador = W.rotulo(topo, "", 13, cor=T.TXT_MUTED, anchor="e", width=160)
        self._contador.pack(side="right")
        self._aviso = W.rotulo(self, " ", 13, cor=T.TXT_MUTED, anchor="w")
        self._aviso.grid(row=1, column=0, sticky="ew", pady=(8, 4))
        self._lista = W.ListaRolavel(self)
        self._lista.grid(row=2, column=0, sticky="nsew")
        self._vazio = W.rotulo(self._lista, "Carregando setores…", 14, cor=T.TXT_MUTED)
        self._vazio.pack(pady=24)

    # ---- Carregamento ----------------------------------------------------
    def atualizar(self) -> None:
        if self._carregando:
            return
        self._carregando = True
        self.pronto.iniciar()
        cache = dict(self._pngs)
        tarefa.executar(lambda: _carregar(cache), self._mostrar, self._falha,
                        "setores-listar")

    def _falha(self, exc: Exception) -> None:
        self._carregando = False
        try:
            if _vivo(self):
                if self._qtd == 0:
                    W.configurar(self._vazio, text="Não foi possível carregar os setores.")
                self._status(svc.mensagem(exc), T.DANGER)
        finally:
            self.pronto.concluir()

    def _mostrar(self, r: tuple) -> None:
        self._carregando = False
        try:
            if _vivo(self):
                itens, self._pngs = r
                self._render(itens)
        finally:
            self.pronto.concluir()

    def _render(self, itens: list[dict]) -> None:
        assinatura = tuple(_chave(s) for s in itens)
        if assinatura == self._assinatura:
            return                                  # lista idêntica: nada a redesenhar
        self._assinatura = assinatura
        n = len(itens)
        while len(self._linhas) < n:
            self._linhas.append(LinhaSetor(self._lista, self._acoes, self._img_vazia))
        for i, (linha, s) in enumerate(zip(self._linhas, itens)):
            linha.mostrar(s, self._pngs.get((int(s["id"]), s["icone"])), i == 0, i == n - 1)
        if n:
            self._vazio.pack_forget()
        else:
            W.configurar(self._vazio, text="Nenhum setor cadastrado.")
            if not self._vazio.winfo_manager():
                self._vazio.pack(pady=24)
        if n != self._qtd:
            for i in range(self._qtd, n):
                self._linhas[i].pack(fill="x", pady=3, padx=2)
            for i in range(n, self._qtd):
                self._linhas[i].pack_forget()
            self._qtd = n
            self._lista.ajustar_barra()
        ativos = sum(1 for s in itens if s["ativo"])
        W.configurar(self._contador, text=f"{ativos} ativo(s) de {n}")

    def _status(self, texto: str, cor: str = T.TXT_MUTED) -> None:
        W.configurar(self._aviso, text=texto or " ", text_color=cor)

    def _ocupado(self) -> bool:
        return self._dialogo is not None and not self._dialogo.fechado

    # ---- Cadastro / edição -----------------------------------------------
    def _adicionar(self) -> None:
        if not self._ocupado():
            self._dialogo = FormSetor(self, {"cor": T.NEON}, self._cadastrar)

    def _cadastrar(self, dados: dict, form: FormSetor) -> None:
        tarefa.executar(lambda: svc.cadastrar(self._usuario, dados),
                        lambda _r: self._salvo(form, "Setor cadastrado."),
                        lambda e: form.erro(svc.mensagem(e)), "setores-cadastrar")

    def _editar(self, s: dict) -> None:
        if self._ocupado():
            return
        self._dialogo = FormSetor(
            self, s,
            lambda d, f: tarefa.executar(
                lambda: svc.editar(self._usuario, s["id"], d),
                lambda _r: self._salvo(f, "Setor atualizado."),
                lambda e: f.erro(svc.mensagem(e)), "setores-editar"),
            editar=True)

    def _salvo(self, form: FormSetor, texto: str) -> None:
        form.concluir()
        if _vivo(self):
            self._status(texto, T.NEON)
            self.atualizar()

    # ---- Ordem -----------------------------------------------------------
    def _mover(self, s: dict, passo: int) -> None:
        if self._ocupado() or self._movendo or self._carregando:
            return
        self._movendo = True

        def ok(_r):
            self._movendo = False
            if _vivo(self):
                self.atualizar()

        def falha(e):
            self._movendo = False
            if _vivo(self):
                self._status(svc.mensagem(e), T.DANGER)

        tarefa.executar(lambda: svc.mover(self._usuario, s["id"], passo), ok, falha,
                        "setores-ordem")

    # ---- Desativar / reativar --------------------------------------------
    def _alternar(self, s: dict) -> None:
        if self._ocupado():
            return
        ativar = not s["ativo"]

        def confirmar(c: Confirmacao):
            c.ocupado("Reativando…" if ativar else "Desativando…")
            tarefa.executar(lambda: svc.definir_ativo(self._usuario, s["id"], ativar),
                            lambda _r: self._concluido(
                                c, "Setor reativado." if ativar else "Setor desativado."),
                            lambda e: c.erro(svc.mensagem(e)), "setores-ativo")

        acao = "Reativar" if ativar else "Desativar"
        extra = "" if ativar else (
            "\nO Totem deixará de emitir senhas para ele"
            + (f"; as {s['pendentes']} pendentes continuam na fila." if s["pendentes"]
               else "."))
        self._dialogo = Confirmacao(self, f"{acao} setor", f"{acao} \"{s['nome']}\"?{extra}",
                                    ok=acao, perigo=not ativar, ao_confirmar=confirmar)

    # ---- Exclusão --------------------------------------------------------
    def _excluir(self, s: dict) -> None:
        if self._ocupado():
            return

        def confirmar(c: Confirmacao):
            c.ocupado("Excluindo…")
            tarefa.executar(lambda: svc.excluir(self._usuario, s["id"]),
                            lambda _r: self._concluido(c, "Setor excluído."),
                            lambda e: c.erro(svc.mensagem(e)), "setores-excluir")

        msg = (f"Excluir \"{s['nome']}\" definitivamente?\n"
               "Só é permitido para setor sem senhas emitidas; caso contrário, use Desativar.")
        self._dialogo = Confirmacao(self, "Excluir setor", msg, ok="Excluir",
                                    perigo=True, ao_confirmar=confirmar)

    # ---- Ícones ----------------------------------------------------------
    def _regenerar(self) -> None:
        if self._ocupado():
            return

        def confirmar(c: Confirmacao):
            c.ocupado("Gerando ícones…")
            tarefa.executar(lambda: svc.regenerar_icones(self._usuario),
                            lambda r: self._regenerado(c, r),
                            lambda e: c.erro(svc.mensagem(e)), "setores-icones-regerar")

        msg = ("Gerar novamente o PNG do ícone de todos os setores?\n"
               "Imagens enviadas por arquivo são mantidas.")
        self._dialogo = Confirmacao(self, "Regenerar ícones", msg, ok="Regenerar",
                                    ao_confirmar=confirmar)

    def _regenerado(self, c: Confirmacao, r: tuple) -> None:
        gerados, sem = r
        self._pngs = {}
        self._assinatura = None                     # PNGs novos: força redesenho
        for linha in self._linhas:
            linha._estado = None
        self._concluido(c, f"Ícones regenerados: {gerados} gerado(s), {sem} sem ícone.")

    def _concluido(self, c: Confirmacao, texto: str) -> None:
        c.fechar(forcar=True)
        if _vivo(self):
            self._status(texto, T.NEON)
            self.atualizar()
