"""
Gestão das mensagens do letreiro (rodapé do Painel): somente gestor.

- Lista: ordem (▲▼), editar, ativar/desativar, excluir (confirmação em 2 cliques).
  Linhas reaproveitadas (pool): só o conteúdo muda; sem destroy a cada atualização.
- Formulário: texto, painel/setor, início/fim (máscara + calendário), ativa.
- Pré-visualização animada só com as mensagens vigentes; pausa quando oculta.
  Cadência IDÊNTICA à do Painel (ui/rodape.py): quadro de 16 ms, deslocamento
  = velocidade × escala × dt (dt limitado a 0,1 s), posição em float, blocos
  encadeados (removidos à esquerda, emendados à direita).
  A velocidade ajustada aqui vale SOMENTE para a pré-visualização.
- abrir() reativa; ocultar() pausa a animação; encerrar() desativa (logout).
- Prontidão: quando_pronto() libera após a carga (lista + setores) renderizada, ok OU erro.
- Banco sempre em background.
"""
import logging
import time
import tkinter as tk
from typing import Callable, Optional

import customtkinter as ctk

from database import descrever_erro
from services import letreiro as svc
from services.letreiro import Aviso, ErroLetreiro
from services.sessao import Sessao
from ui import theme as T
from ui import widgets as W
from ui.campo_data import CampoDataHora
from ui.prontidao import Prontidao

log = logging.getLogger(__name__)

TODOS = "Todos os painéis"
_SEP = "  •  "                       # igual ao Painel
_VAZIO = "— nenhuma mensagem no ar —"
_ESPERA = 300                        # ms, com a tela oculta
_QUADRO_MS = 16                      # igual ao Painel (~60 fps)
_DT_MAX = 0.1                        # igual ao Painel
_MAX_BLOCOS = 200
_CONFIRMAR_MS = 3000

# Velocidade (px/s): mesmos padrão e limites do Painel (PainelConfig)
_VEL_PADRAO, _VEL_MIN, _VEL_MAX, _VEL_PASSO = 80, 20, 300, 10


def _resumo(a: dict) -> str:
    partes = [a["setor"] or TODOS]
    if a["inicio_em"] or a["fim_em"]:
        partes.append(f"{svc.formatar_data(a['inicio_em']) or '…'} → "
                      f"{svc.formatar_data(a['fim_em']) or '…'}")
    if not a["ativo"]:
        partes.append("Inativa")
    else:
        partes.append("No ar" if a["vigente"] else "Fora do período")
    return "  •  ".join(partes)


class LinhaAviso(ctk.CTkFrame):
    """Linha reaproveitável: mostrar() troca só o conteúdo."""

    def __init__(self, master, acoes: dict[str, Callable]):
        super().__init__(master, fg_color=T.BG_ITEM, corner_radius=12)
        self.grid_columnconfigure(1, weight=1)
        self._acoes = acoes
        self._a: Optional[dict] = None
        self._ativo_ant: Optional[bool] = None
        self._confirmar = False
        self._job: Optional[str] = None

        self._barra = ctk.CTkFrame(self, width=6, height=44, corner_radius=3, fg_color=T.NEON)
        self._barra.grid(row=0, column=0, rowspan=2, padx=10, pady=8)
        self._txt = W.rotulo(self, "", 14, "bold", anchor="w", justify="left", wraplength=430)
        self._txt.grid(row=0, column=1, sticky="ew", pady=(8, 0))
        self._res = W.rotulo(self, "", 12, cor=T.TXT_MUTED, anchor="w")
        self._res.grid(row=1, column=1, sticky="ew", pady=(0, 8))

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=2, rowspan=2, padx=8)
        self._sub = W.botao(bar, "▲", lambda: self._acao("mover", -1), height=32, size=12,
                            width=36)
        self._des = W.botao(bar, "▼", lambda: self._acao("mover", 1), height=32, size=12,
                            width=36)
        ed = W.botao(bar, "Editar", lambda: self._a and acoes["editar"](self._a), height=32,
                     size=12, width=72)
        self._at = W.botao(bar, "Desativar", lambda: self._acao("alternar"), icone="pause",
                           height=32, size=12, width=104)
        self._exc = W.botao(bar, "Excluir", self._excluir, perigo=True, icone="ban",
                            height=32, size=12, width=96)
        for i, b in enumerate((self._sub, self._des, ed, self._at, self._exc)):
            b.grid(row=0, column=i, padx=3)

    def _id(self) -> Optional[int]:
        return int(self._a["id"]) if self._a else None

    def _acao(self, nome: str, *args) -> None:
        if self._a:
            self._acoes[nome](self._id(), *args)

    def mostrar(self, a: dict, primeiro: bool, ultimo: bool) -> None:
        if self._a is None or int(a["id"]) != self._id():
            self._resetar_exclusao()
        self._a = a
        ativo = bool(a["ativo"])
        cor = T.NEON if a["vigente"] else (T.WARN if ativo else T.TXT_OFF)
        W.configurar(self._barra, fg_color=cor)
        W.configurar(self._txt, text=a["texto"], text_color=T.TXT if ativo else T.TXT_MUTED)
        W.configurar(self._res, text=_resumo(a))
        W.habilitar(self._sub, not primeiro)
        W.habilitar(self._des, not ultimo)
        if ativo != self._ativo_ant:
            self._ativo_ant = ativo
            W.definir(self._at, "Desativar" if ativo else "Ativar", "pause" if ativo else "play")

    def _excluir(self) -> None:
        if not self._a:
            return
        if self._confirmar:
            aid = self._id()
            self._resetar_exclusao()
            self._acoes["excluir"](aid)
            return
        self._confirmar = True
        W.definir(self._exc, "Confirmar")
        self._job = self.after(_CONFIRMAR_MS, self._resetar_exclusao)

    def _resetar_exclusao(self) -> None:
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:  # noqa: BLE001
                pass
            self._job = None
        try:
            if self._confirmar and self.winfo_exists():
                self._confirmar = False
                W.definir(self._exc, "Excluir")
        except Exception:  # noqa: BLE001
            pass


class TelaLetreiro(ctk.CTkFrame):
    def __init__(self, master, executar_bg: Callable, sessao: Sessao,
                 on_voltar: Callable[[], None]):
        super().__init__(master, fg_color="transparent")
        self._bg = executar_bg
        self._s = sessao
        self._on_voltar = on_voltar
        self._ativo = True
        self._ocupado = False
        self._pronto = Prontidao()
        self._editando: Optional[int] = None
        self._setores: dict[str, Optional[int]] = {TODOS: None}
        self._linhas: list[LinhaAviso] = []
        self._qtd = 0
        self._acoes = {"mover": self._mover, "editar": self._editar,
                       "alternar": self._alternar, "excluir": self._excluir}
        # Pré-visualização (mesma estrutura do Painel)
        self._anim: Optional[str] = None
        self._texto = ""
        self._blocos: list[list] = []          # [item, largura] esq. → dir.
        self._x: Optional[float] = None        # borda esquerda do 1º bloco
        self._t = time.monotonic()
        self._vel = _VEL_PADRAO
        self._fonte_prev = T.font(20, "bold")
        self._erro_anim_logado = False

        self.grid_columnconfigure(0, weight=3, uniform="col")
        self.grid_columnconfigure(1, weight=2, uniform="col")
        self.grid_rowconfigure(1, weight=1)
        self._montar_topo()
        self._montar_lista()
        self._montar_form()
        self._montar_preview()

    # ---- Montagem -----------------------------------------------------------
    def _montar_topo(self):
        t = ctk.CTkFrame(self, fg_color=T.BG_CARD, corner_radius=20,
                         border_width=2, border_color=T.BORDER)
        t.grid(row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=(16, 8))
        t.grid_columnconfigure(1, weight=1)
        W.rotulo(t, "◉  MENSAGENS DO LETREIRO", 22, "bold", T.NEON).grid(
            row=0, column=0, padx=24, pady=14, sticky="w")
        W.rotulo(t, f"{self._s.usuario.nome}  •  Gestor", 15, cor=T.TXT_MUTED).grid(
            row=0, column=1, sticky="w", padx=8)
        W.botao(t, "Voltar ao atendimento", self._on_voltar, icone="undo", height=42,
                size=14, width=230).grid(row=0, column=2, padx=(6, 24))

    def _montar_lista(self):
        c = W.card(self)
        c.grid(row=1, column=0, sticky="nsew", padx=(20, 8), pady=8)
        c.grid_propagate(False)
        c.grid_columnconfigure(0, weight=1)
        c.grid_rowconfigure(1, weight=1)
        self.lbl_qtd = W.rotulo(c, "MENSAGENS", 15, "bold", T.TXT_MUTED, anchor="w")
        self.lbl_qtd.grid(row=0, column=0, sticky="ew", padx=22, pady=(18, 6))
        self.lista = W.ListaRolavel(c)
        self.lista.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 14))
        self.lbl_vazio = W.rotulo(self.lista, "Carregando mensagens…", 14, cor=T.TXT_MUTED)
        self.lbl_vazio.pack(pady=16)

    def _montar_form(self):
        c = W.card(self)
        c.grid(row=1, column=1, sticky="nsew", padx=(8, 20), pady=8)
        c.grid_columnconfigure(0, weight=1)
        px = 24
        self.lbl_form = W.rotulo(c, "NOVA MENSAGEM", 15, "bold", T.TXT_MUTED, anchor="w")
        self.lbl_form.grid(row=0, column=0, sticky="ew", padx=px, pady=(18, 10))

        W.rotulo(c, "Texto", 14, "bold", anchor="w").grid(row=1, column=0, sticky="ew", padx=px)
        self.ent_texto = W.entrada(c, "Ex.: Horário de funcionamento: 07h às 19h")
        self.ent_texto.grid(row=2, column=0, sticky="ew", padx=px)
        self.ent_texto.bind("<KeyRelease>", lambda _e: self._contar())
        self.lbl_cont = W.rotulo(c, f"0/{svc.TEXTO_MAX}", 12, cor=T.TXT_MUTED, anchor="e")
        self.lbl_cont.grid(row=3, column=0, sticky="ew", padx=px)

        W.rotulo(c, "Exibir em", 14, "bold", anchor="w").grid(
            row=4, column=0, sticky="ew", padx=px)
        self.opt_setor = W.opcoes(c, [TODOS])
        self.opt_setor.grid(row=5, column=0, sticky="ew", padx=px, pady=(0, 10))
        self.opt_setor.set(TODOS)

        per = ctk.CTkFrame(c, fg_color="transparent")
        per.grid(row=6, column=0, sticky="ew", padx=px)
        per.grid_columnconfigure((0, 1), weight=1, uniform="p")
        W.rotulo(per, "Início (opcional)", 14, "bold", anchor="w").grid(
            row=0, column=0, sticky="ew")
        W.rotulo(per, "Fim (opcional)", 14, "bold", anchor="w").grid(
            row=0, column=1, sticky="ew", padx=(8, 0))
        self.ent_ini = CampoDataHora(per, "00:00")
        self.ent_ini.grid(row=1, column=0, sticky="ew")
        self.ent_fim = CampoDataHora(per, "23:59")
        self.ent_fim.grid(row=1, column=1, sticky="ew", padx=(8, 0))

        self.sw_ativo = ctk.CTkSwitch(c, text="Mensagem ativa", font=T.font(14, "bold"),
                                      text_color=T.TXT, progress_color=T.NEON,
                                      button_color=T.TXT, button_hover_color=T.NEON_DARK,
                                      fg_color=T.BORDER)
        self.sw_ativo.grid(row=7, column=0, sticky="w", padx=px, pady=14)

        bts = ctk.CTkFrame(c, fg_color="transparent")
        bts.grid(row=8, column=0, sticky="ew", padx=px)
        bts.grid_columnconfigure((0, 1), weight=1, uniform="b")
        self.btn_salvar = W.botao(bts, "Salvar", self._salvar, primario=True, icone="check")
        self.btn_salvar.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        W.botao(bts, "Limpar", self._limpar_form, icone="undo").grid(
            row=0, column=1, sticky="ew", padx=(6, 0))

        self.lbl_msg = W.rotulo(c, "", 14, "bold", T.TXT_MUTED, height=40, wraplength=420)
        self.lbl_msg.grid(row=9, column=0, sticky="ew", padx=px, pady=(10, 18))

    def _montar_preview(self):
        c = W.card(self)
        c.grid(row=2, column=0, columnspan=2, sticky="ew", padx=20, pady=(8, 20))
        c.grid_columnconfigure(0, weight=1)
        W.rotulo(c, "PRÉ-VISUALIZAÇÃO DO PAINEL (mensagens no ar)", 13, "bold",
                 T.TXT_MUTED, anchor="w").grid(row=0, column=0, sticky="ew", padx=22,
                                              pady=(12, 4))

        ctl = ctk.CTkFrame(c, fg_color="transparent")
        ctl.grid(row=0, column=1, sticky="e", padx=22, pady=(12, 4))
        W.rotulo(ctl, "Velocidade (só pré-visualização)", 12, cor=T.TXT_MUTED).grid(
            row=0, column=0, padx=(0, 10))
        self.sld_vel = ctk.CTkSlider(
            ctl, from_=_VEL_MIN, to=_VEL_MAX,
            number_of_steps=(_VEL_MAX - _VEL_MIN) // _VEL_PASSO, width=220,
            fg_color=T.BORDER, progress_color=T.NEON, button_color=T.NEON,
            button_hover_color=T.NEON_DARK, command=self._ao_velocidade)
        self.sld_vel.grid(row=0, column=1)
        self.lbl_vel = W.rotulo(ctl, "", 13, "bold", T.NEON, width=70, anchor="e")
        self.lbl_vel.grid(row=0, column=2, padx=(8, 10))
        W.botao(ctl, "Padrão do painel", self._vel_padrao, icone="undo", height=32,
                size=12, width=150).grid(row=0, column=3)

        self.canvas = tk.Canvas(c, height=52, bg="#000000", highlightthickness=0)
        self.canvas.grid(row=1, column=0, columnspan=2, sticky="ew", padx=18, pady=(0, 16))
        self._vel_padrao()

    # ---- API (App) ----------------------------------------------------------
    def quando_pronto(self, cb: Callable[[], None]) -> None:
        self._pronto.quando(cb)

    def abrir(self) -> None:
        self._ativo = True
        self._limpar_form()
        self._vel_padrao()
        self._carregar()
        if not self._anim:
            self._t = time.monotonic()
            self._anim = self.after(_QUADRO_MS, self._animar)

    def ocultar(self) -> None:
        """Saiu da tela (fica empilhada por baixo): pausa a animação."""
        if self._anim:
            self.after_cancel(self._anim)
            self._anim = None

    def encerrar(self) -> None:
        self._ativo = False
        self.ocultar()

    # ---- Dados --------------------------------------------------------------
    def _carregar(self):
        uid = self._s.usuario.id
        self._pronto.iniciar()
        self._bg(lambda: (svc.listar(uid), svc.listar_setores()), self._ao_carregar,
                 self._falha_carga)

    def _ao_carregar(self, r):
        try:
            self._ao_dados(r)
        finally:
            self._pronto.concluir()

    def _falha_carga(self, exc):
        try:
            if self._ativo and self._qtd == 0:
                W.configurar(self.lbl_vazio, text="Não foi possível carregar as mensagens.")
            self._falha(exc)
        finally:
            self._pronto.concluir()

    def _ao_dados(self, r):
        if not self._ativo:
            return
        avisos, setores = r
        self._setores = {TODOS: None, **{s["nome"]: int(s["id"]) for s in setores}}
        atual = self.opt_setor.get()
        self.opt_setor.configure(values=list(self._setores))
        self.opt_setor.set(atual if atual in self._setores else TODOS)
        self._render(avisos)
        vigentes = [a["texto"] for a in avisos if a["vigente"]]
        texto = _SEP.join(vigentes or [_VAZIO]) + _SEP     # termina com o separador
        if texto != self._texto:
            self._definir_texto(texto)

    def _render(self, avisos: list[dict]):
        n = len(avisos)
        while len(self._linhas) < n:
            self._linhas.append(LinhaAviso(self.lista, self._acoes))
        for i, (linha, a) in enumerate(zip(self._linhas, avisos)):
            linha.mostrar(a, i == 0, i == n - 1)
        if n:
            self.lbl_vazio.pack_forget()
        else:
            W.configurar(self.lbl_vazio, text="Nenhuma mensagem cadastrada.")
            self.lbl_vazio.pack(pady=16)
        if n != self._qtd:
            for i in range(self._qtd, n):
                self._linhas[i].pack(fill="x", pady=3, padx=2)
            for i in range(n, self._qtd):
                self._linhas[i].pack_forget()
            self._qtd = n
        W.configurar(self.lbl_qtd, text=f"MENSAGENS  ({n})")
        self.lista.ajustar_barra()

    # ---- Ações --------------------------------------------------------------
    def _acao(self, func: Callable, msg_ok: str, depois: Optional[Callable] = None):
        if self._ocupado or not self._ativo:
            return
        self._ocupado = True
        W.habilitar(self.btn_salvar, False)

        def ok(_r):
            self._ocupado = False
            if not self._ativo:
                return
            W.habilitar(self.btn_salvar, True)
            if depois:
                depois()
            self._msg(msg_ok, T.NEON)
            self._carregar()

        def falha(exc):
            self._ocupado = False
            if self._ativo:
                W.habilitar(self.btn_salvar, True)
                self._falha(exc)

        self._bg(func, ok, falha)

    def _falha(self, exc):
        if self._ativo:
            msg = str(exc) if isinstance(exc, ErroLetreiro) else descrever_erro(exc)
            self._msg(f"✖ {msg}", T.DANGER)

    def _salvar(self):
        try:
            a = Aviso(self._editando, self.ent_texto.get(),
                      self._setores.get(self.opt_setor.get()), bool(self.sw_ativo.get()),
                      svc.ler_data(self.ent_ini.get()), svc.ler_data(self.ent_fim.get()))
            svc.validar(a)
        except ErroLetreiro as exc:
            self._msg(f"✖ {exc}", T.DANGER)
            return
        u = self._s.usuario
        self._acao(lambda: svc.salvar(u.id, u.login, a), "✔ Mensagem salva.", self._limpar_form)

    def _mover(self, aid: int, delta: int):
        uid = self._s.usuario.id
        self._acao(lambda: svc.mover(uid, aid, delta), "✔ Ordem atualizada.")

    def _alternar(self, aid: int):
        uid = self._s.usuario.id
        self._acao(lambda: svc.alternar_ativo(uid, aid), "✔ Status alterado.")

    def _excluir(self, aid: int):
        uid = self._s.usuario.id
        fim = self._limpar_form if self._editando == aid else None
        self._acao(lambda: svc.excluir(uid, aid), "✔ Mensagem excluída.", fim)

    # ---- Formulário ---------------------------------------------------------
    def _editar(self, a: dict):
        self._editando = int(a["id"])
        W.configurar(self.lbl_form, text="EDITAR MENSAGEM", text_color=T.NEON)
        self.ent_texto.delete(0, "end")
        self.ent_texto.insert(0, a["texto"])
        self.opt_setor.set(a["setor"] if a["setor"] in self._setores else TODOS)
        self.ent_ini.set(svc.formatar_data(a["inicio_em"]))
        self.ent_fim.set(svc.formatar_data(a["fim_em"]))
        (self.sw_ativo.select if a["ativo"] else self.sw_ativo.deselect)()
        self._contar()
        self._msg("")
        self.ent_texto.focus_set()

    def _limpar_form(self):
        self._editando = None
        W.configurar(self.lbl_form, text="NOVA MENSAGEM", text_color=T.TXT_MUTED)
        self.ent_texto.delete(0, "end")
        self.ent_ini.limpar()
        self.ent_fim.limpar()
        self.opt_setor.set(TODOS)
        self.sw_ativo.select()
        self._contar()
        self._msg("")

    def _contar(self):
        n = len(self.ent_texto.get())
        W.configurar(self.lbl_cont, text=f"{n}/{svc.TEXTO_MAX}",
                     text_color=T.DANGER if n > svc.TEXTO_MAX else T.TXT_MUTED)

    def _msg(self, texto: str, cor: str = T.TXT_MUTED):
        W.configurar(self.lbl_msg, text=texto, text_color=cor)

    # ---- Pré-visualização: velocidade ---------------------------------------
    def _ao_velocidade(self, valor: float):
        self._vel = max(_VEL_MIN, min(_VEL_MAX, int(round(valor))))
        W.configurar(self.lbl_vel, text=f"{self._vel} px/s")

    def _vel_padrao(self):
        self.sld_vel.set(_VEL_PADRAO)            # set() não dispara o command
        self._ao_velocidade(_VEL_PADRAO)

    # ---- Pré-visualização: rolagem (cadência do Painel) ---------------------
    def _definir_texto(self, texto: str):
        """Troca imediata: limpa os blocos e recomeça pela borda direita."""
        for item, _ in self._blocos:
            self.canvas.delete(item)
        self._blocos.clear()
        self._texto = texto
        self._x = None

    def _novo_bloco(self, x: float, y: float) -> float:
        item = self.canvas.create_text(x, y, text=self._texto, anchor="w",
                                       font=self._fonte_prev, fill=T.NEON)
        caixa = self.canvas.bbox(item)
        largura = max(1, (caixa[2] - caixa[0]) if caixa else 1)
        self._blocos.append([item, largura])
        return largura

    def _animar(self):
        self._anim = None
        if not self._ativo:
            return
        if not self.canvas.winfo_viewable():
            self._anim = self.after(_ESPERA, self._animar)
            self._t = time.monotonic()
            return
        try:
            self._passo()
        except Exception:  # noqa: BLE001
            if not self._erro_anim_logado:
                self._erro_anim_logado = True
                log.exception("Erro na animação da pré-visualização do letreiro.")
        finally:
            if self._ativo:
                self._anim = self.after(_QUADRO_MS, self._animar)

    def _passo(self):
        agora = time.monotonic()
        dt = min(agora - self._t, _DT_MAX)
        self._t = agora
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if w <= 1 or not self._texto:
            return
        if self._x is None or not self._blocos:
            self._x = float(w) if self._x is None else self._x
        self._x -= self._vel * (self._get_widget_scaling() or 1) * dt

        # Remove blocos que saíram pela esquerda
        while self._blocos and self._x + self._blocos[0][1] < 0:
            item, largura = self._blocos.pop(0)
            self.canvas.delete(item)
            self._x += largura

        # Emenda novos blocos até cobrir a largura
        y = h / 2
        fim = self._x + sum(b[1] for b in self._blocos)
        if not self._blocos:
            fim = self._x = max(self._x, 0.0)
        while fim < w and len(self._blocos) < _MAX_BLOCOS:
            fim += self._novo_bloco(fim, y)

        x = self._x
        for item, largura in self._blocos:
            self.canvas.coords(item, x, y)
            x += largura
