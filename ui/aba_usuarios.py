"""
Aba "Usuários" (somente gestor): lista, cadastro, edição, desbloqueio, encerramento
de sessão, desativação/reativação e exclusão (só sem histórico).
Linhas reaproveitadas (pool). Ações sobre o próprio usuário ficam desabilitadas
(o service também recusa).
"""
import logging
from tkinter import TclError
from typing import Optional

import customtkinter as ctk

from services import usuarios_service as svc
from services.auth import Usuario
from ui import tarefa
from ui import theme as T
from ui import widgets as W
from ui.confirmacao import Confirmacao
from ui.form_usuario import FormUsuario
from ui.prontidao import Prontidao

log = logging.getLogger(__name__)


def _vivo(w) -> bool:
    try:
        return tarefa.ativo() and bool(w.winfo_exists())
    except TclError:
        return False


def _situacao(u: dict) -> tuple[str, str]:
    if not u["ativo"]:
        return "Inativo", T.TXT_MUTED
    if u["bloqueado"]:
        return "Bloqueado", T.DANGER
    if u["em_sessao"]:
        return "Em sessão", T.WARN
    return "Ativo", T.NEON


class LinhaUsuario(ctk.CTkFrame):
    def __init__(self, master, acoes: dict, meu_id: int, nomes_setores: dict):
        super().__init__(master, fg_color=T.BG_ITEM, corner_radius=12)
        self.grid_columnconfigure(0, weight=1)
        self._u: Optional[dict] = None
        self._meu_id = meu_id
        self._nomes = nomes_setores

        info = ctk.CTkFrame(self, fg_color="transparent")
        info.grid(row=0, column=0, sticky="ew", padx=14, pady=8)
        self._tit = W.rotulo(info, "", 15, "bold", anchor="w")
        self._tit.pack(anchor="w")
        self._sub = W.rotulo(info, "", 12, cor=T.TXT_MUTED, anchor="w")
        self._sub.pack(anchor="w")
        self._sit = W.rotulo(self, "", 13, "bold", width=90)
        self._sit.grid(row=0, column=1, padx=8)

        def bt(icone, acao, largura=40, texto=""):
            return W.botao(self, texto, lambda: self._u and acoes[acao](self._u),
                           icone=icone, height=36, size=12, width=largura)

        self._b_edit = bt("edit", "editar")
        self._b_edit.grid(row=0, column=2, padx=4)
        self._b_desb = bt("key", "desbloquear")
        self._b_desb.grid(row=0, column=3, padx=4)
        self._b_sessao = bt("x", "sessao")
        self._b_sessao.grid(row=0, column=4, padx=4)
        self._b_alt = bt("power", "alternar", 110)
        self._b_alt.grid(row=0, column=5, padx=4)
        self._b_exc = bt("trash", "excluir")
        self._b_exc.grid(row=0, column=6, padx=(4, 10))

    @staticmethod
    def _exibir(btn, on: bool) -> None:
        if on:
            btn.grid()
        else:
            btn.grid_remove()

    def mostrar(self, u: dict) -> None:
        self._u = u
        proprio = u["id"] == self._meu_id
        W.configurar(self._tit, text=u["nome"] + ("  (você)" if proprio else ""))
        setores = ", ".join(self._nomes.get(i, f"#{i}") for i in u["setores"]) \
            or "Todos os setores"
        perfil = "Gestor" if u["perfil"] == "gestor" else "Atendente"
        W.configurar(self._sub, text=f"{u['login']} • {perfil} • {setores}")
        texto, cor = _situacao(u)
        W.configurar(self._sit, text=texto, text_color=cor)
        self._exibir(self._b_desb, bool(u["bloqueado"]))
        self._exibir(self._b_sessao, bool(u["em_sessao"]) and not proprio)
        W.definir(self._b_alt, "Desativar" if u["ativo"] else "Reativar")
        W.habilitar(self._b_alt, not proprio)
        W.habilitar(self._b_exc, not proprio)


class AbaUsuarios(ctk.CTkFrame):
    def __init__(self, master, usuario: Usuario):
        super().__init__(master, fg_color="transparent")
        self._usuario = usuario
        self._linhas: list[LinhaUsuario] = []
        self._qtd = 0
        self._carregando = False
        self._setores: list[dict] = []
        self._nomes: dict[int, str] = {}
        self.pronto = Prontidao()
        self._dialogo = None
        self._acoes = {"editar": self._editar, "alternar": self._alternar,
                       "excluir": self._excluir, "desbloquear": self._desbloquear,
                       "sessao": self._encerrar_sessao}
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.grid(row=0, column=0, sticky="ew")
        W.botao(topo, "Novo usuário", self._adicionar, primario=True, icone="plus",
                height=44, size=14).pack(side="left")
        W.botao(topo, "Atualizar", self.atualizar, icone="refresh", height=44,
                size=14).pack(side="left", padx=8)
        self._contador = W.rotulo(topo, "", 13, cor=T.TXT_MUTED)
        self._contador.pack(side="right")
        self._aviso = W.rotulo(self, "", 13, cor=T.TXT_MUTED, anchor="w")
        self._aviso.grid(row=1, column=0, sticky="ew", pady=(8, 4))
        self._lista = W.ListaRolavel(self)
        self._lista.grid(row=2, column=0, sticky="nsew")
        self._vazio = W.rotulo(self._lista, "Carregando usuários…", 14, cor=T.TXT_MUTED)
        self._vazio.pack(pady=24)

    # ---- Carregamento ----------------------------------------------------
    def atualizar(self) -> None:
        if self._carregando:
            return
        self._carregando = True
        self.pronto.iniciar()
        tarefa.executar(lambda: (svc.listar(), svc.listar_setores()), self._mostrar,
                        self._falha, "usuarios-listar")

    def _falha(self, exc: Exception) -> None:
        self._carregando = False
        try:
            if _vivo(self):
                if self._qtd == 0:
                    W.configurar(self._vazio, text="Não foi possível carregar os usuários.")
                self._status(svc.mensagem(exc), T.DANGER)
        finally:
            self.pronto.concluir()

    def _mostrar(self, res: tuple) -> None:
        self._carregando = False
        try:
            if _vivo(self):
                itens, setores = res
                self._setores = list(setores)
                self._nomes.clear()
                self._nomes.update({int(s["id"]): s["nome"] for s in self._setores})
                self._render(itens)
        finally:
            self.pronto.concluir()

    def _render(self, itens: list[dict]) -> None:
        n = len(itens)
        while len(self._linhas) < n:
            self._linhas.append(LinhaUsuario(self._lista, self._acoes, self._usuario.id,
                                             self._nomes))
        for linha, u in zip(self._linhas, itens):
            linha.mostrar(u)
        if n:
            self._vazio.pack_forget()
        else:
            W.configurar(self._vazio, text="Nenhum usuário cadastrado.")
            self._vazio.pack(pady=24)
        if n != self._qtd:
            for i in range(self._qtd, n):
                self._linhas[i].pack(fill="x", pady=3, padx=2)
            for i in range(n, self._qtd):
                self._linhas[i].pack_forget()
            self._qtd = n
            self._lista.ajustar_barra()
        ativos = sum(1 for u in itens if u["ativo"])
        W.configurar(self._contador, text=f"{ativos} ativo(s) de {n}")

    def _status(self, texto: str, cor: str = T.TXT_MUTED) -> None:
        W.configurar(self._aviso, text=texto, text_color=cor)

    def _ocupado(self) -> bool:
        return self._dialogo is not None and not self._dialogo.fechado

    # ---- Cadastro / edição -----------------------------------------------
    def _adicionar(self) -> None:
        if self._ocupado():
            return
        self._dialogo = FormUsuario(
            self, {}, self._setores,
            lambda d, f: tarefa.executar(
                lambda: svc.cadastrar(self._usuario, d),
                lambda _r: self._salvo(f, "Usuário cadastrado."),
                lambda e: f.erro(svc.mensagem(e)), "usuarios-cadastrar"))

    def _editar(self, u: dict) -> None:
        if self._ocupado():
            return
        self._dialogo = FormUsuario(
            self, u, self._setores,
            lambda d, f: tarefa.executar(
                lambda: svc.editar(self._usuario, u["id"], d),
                lambda _r: self._salvo(f, "Usuário atualizado."),
                lambda e: f.erro(svc.mensagem(e)), "usuarios-editar"),
            editar=True)

    def _salvo(self, form: FormUsuario, texto: str) -> None:
        form.concluir()
        if _vivo(self):
            self._status(texto, T.NEON)
            self.atualizar()

    # ---- Ações com confirmação -------------------------------------------
    def _confirmar(self, titulo: str, msg: str, ok: str, perigo: bool, ocupado: str,
                   func, sucesso: str, nome: str) -> None:
        if self._ocupado():
            return

        def confirmar(c: Confirmacao):
            c.ocupado(ocupado)
            tarefa.executar(func, lambda _r: self._concluido(c, sucesso),
                            lambda e: c.erro(svc.mensagem(e)), nome)

        self._dialogo = Confirmacao(self, titulo, msg, ok=ok, perigo=perigo,
                                    ao_confirmar=confirmar)

    def _alternar(self, u: dict) -> None:
        ativar = not u["ativo"]
        acao = "Reativar" if ativar else "Desativar"
        msg = (f"{acao} \"{u['nome']}\"?" +
               ("" if ativar else "\nA sessão aberta será encerrada e as senhas em "
                                  "atendimento voltarão para a fila."))
        self._confirmar(f"{acao} usuário", msg, acao, not ativar,
                        "Reativando…" if ativar else "Desativando…",
                        lambda: svc.definir_ativo(self._usuario, u["id"], ativar),
                        "Usuário reativado." if ativar else "Usuário desativado.",
                        "usuarios-ativo")

    def _excluir(self, u: dict) -> None:
        msg = (f"Excluir \"{u['nome']}\" definitivamente?\n"
               "Só é permitido para usuário sem histórico; caso contrário, use Desativar.")
        self._confirmar("Excluir usuário", msg, "Excluir", True, "Excluindo…",
                        lambda: svc.excluir(self._usuario, u["id"]),
                        "Usuário excluído.", "usuarios-excluir")

    def _desbloquear(self, u: dict) -> None:
        self._confirmar("Desbloquear usuário", f"Liberar o login de \"{u['nome']}\" agora?",
                        "Desbloquear", False, "Desbloqueando…",
                        lambda: svc.desbloquear(self._usuario, u["id"]),
                        "Usuário desbloqueado.", "usuarios-desbloquear")

    def _encerrar_sessao(self, u: dict) -> None:
        msg = (f"Encerrar a sessão de \"{u['nome']}\"?\n"
               "As senhas em atendimento voltarão para a fila.")
        self._confirmar("Encerrar sessão", msg, "Encerrar", True, "Encerrando…",
                        lambda: svc.encerrar_sessao(self._usuario, u["id"]),
                        "Sessão encerrada.", "usuarios-sessao")

    def _concluido(self, c: Confirmacao, texto: str) -> None:
        c.fechar(forcar=True)
        if _vivo(self):
            self._status(texto, T.NEON)
            self.atualizar()
