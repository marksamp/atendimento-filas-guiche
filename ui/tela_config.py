"""
Tela de conexão com o banco (Guichê).
- Validação local + teste real; nunca salva configuração que não conecta.
- Senha mascarada; ao editar, "em branco = manter a senha atual".
- Anti-flicker: rótulos com dimensões fixas; só reconfigura o que mudou.
"""
from typing import Callable, Optional

import customtkinter as ctk

from config import TIPOS_BANCO, DBSettings
from database import ErroConexao, descrever_erro, testar_conexao
from services import config_store
from ui import theme as T
from ui import widgets as W

LARGURA_CAMPO = 360
LARGURA_UTIL = 760
ATRASO_STATUS_MS = 150


class TelaConfig(ctk.CTkFrame):
    def __init__(self, master, executar_bg: Callable,
                 on_salvo: Callable[[DBSettings], None], on_cancelar: Callable[[], None]):
        super().__init__(master, fg_color="transparent")
        self._bg = executar_bg
        self._on_salvo = on_salvo
        self._senha_atual: Optional[str] = None
        self._entradas: dict[str, ctk.CTkEntry] = {}
        self._erros: dict[str, ctk.CTkLabel] = {}
        self._texto_erro: dict[str, str] = {}
        self._borda: dict[str, str] = {}
        self._status_atual = ("", "")
        self._travado: Optional[bool] = None
        self._cancel_visivel: Optional[bool] = None
        self._job: Optional[str] = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        card = W.card(self)
        card.grid(row=0, column=0, padx=20, pady=10)
        card.grid_columnconfigure((0, 1), weight=1, uniform="c", minsize=LARGURA_CAMPO + 40)

        W.rotulo(card, "⚙  CONEXÃO COM O BANCO DE DADOS", 20, "bold", T.NEON).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=32, pady=(28, 2))
        self.lbl_aviso = W.rotulo(card, "", 14, cor=T.TXT_MUTED, wraplength=LARGURA_UTIL,
                                  justify="left", anchor="w", width=LARGURA_UTIL, height=40)
        self.lbl_aviso.grid(row=1, column=0, columnspan=2, sticky="w", padx=32, pady=(0, 10))

        b = self._bloco(card, 2, 0, "tipo", "Tipo de banco")
        self.opt_tipo = W.opcoes(b, list(TIPOS_BANCO), self._ao_trocar_tipo, LARGURA_CAMPO)
        self.opt_tipo.grid(row=1, column=0, sticky="ew")
        self._entrada(card, 2, 1, "host", "Host / IP", "ex.: 192.168.0.10")
        self._entrada(card, 3, 0, "port", "Porta", "3306")
        self._entrada(card, 3, 1, "database", "Nome do banco", "sistema_filas")
        self._entrada(card, 4, 0, "user", "Usuário", "filas_app")
        b = self._bloco(card, 4, 1, "password", "Senha")
        self.senha = W.CampoSenha(b, width=LARGURA_CAMPO)
        self.senha.grid(row=1, column=0, sticky="ew")
        self._entradas["password"] = self.senha.entry
        self._borda["password"] = T.BORDER

        self.lbl_status = W.rotulo(card, "", 15, "bold", T.TXT_MUTED, wraplength=LARGURA_UTIL,
                                   width=LARGURA_UTIL, height=48)
        self.lbl_status.grid(row=5, column=0, columnspan=2, padx=32, pady=(6, 2))

        botoes = ctk.CTkFrame(card, fg_color="transparent")
        botoes.grid(row=6, column=0, columnspan=2, sticky="ew", padx=32, pady=(6, 28))
        botoes.grid_columnconfigure((0, 1, 2), weight=1, uniform="b")
        self.btn_cancelar = W.botao(botoes, "Cancelar", on_cancelar)
        self.btn_cancelar.grid(row=0, column=0, sticky="ew", padx=6)
        self._cancel_visivel = True
        self.btn_testar = W.botao(botoes, "Testar conexão", self._testar)
        self.btn_testar.grid(row=0, column=1, sticky="ew", padx=6)
        self.btn_salvar = W.botao(botoes, "Salvar e conectar", self._salvar, primario=True)
        self.btn_salvar.grid(row=0, column=2, sticky="ew", padx=6)

    # ---- Construção --------------------------------------------------
    def _bloco(self, parent, row, col, chave, rotulo) -> ctk.CTkFrame:
        b = ctk.CTkFrame(parent, fg_color="transparent")
        b.grid(row=row, column=col, sticky="ew",
               padx=(32 if col == 0 else 10, 32 if col == 1 else 10), pady=2)
        b.grid_columnconfigure(0, weight=1)
        W.rotulo(b, rotulo, 14, "bold").grid(row=0, column=0, sticky="w", pady=(0, 4))
        err = W.rotulo(b, "", 12, cor=T.DANGER, width=LARGURA_CAMPO, height=34, anchor="nw",
                       justify="left", wraplength=LARGURA_CAMPO)
        err.grid(row=2, column=0, sticky="w")
        self._erros[chave] = err
        self._texto_erro[chave] = ""
        return b

    def _entrada(self, parent, row, col, chave, rotulo, placeholder):
        b = self._bloco(parent, row, col, chave, rotulo)
        ent = W.entrada(b, placeholder, width=LARGURA_CAMPO)
        ent.grid(row=1, column=0, sticky="ew")
        self._entradas[chave] = ent
        self._borda[chave] = T.BORDER

    # ---- API ---------------------------------------------------------
    def preencher(self, settings: Optional[DBSettings], completo: bool,
                  cancelavel: bool, aviso: str = "") -> None:
        s = settings or DBSettings()
        self.opt_tipo.set(s.tipo if s.tipo in TIPOS_BANCO else next(iter(TIPOS_BANCO)))
        for chave, valor in (("host", s.host), ("port", str(s.port)),
                             ("database", s.database), ("user", s.user)):
            ent = self._entradas[chave]
            ent.delete(0, "end")
            if valor:
                ent.insert(0, valor)
        self._senha_atual = s.password if (settings and completo) else None
        self.senha.limpar("Em branco = manter a senha atual"
                          if self._senha_atual is not None else "")
        self.lbl_aviso.configure(text=aviso or "Informe os dados de acesso ao servidor do banco.")
        self._aplicar_erros({})
        self._cancelar_job()
        self._status("")
        self._mostrar_cancelar(cancelavel)
        self._travar(False)

    # ---- Leitura e validação ----------------------------------------
    def _ler(self) -> tuple[DBSettings, dict[str, str]]:
        erros: dict[str, str] = {}
        try:
            porta = int(self._entradas["port"].get().strip())
        except ValueError:
            porta = 0
            erros["port"] = "Porta deve ser numérica."
        senha = self.senha.get() or (self._senha_atual or "")
        s = DBSettings(tipo=self.opt_tipo.get(), host=self._entradas["host"].get().strip(),
                       port=porta, database=self._entradas["database"].get().strip(),
                       user=self._entradas["user"].get().strip(), password=senha)
        for k, v in s.validar().items():
            erros.setdefault(k, v)
        return s, erros

    def _aplicar_erros(self, erros: dict[str, str]) -> None:
        for chave, lbl in self._erros.items():
            texto = erros.get(chave, "")
            if self._texto_erro[chave] != texto:
                self._texto_erro[chave] = texto
                lbl.configure(text=texto)
        for chave, ent in self._entradas.items():
            cor = T.DANGER if chave in erros else T.BORDER
            if self._borda[chave] != cor:
                self._borda[chave] = cor
                ent.configure(border_color=cor)

    # ---- Ações -------------------------------------------------------
    def _validado(self) -> Optional[DBSettings]:
        s, erros = self._ler()
        self._aplicar_erros(erros)
        if erros:
            self._status("Corrija os campos destacados.", T.DANGER)
            return None
        return s

    def _testar(self):
        s = self._validado()
        if s:
            self._executar(lambda: testar_conexao(s), s,
                           lambda _r: self._status("✔ Conexão bem-sucedida.", T.NEON))

    def _salvar(self):
        s = self._validado()
        if not s:
            return

        def tarefa():
            testar_conexao(s)
            config_store.salvar(s)
            return s

        def ok(settings):
            self.senha.limpar()
            self._status("✔ Configuração salva.", T.NEON)
            self._on_salvo(settings)

        self._executar(tarefa, s, ok)

    def _executar(self, func, s: DBSettings, ok):
        if self._travado:
            return
        self._travar(True)
        self._cancelar_job()
        self._job = self.after(ATRASO_STATUS_MS,
                               lambda: self._status("Testando conexão...", T.TXT_MUTED))

        def sucesso(res):
            self._cancelar_job()
            self._travar(False)
            ok(res)

        def falha(exc):
            self._cancelar_job()
            self._travar(False)
            if isinstance(exc, ErroConexao):
                msg = str(exc)
            elif isinstance(exc, OSError):
                msg = "Conexão OK, mas não foi possível gravar a configuração neste computador."
            else:
                msg = descrever_erro(exc, s)
            self._status(f"✖ {msg}", T.DANGER)

        self._bg(func, sucesso, falha)

    # ---- Utilidades --------------------------------------------------
    def _cancelar_job(self):
        if self._job:
            self.after_cancel(self._job)
            self._job = None

    def _ao_trocar_tipo(self, tipo: str):
        ent = self._entradas["port"]
        if not ent.get().strip():
            ent.insert(0, str(TIPOS_BANCO[tipo]))

    def _status(self, texto: str, cor: str = T.TXT_MUTED):
        if self._status_atual != (texto, cor):
            self._status_atual = (texto, cor)
            self.lbl_status.configure(text=texto, text_color=cor)

    def _mostrar_cancelar(self, visivel: bool):
        if self._cancel_visivel != visivel:
            self._cancel_visivel = visivel
            self.btn_cancelar.grid() if visivel else self.btn_cancelar.grid_remove()

    def _travar(self, travado: bool):
        if self._travado == travado:
            return
        self._travado = travado
        estado = "disabled" if travado else "normal"
        for btn in (self.btn_testar, self.btn_salvar, self.btn_cancelar):
            btn.configure(state=estado)
        self.configure(cursor="watch" if travado else "")
