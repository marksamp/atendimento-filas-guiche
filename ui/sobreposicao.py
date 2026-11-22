"""
Diálogo em sobreposição dentro da janela principal, no padrão da tela de login.
Não usa CTkToplevel. Cobre a janela inteira (bloqueia os cliques atrás), centraliza
o card e fecha com Esc (só a do topo e se não travada).
Sem flash: é montada por baixo da tela atual e só sobe já desenhada.
Loading ativo (reter(True)): não sobe; o App chama reerguer() quando o loading sai.
Anti-flicker: NÃO é alternado ao abrir (isso repinta a janela toda); só
suspender_buffer() para animações contínuas (ex.: barras de envio).
Anti-balanço: status com altura fixa (1 ou 2 linhas não mudam o card); o conteúdo
variável dos formulários também tem tamanho fixo, então o card não recentraliza.
"""
from tkinter import TclError
from typing import Callable, Optional

import customtkinter as ctk

from ui import anti_flicker
from ui import theme as T
from ui import widgets as W

PX = 40
_MONTAGEM_MS = 40
_ALT_STATUS = 44
_pilha: list["Sobreposicao"] = []
_retido = False


def _ao_esc(_e=None) -> None:
    if _pilha:
        _pilha[-1].esc()


def aberta() -> bool:
    return bool(_pilha)


def reter(on: bool) -> None:
    """Enquanto o loading cobre a janela, nenhuma sobreposição sobe."""
    global _retido
    _retido = on


def reerguer() -> None:
    """Mantém as sobreposições acima após uma troca de tela."""
    for s in _pilha:
        try:
            s.lift()
        except TclError:
            pass


class Sobreposicao(ctk.CTkFrame):
    def __init__(self, master, titulo: str, subtitulo: str = "", cor: str = T.NEON):
        raiz = master.winfo_toplevel()
        super().__init__(raiz, fg_color=T.BG_APP, corner_radius=0)
        self._raiz = raiz
        self.fechado = False
        self.travado = False
        self._suspenso = False
        self._ao_fechar: list[Callable[[], None]] = []
        self.btn_ok: Optional[ctk.CTkButton] = None
        self.btn_cancelar: Optional[ctk.CTkButton] = None
        self.lbl_status: Optional[ctk.CTkLabel] = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.card = W.card(self)
        self.card.grid(row=0, column=0)
        self.card.grid_columnconfigure(0, weight=1)
        W.rotulo(self.card, f"◉  {titulo.upper()}", 22, "bold", cor).grid(
            row=0, sticky="w", padx=PX, pady=(36, 2))
        self.lbl_sub = W.rotulo(self.card, subtitulo, 14, cor=T.TXT_MUTED, anchor="w",
                                justify="left")
        if subtitulo:
            self.lbl_sub.grid(row=1, sticky="w", padx=PX, pady=(0, 18))
        self.corpo = ctk.CTkFrame(self.card, fg_color="transparent")
        self.corpo.grid(row=2, sticky="ew", padx=PX)
        self._rodape = ctk.CTkFrame(self.card, fg_color="transparent")
        self._rodape.grid(row=3, sticky="ew", padx=PX, pady=(0, 28))

    # ---- Montagem ------------------------------------------------------------
    def rodape_padrao(self, ok: str, comando: Callable[[], None], largura: int,
                      perigo: bool = False, cancelar: Optional[str] = "Cancelar") -> None:
        """Status (altura fixa) + botão principal largo + link discreto (igual ao login)."""
        self.lbl_sub.configure(wraplength=largura)
        caixa = ctk.CTkFrame(self._rodape, fg_color="transparent", width=largura,
                             height=_ALT_STATUS)
        caixa.pack(fill="x", pady=(12, 4))
        caixa.pack_propagate(False)                    # 1 ou 2 linhas: mesma altura
        self.lbl_status = W.rotulo(caixa, "", 14, "bold", T.TXT_MUTED,
                                   wraplength=largura, justify="center")
        self.lbl_status.pack(expand=True, fill="both")
        self.btn_ok = W.botao(self._rodape, ok, comando, primario=not perigo, perigo=perigo,
                              width=largura)
        self.btn_ok.pack(fill="x", pady=(4, 8))
        if cancelar:
            self.btn_cancelar = ctk.CTkButton(
                self._rodape, text=cancelar, height=36, fg_color="transparent",
                hover_color=T.BG_CARD_HOV, text_color=T.TXT_MUTED, font=T.font(13),
                command=self.fechar)
            self.btn_cancelar.pack()

    def ao_fechar(self, cb: Callable[[], None]) -> None:
        self._ao_fechar.append(cb)

    def exibir(self, foco=None) -> None:
        self.place(x=0, y=0, relwidth=1, relheight=1)
        self.lower()                                   # desenha escondida
        _pilha.append(self)
        if not getattr(self._raiz, "_sobrep_esc", False):
            self._raiz.bind("<Escape>", _ao_esc, add="+")
            self._raiz._sobrep_esc = True
        self.after(_MONTAGEM_MS, lambda: self._revelar(foco))

    def _revelar(self, foco) -> None:
        if self.fechado:
            return
        if not _retido:
            try:
                reerguer()
            except TclError:
                return
        self._focar(foco)

    def _focar(self, foco) -> None:
        try:
            if not self.fechado:
                (foco or self).focus_set()
        except TclError:
            pass

    def suspender_buffer(self) -> None:
        """Desliga o double buffering até fechar (animações sem engasgo)."""
        if not self._suspenso:
            self._suspenso = True
            anti_flicker.suspender(self._raiz)

    # ---- Estado --------------------------------------------------------------
    def status(self, texto: str, cor: str = T.TXT_MUTED) -> None:
        if self.lbl_status is not None and not self.fechado:
            W.configurar(self.lbl_status, text=texto, text_color=cor)

    def travar(self, travado: bool) -> None:
        self.travado = travado
        if self.btn_ok is not None:
            W.habilitar(self.btn_ok, not travado)
        if self.btn_cancelar is not None:
            W.configurar(self.btn_cancelar, state="disabled" if travado else "normal")

    def esc(self) -> None:
        if not self.travado:
            self.fechar()

    def fechar(self, forcar: bool = False) -> None:
        if self.fechado or (self.travado and not forcar):
            return
        self.fechado = True
        if self in _pilha:
            _pilha.remove(self)
        for cb in self._ao_fechar:
            try:
                cb()
            except Exception:  # noqa: BLE001
                pass
        try:
            if self._suspenso:
                self._suspenso = False
                anti_flicker.retomar(self._raiz)
            self.destroy()
        except TclError:
            pass
