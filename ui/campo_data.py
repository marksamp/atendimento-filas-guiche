"""
Campo de data/hora com máscara (dd/mm/aaaa hh:mm) e calendário suspenso.
- so_data=True: máscara dd/mm/aaaa e calendário sem hora (colunas DATE);
  use data()/definir_data() para ler/gravar datetime.date.
- O calendário abre ao focar/clicar no campo (sem botão lateral).
- Clique + foco disparam juntos: abertura agendada UMA vez (coalescida) e
  protegida contra reentrância durante a construção do overlay.
- Digite só números; separadores são inseridos e o calendário acompanha.
- Fecha com Esc/Enter, Tab, clique fora ou escolha de uma data.
- Só a data digitada (modo data/hora)? Ao sair completa com a hora padrão.
- Data inexistente (ex.: mês 23) deixa a borda vermelha ao sair do campo.
"""
import re
from datetime import date, datetime
from typing import Optional

import customtkinter as ctk

from ui import theme as T
from ui import widgets as W
from ui.calendario import Calendario

FORMATO = "%d/%m/%Y %H:%M"
FORMATO_DATA = "%d/%m/%Y"
_NAVEG = {"Left", "Right", "Up", "Down", "Home", "End", "Tab", "Return", "Escape",
          "Shift_L", "Shift_R", "Control_L", "Control_R"}
_PARTES = ((0, 2, ""), (2, 4, "/"), (4, 8, "/"), (8, 10, " "), (10, 12, ":"))


def mascarar(digitos: str, limite: int = 12) -> str:
    d = digitos[:limite]
    return "".join(sep + d[i:j] for i, j, sep in _PARTES if len(d) > i)


def _digitos(txt: str) -> str:
    return re.sub(r"\D", "", txt)


class CampoDataHora(ctk.CTkFrame):
    def __init__(self, master, hora_padrao: str = "00:00", so_data: bool = False,
                 largura: int = 120):
        super().__init__(master, fg_color="transparent")
        self._hora = hora_padrao
        self._so_data = so_data
        self._fmt = FORMATO_DATA if so_data else FORMATO
        self._limite = 8 if so_data else 12
        self._popup: Optional[Calendario] = None
        self._ignorar_foco = False
        self._erro = False
        self._job_abrir: Optional[str] = None
        self._abrindo = False
        self.grid_columnconfigure(0, weight=1)

        dica = "dd/mm/aaaa" if so_data else "dd/mm/aaaa hh:mm"
        self.ent = W.entrada(self, dica, width=largura)
        self.ent.grid(row=0, column=0, sticky="ew")
        self.ent.bind("<KeyRelease>", self._ao_digitar)
        self.ent.bind("<FocusIn>", lambda _e: self._ao_focar())
        self.ent.bind("<FocusOut>", lambda _e: self._ao_sair())
        self.ent.bind("<Button-1>", lambda _e: self._agendar_abrir())
        self.ent.bind("<Escape>", lambda _e: self._fechar())
        self.ent.bind("<Return>", lambda _e: self._fechar())
        self.bind("<Unmap>", lambda _e: self._fechar(), add="+")
        self.bind("<Destroy>", lambda _e: self._ao_destruir(), add="+")

    # ---- API ----------------------------------------------------------------
    def get(self) -> str:
        return self.ent.get().strip()

    def set(self, txt: str) -> None:
        self.ent.delete(0, "end")
        if txt:
            self.ent.insert(0, txt)
        self._marcar_erro(False)

    def limpar(self) -> None:
        self._fechar()
        self.set("")

    def data(self) -> Optional[date]:
        """Data do campo (None se vazio). ValueError se inválida."""
        txt = self.get()
        if not txt:
            return None
        try:
            return datetime.strptime(txt, self._fmt).date()
        except ValueError:
            self._marcar_erro(True)
            raise ValueError(f"Data inválida: '{txt}' (use {self.ent.cget('placeholder_text')}).") \
                from None

    def definir_data(self, valor: Optional[date]) -> None:
        self.set(valor.strftime(self._fmt) if valor else "")

    # ---- Máscara / validação ------------------------------------------------
    def _ao_digitar(self, e):
        if e.keysym in _NAVEG:
            return
        self._mascara()
        self._marcar_erro(False)
        if self._aberto():
            try:
                self._popup.mostrar(datetime.strptime(self.get(), self._fmt))
            except ValueError:
                pass

    def _mascara(self):
        txt = self.ent.get()
        antes = len(_digitos(txt[:self.ent.index("insert")]))
        novo = mascarar(_digitos(txt), self._limite)
        if novo == txt:
            return
        self.ent.delete(0, "end")
        self.ent.insert(0, novo)
        idx = cont = 0
        while idx < len(novo) and cont < antes:
            cont += novo[idx].isdigit()
            idx += 1
        self.ent.icursor(idx)

    def _completar(self):
        if self._so_data:
            return
        d = _digitos(self.ent.get())
        if len(d) == 8:
            self.set(mascarar(d + _digitos(self._hora)))

    def _valido(self) -> bool:
        txt = self.get()
        if not txt:
            return True
        try:
            datetime.strptime(txt, self._fmt)
            return True
        except ValueError:
            return False

    def _marcar_erro(self, erro: bool):
        if erro != self._erro:
            self._erro = erro
            self.ent.configure(border_color=T.DANGER if erro else T.BORDER)

    # ---- Foco ---------------------------------------------------------------
    def _ao_focar(self):
        if not self._ignorar_foco:
            self._agendar_abrir()

    def _ao_sair(self):
        self._completar()
        self._marcar_erro(not self._valido())
        self.after(120, self._verificar_foco)

    def _verificar_foco(self):
        if not self._aberto():
            return
        try:
            f = self.focus_get()
        except (KeyError, Exception):  # noqa: BLE001  (popdowns do Tk)
            return
        if f is None or f is self.ent or str(f).startswith(str(self.ent)) \
                or self._popup.contem(f):
            return
        self._fechar()

    # ---- Calendário ---------------------------------------------------------
    def _aberto(self) -> bool:
        try:
            return self._popup is not None and bool(self._popup.winfo_exists())
        except Exception:  # noqa: BLE001
            return False

    def _agendar_abrir(self):
        if self._job_abrir is None:
            self._job_abrir = self.after_idle(self._executar_abrir)

    def _executar_abrir(self):
        self._job_abrir = None
        self._abrir()

    def _abrir(self):
        if self._abrindo or self._aberto() or not self.winfo_viewable():
            return
        try:
            valor = datetime.strptime(self.get(), self._fmt)
        except ValueError:
            valor = None
        self._abrindo = True
        try:
            self._popup = Calendario(self, valor, self._hora, self._ao_escolher,
                                     com_hora=not self._so_data)
        finally:
            self._abrindo = False

    def _fechar(self):
        if self._aberto():
            self._popup.fechar()
        self._popup = None

    def _ao_destruir(self):
        if self._job_abrir is not None:
            try:
                self.after_cancel(self._job_abrir)
            except Exception:  # noqa: BLE001
                pass
            self._job_abrir = None
        self._fechar()

    def _ao_escolher(self, dt: Optional[datetime]):
        self.set(dt.strftime(self._fmt) if dt else "")
        self._popup = None
        self._ignorar_foco = True                # volta o foco sem reabrir
        self.ent.focus_set()
        self.ent.icursor("end")
        self.after(200, lambda: setattr(self, "_ignorar_foco", False))
