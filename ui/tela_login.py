"""
Login do atendente + seleção do guichê (lembra o último usado nesta máquina).
Prontidão: preparar() conta a carga dos guichês; quando_pronto() libera após ok OU erro.
"Configurar banco de dados" começa oculto; CTRL (sozinho) alterna exibir/ocultar.
- A alternância ocorre ao soltar o CTRL, e só se nenhuma outra tecla foi usada junto
  (Ctrl+V, Ctrl+A etc. não alternam); a repetição automática da tecla é ignorada.
- O estado escolhido permanece até o próximo CTRL; preparar()/login voltam a ocultar.
"""
from tkinter import TclError
from typing import Callable, Optional

import customtkinter as ctk

from database import descrever_erro
from services import auth, config_store, sessao
from services.auth import ErroLogin, Usuario
from ui import theme as T
from ui import widgets as W
from ui.prontidao import Prontidao

LARGURA = 380
_ALTURA_CONFIG = 36
_TECLAS_CTRL = ("Control_L", "Control_R")


class TelaLogin(ctk.CTkFrame):
    def __init__(self, master, executar_bg: Callable,
                 on_login: Callable[[Usuario, int], None], on_config: Callable[[], None]):
        super().__init__(master, fg_color="transparent")
        self._bg = executar_bg
        self._on_login = on_login
        self._on_config = on_config
        self._guiches: dict[str, int] = {}
        self._travado: Optional[bool] = None
        self._config_visivel = False
        self._ctrl_sozinho = False
        self._pronto = Prontidao()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        c = W.card(self)
        c.grid(row=0, column=0)
        c.grid_columnconfigure(0, weight=1)
        px = 40

        W.rotulo(c, "◉  GUICHÊ DE ATENDIMENTO", 22, "bold", T.NEON).grid(
            row=0, sticky="w", padx=px, pady=(36, 2))
        W.rotulo(c, "Entre com seu usuário para iniciar.", 14, cor=T.TXT_MUTED).grid(
            row=1, sticky="w", padx=px, pady=(0, 18))

        W.rotulo(c, "Usuário", 14, "bold").grid(row=2, sticky="w", padx=px)
        self.ent_login = W.entrada(c, "seu.login", width=LARGURA)
        self.ent_login.grid(row=3, sticky="ew", padx=px, pady=(4, 12))

        W.rotulo(c, "Senha", 14, "bold").grid(row=4, sticky="w", padx=px)
        self.senha = W.CampoSenha(c, width=LARGURA)
        self.senha.grid(row=5, sticky="ew", padx=px, pady=(4, 12))

        W.rotulo(c, "Guichê", 14, "bold").grid(row=6, sticky="w", padx=px)
        self.opt_guiche = W.opcoes(c, ["Carregando..."], width=LARGURA)
        self.opt_guiche.grid(row=7, sticky="ew", padx=px, pady=(4, 8))

        self.lbl_status = W.rotulo(c, "", 14, "bold", T.TXT_MUTED, width=LARGURA, height=44,
                                   wraplength=LARGURA)
        self.lbl_status.grid(row=8, padx=px)

        self.btn_entrar = W.botao(c, "Entrar", self._entrar, primario=True, width=LARGURA)
        self.btn_entrar.grid(row=9, sticky="ew", padx=px, pady=(4, 8))

        # Espaço fixo: o card não muda de tamanho ao mostrar/ocultar o botão
        self._slot_config = ctk.CTkFrame(c, fg_color="transparent", width=LARGURA,
                                         height=_ALTURA_CONFIG)
        self._slot_config.grid(row=10, padx=px, pady=(0, 28))
        self._slot_config.pack_propagate(False)
        self.btn_config = ctk.CTkButton(
            self._slot_config, text="⚙  Configurar banco de dados", height=_ALTURA_CONFIG,
            fg_color="transparent", hover_color=T.BG_CARD_HOV, text_color=T.TXT_MUTED,
            font=T.font(13), command=self._abrir_config)

        self.ent_login.bind("<Return>", lambda _e: self.senha.entry.focus_set())
        self.senha.bind_enter(self._entrar)
        self._ligar_atalho_config()

    # ---- API ---------------------------------------------------------
    def quando_pronto(self, cb: Callable[[], None]) -> None:
        self._pronto.quando(cb)

    def aguardando(self, texto: str) -> None:
        self._status(texto, T.TXT_MUTED)
        self._travar(True)

    def preparar(self, msg: str = "", cor: str = T.TXT_MUTED) -> None:
        self.senha.limpar()
        self._mostrar_config(False)
        self._status(msg, cor)
        self._travar(True)
        self._pronto.iniciar()
        self._bg(sessao.listar_guiches, self._ao_guiches, self._ao_falha_guiches)

    # ---- Atalho CTRL (alterna o botão de configuração) ---------------
    def _ligar_atalho_config(self) -> None:
        topo = self.winfo_toplevel()
        topo.bind("<KeyPress>", self._ao_tecla, add="+")
        for tecla in _TECLAS_CTRL:
            topo.bind(f"<KeyRelease-{tecla}>", self._ao_soltar_ctrl, add="+")
        # Soltar CTRL fora da janela (ex.: Alt+Tab) não gera KeyRelease aqui
        topo.bind("<FocusOut>", lambda _e: self._cancelar_ctrl(), add="+")

    def _ao_tecla(self, evento) -> None:
        if evento.keysym in _TECLAS_CTRL:
            if not self._ctrl_sozinho:          # repetição automática não reinicia
                self._ctrl_sozinho = True
        else:
            self._ctrl_sozinho = False          # combinação (Ctrl+V etc.): não alterna

    def _ao_soltar_ctrl(self, _evento) -> None:
        if self._ctrl_sozinho:
            self._ctrl_sozinho = False
            self._mostrar_config(not self._config_visivel)

    def _cancelar_ctrl(self) -> None:
        self._ctrl_sozinho = False

    def _mostrar_config(self, visivel: bool) -> None:
        try:
            if not self.winfo_exists():
                return
            if visivel and not self.winfo_ismapped():
                return
        except TclError:
            return
        if visivel == self._config_visivel:
            return
        self._config_visivel = visivel
        if visivel:
            self.btn_config.pack(fill="both", expand=True)
        else:
            self.btn_config.pack_forget()

    # ---- Internos ----------------------------------------------------
    def _ao_guiches(self, lista: list[dict]) -> None:
        try:
            self._aplicar_guiches(lista)
        finally:
            self._pronto.concluir()

    def _aplicar_guiches(self, lista: list[dict]) -> None:
        self._guiches = {g["nome"]: int(g["id"]) for g in lista}
        self._travar(False)
        if not self._guiches:
            self.opt_guiche.configure(values=["—"])
            self.opt_guiche.set("—")
            self._status("Nenhum guichê ativo cadastrado. Procure o gestor.", T.WARN)
            return
        nomes = list(self._guiches)
        self.opt_guiche.configure(values=nomes)
        ultimo = config_store.ler_preferencia("guiche_id")
        self.opt_guiche.set(next((n for n, i in self._guiches.items() if i == ultimo), nomes[0]))
        (self.ent_login if not self.ent_login.get() else self.senha.entry).focus_set()

    def _ao_falha_guiches(self, exc) -> None:
        try:
            self._travar(False)
            self.opt_guiche.configure(values=["—"])
            self.opt_guiche.set("—")
            self._status(f"✖ {descrever_erro(exc)}", T.DANGER)
        finally:
            self._pronto.concluir()

    def _entrar(self) -> None:
        if self._travado:
            return
        gid = self._guiches.get(self.opt_guiche.get())
        if gid is None:
            self._status("Selecione um guichê.", T.DANGER)
            return
        login, senha = self.ent_login.get(), self.senha.get()
        self._travar(True)
        self._status("Verificando...", T.TXT_MUTED)

        def ok(usuario: Usuario):
            try:
                config_store.gravar_preferencia("guiche_id", gid)
            except OSError:
                pass
            self._status("")
            self._mostrar_config(False)
            self._on_login(usuario, gid)

        def falha(exc):
            self._travar(False)
            self.senha.limpar()
            self.senha.entry.focus_set()
            msg = str(exc) if isinstance(exc, ErroLogin) else descrever_erro(exc)
            self._status(f"✖ {msg}", T.DANGER)

        self._bg(lambda: auth.autenticar(login, senha), ok, falha)

    def _abrir_config(self) -> None:
        if not self._travado:
            self._mostrar_config(False)
            self._on_config()

    def _status(self, texto: str, cor: str = T.TXT_MUTED) -> None:
        self.lbl_status.configure(text=texto, text_color=cor)

    def _travar(self, travado: bool) -> None:
        if self._travado == travado:
            return
        self._travado = travado
        estado = "disabled" if travado else "normal"
        for w in (self.btn_entrar, self.btn_config, self.opt_guiche):
            w.configure(state=estado)
