"""
Formulário de usuário (cadastro/edição) em sobreposição, no padrão de FormGuiche.
- Login, nome, perfil, senha/confirmação (na edição: em branco = mantém) e setores.
- Nenhum setor marcado = atende todos os setores ativos.
- "Selecionar todos" sincronizado com as marcações individuais.
- Validação local instantânea (usuarios_service.validar); erro fica no formulário.
- Salvar trava o formulário; erro destrava; sucesso fecha.
"""
from typing import Callable

import customtkinter as ctk

from services import usuarios_service as svc
from ui import theme as T
from ui import widgets as W
from ui.sobreposicao import Sobreposicao

_LARG = 300
_PERFIS = {"Atendente": "atendente", "Gestor": "gestor"}
_SUB = "Sem setores marcados, o usuário atende todos os setores ativos."


def _checkbox(pai, texto: str, comando, size: int = 13) -> ctk.CTkCheckBox:
    return ctk.CTkCheckBox(pai, text=texto, command=comando, font=T.font(size),
                           text_color=T.TXT, fg_color=T.NEON, hover_color=T.NEON_DARK,
                           border_color=T.BORDER, checkmark_color=T.BG_APP)


class FormUsuario(Sobreposicao):
    def __init__(self, master, valores: dict, setores: list[dict],
                 ao_salvar: Callable[[dict, "FormUsuario"], None], editar: bool = False):
        super().__init__(master, "Editar usuário" if editar else "Novo usuário", _SUB)
        self._cb = ao_salvar
        self._editar = editar
        self._login_atual = valores.get("login") or ""
        self._checks: list[tuple[int, ctk.CTkCheckBox]] = []

        c = self.corpo
        c.grid_columnconfigure((0, 1), weight=1)
        esq = ctk.CTkFrame(c, fg_color="transparent")
        esq.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        dir_ = ctk.CTkFrame(c, fg_color="transparent")
        dir_.grid(row=0, column=1, sticky="nsew", padx=(12, 0))

        self._f_login = self._campo(esq, "Login", W.entrada(esq, "6 a 40 letras/números",
                                                            width=_LARG))
        self._f_login.insert(0, self._login_atual)
        self._f_nome = self._campo(esq, "Nome completo",
                                   W.entrada(esq, "Nome e sobrenome", width=_LARG))
        self._f_nome.insert(0, valores.get("nome") or "")
        self._f_perfil = self._campo(esq, "Perfil", W.opcoes(esq, list(_PERFIS), width=_LARG))
        self._f_perfil.set("Gestor" if valores.get("perfil") == "gestor" else "Atendente")

        dica = "Em branco = mantém a atual" if editar else "Senha inicial"
        self._f_senha = self._campo(dir_, "Senha", W.CampoSenha(dir_, dica, width=_LARG))
        self._f_conf = self._campo(dir_, "Confirmação",
                                   W.CampoSenha(dir_, "Repita a senha", width=_LARG))

        cab = ctk.CTkFrame(c, fg_color="transparent")
        cab.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 4))
        W.rotulo(cab, "Setores atendidos", 14, "bold").pack(side="left")
        self._todos = _checkbox(cab, "Selecionar todos", self._alternar_todos)
        self._todos.pack(side="right")

        lista = W.ListaRolavel(c, height=120)
        lista.grid(row=2, column=0, columnspan=2, sticky="ew")
        marcados = set(valores.get("setores") or [])
        for i, s in enumerate(setores):
            cb = _checkbox(lista, s["nome"], self._sincronizar)
            cb.grid(row=i // 3, column=i % 3, sticky="w", padx=6, pady=4)
            if int(s["id"]) in marcados:
                cb.select()
            self._checks.append((int(s["id"]), cb))
        if not setores:
            W.rotulo(lista, "Nenhum setor ativo.", 13, cor=T.TXT_MUTED).grid(row=0, column=0)
            self._todos.configure(state="disabled")
        self._sincronizar()

        self.rodape_padrao("Salvar", self._salvar, _LARG * 2 + 24)
        self.exibir(foco=self._f_login)

    @staticmethod
    def _campo(pai, titulo: str, widget):
        W.rotulo(pai, titulo, 14, "bold").pack(anchor="w", pady=(8, 4))
        widget.pack(fill="x")
        return widget

    # ---- Setores ---------------------------------------------------------
    def _alternar_todos(self) -> None:
        marcar = bool(self._todos.get())
        for _sid, cb in self._checks:
            cb.select() if marcar else cb.deselect()

    def _sincronizar(self) -> None:
        todos = bool(self._checks) and all(cb.get() for _sid, cb in self._checks)
        self._todos.select() if todos else self._todos.deselect()

    # ---- Salvar ----------------------------------------------------------
    def _dados(self) -> dict:
        return {
            "login": self._f_login.get(),
            "nome": self._f_nome.get(),
            "perfil": _PERFIS.get(self._f_perfil.get(), ""),
            "senha": self._f_senha.get(),
            "confirmacao": self._f_conf.get(),
            "setores": [sid for sid, cb in self._checks if cb.get()],
        }

    def _salvar(self) -> None:
        if self.travado or self.fechado:
            return
        d = self._dados()
        erros = svc.validar(d, self._editar, self._login_atual)
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
