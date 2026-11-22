"""Fábricas de widgets padronizados (evita repetição de estilo)."""
from typing import Callable, Optional

import customtkinter as ctk

from ui import theme as T
from ui.icones import icone as _icone

# Estilos de botão habilitado, por tipo; desabilitado é único (sem destaque)
_ESTILOS = {
    "primario": dict(fg_color=T.NEON, hover_color=T.NEON_DARK, border_color=T.NEON,
                     text_color=T.BG_APP),
    "perigo": dict(fg_color=T.BG_APP, hover_color=T.BG_CARD_HOV, border_color=T.DANGER,
                   text_color=T.DANGER),
    "normal": dict(fg_color=T.BG_APP, hover_color=T.BG_CARD_HOV, border_color=T.BORDER,
                   text_color=T.TXT),
}
_DESABILITADO = dict(fg_color=T.BG_OFF, border_color=T.BORDER_OFF)


def configurar(widget, **kw) -> None:
    """configure() só com o que mudou (anti-flicker; cache no próprio widget)."""
    cache = widget.__dict__.setdefault("_cfg_cache", {})
    novo = {k: v for k, v in kw.items() if cache.get(k, object()) != v}
    if novo:
        cache.update(novo)
        widget.configure(**novo)


def card(parent, **kw) -> ctk.CTkFrame:
    return ctk.CTkFrame(parent, fg_color=T.BG_CARD, corner_radius=24,
                        border_width=2, border_color=T.BORDER, **kw)


def rotulo(parent, texto: str = "", size: int = 14, weight: str = "normal",
           cor: str = T.TXT, **kw) -> ctk.CTkLabel:
    return ctk.CTkLabel(parent, text=texto, font=T.font(size, weight), text_color=cor, **kw)


def entrada(parent, placeholder: str = "", show: str = "", width: int = 360) -> ctk.CTkEntry:
    return ctk.CTkEntry(parent, placeholder_text=placeholder, show=show, height=44,
                        width=width, corner_radius=12, font=T.font(15), fg_color=T.BG_APP,
                        border_color=T.BORDER, border_width=2, text_color=T.TXT,
                        placeholder_text_color=T.TXT_MUTED)


# ---------------------------------------------------------------------
# Botões
# ---------------------------------------------------------------------
def botao(parent, texto: str, comando, primario: bool = False, perigo: bool = False,
          icone: Optional[str] = None, height: int = 54, size: int = 16,
          **kw) -> ctk.CTkButton:
    """Botão padronizado; use habilitar() para trocar o estado (aplica o visual)."""
    btn = ctk.CTkButton(parent, text=texto, command=comando, height=height,
                        corner_radius=T.RADIUS, font=T.font(size, "bold"), border_width=2,
                        text_color_disabled=T.TXT_OFF, compound="left", **kw)
    btn._tipo = "primario" if primario else ("perigo" if perigo else "normal")
    btn._icone = icone
    btn._icone_tam = size + 4
    btn._on = None
    habilitar(btn, True)
    return btn


def habilitar(btn: ctk.CTkButton, on: bool) -> None:
    """Estado + visual (CTk não altera cores sozinho ao desabilitar)."""
    if btn._on == on:
        return
    btn._on = on
    estilo = _ESTILOS[btn._tipo] if on else _DESABILITADO
    cor_icone = estilo.get("text_color", T.TXT_OFF)
    extra = {"image": _icone(btn._icone, btn._icone_tam, cor_icone)} if btn._icone else {}
    btn.configure(state="normal" if on else "disabled", **estilo, **extra)


def definir(btn: ctk.CTkButton, texto: Optional[str] = None,
            icone: Optional[str] = None) -> None:
    """Troca texto e/ou ícone mantendo o estado atual."""
    if texto is not None:
        btn.configure(text=texto)
    if icone is not None:
        btn._icone = icone
        on = True if btn._on is None else btn._on
        btn._on = None
        habilitar(btn, on)


def opcoes(parent, valores: list[str], comando=None, width: int = 360) -> ctk.CTkOptionMenu:
    return ctk.CTkOptionMenu(
        parent, values=valores or ["—"], command=comando, height=44, width=width,
        corner_radius=12, font=T.font(15), fg_color=T.BG_APP, button_color=T.BORDER,
        button_hover_color=T.NEON_DARK, dropdown_fg_color=T.BG_CARD,
        dropdown_hover_color=T.BG_CARD_HOV, text_color=T.TXT,
        text_color_disabled=T.TXT_OFF, dynamic_resizing=False,
    )


# ---------------------------------------------------------------------
# Lista com rolagem (barra sempre no layout; só "some" quando desnecessária,
# sem alterar a largura do conteúdo)
# ---------------------------------------------------------------------
class ListaRolavel(ctk.CTkScrollableFrame):
    def __init__(self, master, **kw):
        super().__init__(master, fg_color="transparent", scrollbar_button_color=T.BORDER,
                         scrollbar_button_hover_color=T.NEON_DARK, **kw)
        self._visivel: Optional[bool] = None
        self._job: Optional[str] = None
        self._parent_canvas.bind("<Configure>", lambda _e: self.ajustar_barra(), add="+")
        self.bind("<Configure>", lambda _e: self.ajustar_barra(), add="+")
        self.ajustar_barra()

    def ajustar_barra(self) -> None:
        if not self._job:
            self._job = self.after_idle(self._ajustar)

    def _ajustar(self) -> None:
        self._job = None
        canvas = self._parent_canvas
        caixa = canvas.bbox("all")
        conteudo = (caixa[3] - caixa[1]) if caixa else 0
        precisa = conteudo > canvas.winfo_height() + 1
        if precisa == self._visivel:
            return
        self._visivel = precisa
        if precisa:
            self._scrollbar.configure(button_color=T.BORDER, button_hover_color=T.NEON_DARK)
        else:
            self._scrollbar.configure(button_color=T.BG_CARD, button_hover_color=T.BG_CARD)
            canvas.yview_moveto(0)


class LinhaSenha(ctk.CTkFrame):
    """Linha reaproveitável da lista: só o conteúdo muda (sem destroy)."""

    def __init__(self, master, reativar_cb: Optional[Callable[[int], None]] = None):
        super().__init__(master, fg_color=T.BG_ITEM, corner_radius=12)
        self.grid_columnconfigure(2, weight=1)
        self._sid: Optional[int] = None
        self._reativar = reativar_cb is not None
        self._barra = ctk.CTkFrame(self, width=6, height=34, corner_radius=3, fg_color=T.NEON)
        self._barra.grid(row=0, column=0, padx=(10, 10), pady=8)
        self._num = rotulo(self, "", 18, "bold", T.TXT, width=90, anchor="w")
        self._num.grid(row=0, column=1, sticky="w")
        self._info = rotulo(self, "", 12, cor=T.TXT_MUTED, anchor="w")
        self._info.grid(row=0, column=2, sticky="ew", padx=6)
        if reativar_cb:
            self._dir = botao(self, "Reativar",
                              lambda: self._sid is not None and reativar_cb(self._sid),
                              icone="undo", height=32, size=12, width=110)
            self._dir.grid(row=0, column=3, padx=8)
        else:
            self._dir = rotulo(self, "", 13, "bold", T.TXT_MUTED, width=64, anchor="e")
            self._dir.grid(row=0, column=3, padx=12)

    def mostrar(self, s: dict) -> None:
        self._sid = int(s["id"])
        configurar(self._barra, fg_color=T.cor_segura(s.get("cor")))
        configurar(self._num, text=s["numero"],
                   text_color=T.NEON if s.get("prioritaria") else T.TXT)
        configurar(self._info, text=f"{s['setor']} • {s['prioridade']}")
        if not self._reativar:
            configurar(self._dir, text=f"{s['espera_min']} min")


class ListaSenhas(ListaRolavel):
    """Lista com pool de linhas: atualiza textos no lugar; pack só quando a quantidade muda."""

    def __init__(self, master, max_itens: int,
                 reativar_cb: Optional[Callable[[int], None]] = None, **kw):
        super().__init__(master, **kw)
        self._max = max_itens
        self._cb = reativar_cb
        self._linhas: list[LinhaSenha] = []
        self._qtd = 0
        self._vazio = rotulo(self, "Nenhuma senha.", 14, cor=T.TXT_MUTED)
        self._mais = rotulo(self, "", 13, cor=T.TXT_MUTED)
        self._vazio_on: Optional[bool] = None
        self._mais_on = False

    def mostrar(self, itens: list[dict]) -> None:
        vis = itens[:self._max]
        n = len(vis)
        mudou = False

        vazio = n == 0
        if vazio != self._vazio_on:
            self._vazio_on = vazio
            if vazio:
                self._vazio.pack(pady=16)
            else:
                self._vazio.pack_forget()
            mudou = True

        while len(self._linhas) < n:
            self._linhas.append(LinhaSenha(self, self._cb))
        for linha, s in zip(self._linhas, vis):
            linha.mostrar(s)

        if n != self._qtd:
            if n > self._qtd and self._mais_on:
                self._mais.pack_forget()
                self._mais_on = False
            for i in range(self._qtd, n):
                self._linhas[i].pack(fill="x", pady=3, padx=2)
            for i in range(n, self._qtd):
                self._linhas[i].pack_forget()
            self._qtd = n
            mudou = True

        resto = len(itens) - n
        if resto > 0:
            configurar(self._mais, text=f"... e mais {resto}")
            if not self._mais_on:
                self._mais.pack(pady=8)
                self._mais_on = True
                mudou = True
        elif self._mais_on:
            self._mais.pack_forget()
            self._mais_on = False
            mudou = True

        if mudou:
            self.ajustar_barra()


class CampoSenha(ctk.CTkFrame):
    """Entry mascarada + botão mostrar/ocultar."""

    def __init__(self, master, placeholder: str = "", width: int = 360):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        self.entry = entrada(self, placeholder, show="•", width=width - 52)
        self.entry.grid(row=0, column=0, sticky="ew")
        self._olho = ctk.CTkButton(
            self, text="👁", width=44, height=44, corner_radius=12, font=T.font(16),
            fg_color=T.BG_APP, hover_color=T.BG_CARD_HOV, border_width=1,
            border_color=T.BORDER, text_color=T.TXT, command=self.alternar)
        self._olho.grid(row=0, column=1, padx=(8, 0))

    def alternar(self) -> None:
        oculto = self.entry.cget("show") == "•"
        self.entry.configure(show="" if oculto else "•")
        self._olho.configure(text="🙈" if oculto else "👁")

    def get(self) -> str:
        return self.entry.get()

    def limpar(self, placeholder: str | None = None) -> None:
        self.entry.delete(0, "end")
        self.entry.configure(show="•")
        self._olho.configure(text="👁")
        if placeholder is not None:
            self.entry.configure(placeholder_text=placeholder)

    def bind_enter(self, func) -> None:
        self.entry.bind("<Return>", lambda _e: func())
