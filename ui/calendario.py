"""
Calendário suspenso (tema escuro/neon) para escolha de data e hora.
- Overlay desenhado DENTRO da janela principal (place sobre a raiz): sem
  Toplevel/overrideredirect, logo sempre aparece e aceita foco em qualquer SO.
- Clique no dia = confirma e fecha. Esc, clique fora ou saída do campo = fecha.
- com_hora=False: sem a linha da hora (campos DATE); devolve meia-noite.
- Só um calendário aberto por vez (handler global de clique instalado uma vez).
- CTk proíbe bind_all nos seus widgets: usa tk.Misc.bind_all (Tk puro).
- update_idletasks() pode executar callbacks pendentes que fecham este overlay:
  o posicionamento confere se ele ainda existe.
"""
import calendar
import re
import tkinter as tk
from datetime import date, datetime, time, timedelta
from typing import Callable, Optional

import customtkinter as ctk

from ui import theme as T

MESES = ("Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
         "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro")
DIAS = ("D", "S", "T", "Q", "Q", "S", "S")
_CAL = calendar.Calendar(firstweekday=6)    # domingo primeiro
_MARGEM = 4

_aberto: Optional["Calendario"] = None
_instalado = False


def _dentro(widget, pai) -> bool:
    try:
        nome, base = str(widget), str(pai)
    except Exception:  # noqa: BLE001
        return False
    return nome == base or nome.startswith(base + ".")


def _clique_global(e):
    c = _aberto
    try:
        if c is None or not c.winfo_exists():
            return
    except Exception:  # noqa: BLE001
        return
    if _dentro(e.widget, c) or _dentro(e.widget, c.ancora):
        return
    c.fechar()


def _instalar(widget) -> None:
    """Handler global de clique (uma vez). tk.Misc.bind_all contorna o bloqueio do CTk."""
    global _instalado
    if not _instalado:
        tk.Misc.bind_all(widget, "<Button-1>", _clique_global, "+")
        _instalado = True


class Calendario(ctk.CTkFrame):
    def __init__(self, ancora, valor: Optional[datetime], hora_padrao: str,
                 ao_escolher: Callable[[Optional[datetime]], None], com_hora: bool = True):
        global _aberto
        if _aberto is not None:
            _aberto.fechar()
        super().__init__(ancora.winfo_toplevel(), fg_color=T.BG_CARD, corner_radius=14,
                         border_width=2, border_color=T.NEON)
        self.ancora = ancora
        self._cb = ao_escolher
        self._hora_padrao = hora_padrao
        self._com_hora = com_hora
        self.ent_hora: Optional[ctk.CTkEntry] = None
        self._hoje = date.today()
        self._sel = valor.date() if valor else None
        base = self._sel or self._hoje
        self._ano, self._mes = base.year, base.month
        self._botoes: list[ctk.CTkButton] = []

        try:
            self._montar(valor.strftime("%H:%M") if valor else hora_padrao)
            self._render()
            _instalar(ancora)
            _aberto = self
            self._posicionar()
        except Exception:
            self.fechar()                        # nunca deixa overlay órfão
            raise

    # ---- Montagem -----------------------------------------------------------
    def _nav(self, master, txt: str, delta: int) -> ctk.CTkButton:
        return ctk.CTkButton(master, text=txt, width=34, height=30, corner_radius=8,
                             font=T.font(16, "bold"), fg_color="transparent",
                             hover_color=T.BG_CARD_HOV, text_color=T.NEON,
                             command=lambda: self._mudar(delta))

    def _montar(self, hora: str):
        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.pack(fill="x", padx=10, pady=(10, 4))
        topo.grid_columnconfigure(1, weight=1)
        self._nav(topo, "‹", -1).grid(row=0, column=0)
        self.lbl_mes = ctk.CTkLabel(topo, text="", font=T.font(15, "bold"), text_color=T.TXT)
        self.lbl_mes.grid(row=0, column=1)
        self._nav(topo, "›", 1).grid(row=0, column=2)

        grade = ctk.CTkFrame(self, fg_color="transparent")
        grade.pack(padx=10)
        for c, d in enumerate(DIAS):
            ctk.CTkLabel(grade, text=d, width=38, font=T.font(12, "bold"),
                         text_color=T.TXT_MUTED).grid(row=0, column=c)
        for i in range(42):
            b = ctk.CTkButton(grade, text="", width=38, height=32, corner_radius=8,
                              font=T.font(13), hover_color=T.BG_CARD_HOV,
                              border_color=T.NEON)
            b.grid(row=1 + i // 7, column=i % 7, padx=1, pady=1)
            self._botoes.append(b)

        rod = ctk.CTkFrame(self, fg_color="transparent")
        rod.pack(fill="x", padx=12, pady=(8, 12))
        if self._com_hora:
            ctk.CTkLabel(rod, text="Hora", font=T.font(13, "bold"),
                         text_color=T.TXT).pack(side="left")
            self.ent_hora = ctk.CTkEntry(rod, width=70, height=30, corner_radius=8,
                                         font=T.font(13), fg_color=T.BG_ITEM,
                                         border_color=T.BORDER, text_color=T.TXT,
                                         justify="center")
            self.ent_hora.insert(0, hora)
            self.ent_hora.pack(side="left", padx=(6, 0))
            self.ent_hora.bind("<KeyRelease>", self._mascara_hora)
            self.ent_hora.bind("<Return>", lambda _e: self._escolher(self._sel or self._hoje))
            self.ent_hora.bind("<Escape>", lambda _e: self.fechar())
        for txt, cmd in (("Limpar", self._limpar), ("Hoje", self._ir_hoje)):
            ctk.CTkButton(rod, text=txt, width=64, height=30, corner_radius=8,
                          font=T.font(12, "bold"), fg_color="transparent",
                          hover_color=T.BG_CARD_HOV, text_color=T.NEON,
                          border_width=1, border_color=T.BORDER,
                          command=cmd).pack(side="right", padx=(6, 0))

    def _render(self):
        self.lbl_mes.configure(text=f"{MESES[self._mes - 1]} {self._ano}")
        dias = [d for sem in _CAL.monthdatescalendar(self._ano, self._mes) for d in sem]
        dias += [dias[-1] + timedelta(days=i) for i in range(1, 43 - len(dias))]
        for b, d in zip(self._botoes, dias):
            sel, hoje = d == self._sel, d == self._hoje
            if sel:
                cor = T.BG_APP
            elif hoje:
                cor = T.NEON
            else:
                cor = T.TXT if d.month == self._mes else T.TXT_OFF
            b.configure(text=str(d.day), text_color=cor,
                        fg_color=T.NEON if sel else "transparent",
                        border_width=1 if hoje and not sel else 0,
                        command=lambda d=d: self._escolher(d))

    def _posicionar(self):
        """Coordenadas em px reais; place() do CTk reaplica a escala, por isso divide."""
        raiz, a = self.master, self.ancora
        self.update_idletasks()
        if not self.winfo_exists() or _aberto is not self:
            return                               # fechado por callback pendente
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        x = a.winfo_rootx() - raiz.winfo_rootx()
        topo = a.winfo_rooty() - raiz.winfo_rooty()
        y = topo + a.winfo_height() + _MARGEM
        if y + h > raiz.winfo_height() and topo - h - _MARGEM >= 0:
            y = topo - h - _MARGEM
        x = max(0, min(x, raiz.winfo_width() - w))
        s = self._get_widget_scaling() or 1
        self.place(x=x / s, y=y / s)
        self.lift()

    # ---- API ----------------------------------------------------------------
    def contem(self, widget) -> bool:
        return _dentro(widget, self)

    def mostrar(self, valor: datetime) -> None:
        """Sincroniza com o que foi digitado no campo."""
        self._sel = valor.date()
        self._ano, self._mes = valor.year, valor.month
        if self.ent_hora is not None:
            self.ent_hora.delete(0, "end")
            self.ent_hora.insert(0, valor.strftime("%H:%M"))
        self._render()

    def fechar(self):
        global _aberto
        if _aberto is self:
            _aberto = None
        try:
            if self.winfo_exists():
                self.destroy()
        except Exception:  # noqa: BLE001
            pass

    # ---- Ações --------------------------------------------------------------
    def _mudar(self, delta: int):
        m = self._mes - 1 + delta
        self._ano += m // 12
        self._mes = m % 12 + 1
        self._render()

    def _hora(self) -> time:
        if self.ent_hora is None:
            return time(0, 0)
        for txt in (self.ent_hora.get(), self._hora_padrao):
            try:
                return datetime.strptime(txt.strip(), "%H:%M").time()
            except ValueError:
                continue
        return time(0, 0)

    def _escolher(self, d: date):
        cb, dt = self._cb, datetime.combine(d, self._hora())
        self.fechar()
        cb(dt)

    def _ir_hoje(self):
        self._escolher(self._hoje)

    def _limpar(self):
        cb = self._cb
        self.fechar()
        cb(None)

    def _mascara_hora(self, e):
        if e.keysym in ("Left", "Right", "Tab", "Home", "End", "Return", "Escape"):
            return
        atual = self.ent_hora.get()
        d = re.sub(r"\D", "", atual)[:4]
        novo = d[:2] + (":" + d[2:] if len(d) > 2 else "")
        if novo != atual:
            self.ent_hora.delete(0, "end")
            self.ent_hora.insert(0, novo)
            self.ent_hora.icursor("end")
