"""
Tela principal do atendente.

- Senha atual (chamando / em atendimento) com ações conforme o status.
- Fila de espera e ausentes (reativar) dos setores do usuário.
- quando_pronto(cb): o App mantém a tela de loading até os primeiros dados
  (ou a primeira falha, que é exibida na tela).
- Atualização periódica em background (inclusive parâmetros: nada de banco na UI).
- ANTI-FLICKER: linhas reaproveitadas (W.ListaSenhas), configure só do que mudou
  (W.configurar); cards e bloco central com tamanho fixo (grid_propagate(False)).
- Cada ação usa um uuid de requisição; em falha de rede o mesmo uuid é
  reutilizado no próximo clique (idempotência no servidor).
"""
import uuid
from typing import Callable, Optional

import customtkinter as ctk

from config import UI
from database import descrever_erro, eh_erro_rede
from services import fila_service, parametros
from services import sessao as sessao_svc
from services.fila_service import RegraViolada
from services.sessao import ErroSessao, Sessao
from ui import theme as T
from ui import widgets as W
from ui.icones import icone

TODOS = "Todos os meus setores"
_CARREGANDO = "Carregando…"


class TelaAtendimento(ctk.CTkFrame):
    def __init__(self, master, executar_bg: Callable, sessao: Sessao,
                 on_sair: Callable[[], None], on_trocar_senha: Callable[[], None]):
        super().__init__(master, fg_color="transparent")
        self._bg = executar_bg
        self._s = sessao
        self._on_sair = on_sair
        self._on_trocar_senha = on_trocar_senha
        self._ativo = True
        self._carregado = False
        self._pronto = False
        self._ao_pronto: list[Callable[[], None]] = []
        self._ocupado = False
        self._atualizando = False
        self._pendente = False
        self._offline = False
        self._job: Optional[str] = None
        self._atual: Optional[dict] = None
        self._reqs: dict[str, str] = {}
        self._num_visivel: Optional[bool] = None
        self._rotulo_pausa: Optional[str] = None
        self._max_rep = parametros.Parametros().max_repeticoes
        u = sessao.usuario
        self._setores = {TODOS: u.setor_ids, **{s["nome"]: [int(s["id"])] for s in u.setores}}

        self.grid_columnconfigure(0, weight=3, uniform="col")
        self.grid_columnconfigure(1, weight=2, uniform="col")
        self.grid_rowconfigure(1, weight=1)
        self._montar_topo()
        self._montar_atual()
        self._montar_listas()
        self._render_atual()
        self._estado_botoes()
        self._atualizar()

    # =================================================================
    # Montagem
    # =================================================================
    def _montar_topo(self):
        t = ctk.CTkFrame(self, fg_color=T.BG_CARD, corner_radius=20,
                         border_width=2, border_color=T.BORDER)
        t.grid(row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=(16, 8))
        t.grid_columnconfigure(1, weight=1)
        u = self._s.usuario
        W.rotulo(t, f"◉  {self._s.guiche.upper()}", 22, "bold", T.NEON).grid(
            row=0, column=0, padx=24, pady=14, sticky="w")
        W.rotulo(t, f"{u.nome}  •  {'Gestor' if u.gestor else 'Atendente'}", 15,
                 cor=T.TXT_MUTED).grid(row=0, column=1, sticky="w", padx=8)
        self.lbl_painel = W.rotulo(t, "●  Painel: verificando", 14, "bold", T.TXT_MUTED,
                                   width=210, anchor="e")
        self.lbl_painel.grid(row=0, column=2, padx=12)
        self.btn_pausa = W.botao(t, "Pausar", self._pausar, icone="pause", height=42,
                                 size=14, width=130)
        self.btn_pausa.grid(row=0, column=3, padx=6)
        self.btn_senha = W.botao(t, "Senha", self._trocar_senha, icone="key", height=42,
                                 size=14, width=120)
        self.btn_senha.grid(row=0, column=4, padx=6)
        self.btn_sair = W.botao(t, "Sair", self._sair, perigo=True, icone="power", height=42,
                                size=14, width=110)
        self.btn_sair.grid(row=0, column=5, padx=(6, 24))

    def _montar_atual(self):
        c = W.card(self)
        c.grid(row=1, column=0, sticky="nsew", padx=(20, 8), pady=(8, 20))
        c.grid_propagate(False)
        c.grid_columnconfigure((0, 1), weight=1, uniform="a")
        c.grid_rowconfigure(1, weight=1)
        px = 28

        W.rotulo(c, "SENHA ATUAL", 15, "bold", T.TXT_MUTED).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=px, pady=(22, 0))

        centro = ctk.CTkFrame(c, fg_color="transparent", height=230)
        centro.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=px, pady=8)
        centro.grid_propagate(False)
        centro.grid_columnconfigure(0, weight=1)
        centro.grid_rowconfigure(0, weight=1, minsize=150)
        self.lbl_vazio = ctk.CTkLabel(centro, text="", image=icone("megaphone", 88, T.TXT_OFF))
        self.lbl_vazio.grid(row=0, column=0)
        self.lbl_numero = W.rotulo(centro, "", 110, "bold", T.NEON)
        self.lbl_numero.grid(row=0, column=0)
        self.lbl_info = W.rotulo(centro, "", 20, "bold", height=30)
        self.lbl_info.grid(row=1, column=0, sticky="ew")
        self.lbl_detalhe = W.rotulo(centro, "", 15, cor=T.TXT_MUTED, height=26)
        self.lbl_detalhe.grid(row=2, column=0, sticky="ew", pady=(2, 8))

        sel = ctk.CTkFrame(c, fg_color="transparent")
        sel.grid(row=2, column=0, columnspan=2, sticky="ew", padx=px, pady=(0, 10))
        sel.grid_columnconfigure(1, weight=1)
        W.rotulo(sel, "Chamar de:", 14, "bold").grid(row=0, column=0, padx=(0, 12))
        self.opt_setor = W.opcoes(sel, list(self._setores), width=300)
        self.opt_setor.grid(row=0, column=1, sticky="ew")
        self.opt_setor.set(TODOS)

        self.btn_chamar = W.botao(c, "CHAMAR PRÓXIMA", self._chamar, primario=True,
                                  icone="megaphone", height=66, size=20)
        self.btn_chamar.grid(row=3, column=0, columnspan=2, sticky="ew", padx=px, pady=6)
        self.btn_repetir = W.botao(c, "Chamar novamente", self._repetir, icone="repeat")
        self.btn_repetir.grid(row=4, column=0, sticky="ew", padx=(px, 6), pady=6)
        self.btn_iniciar = W.botao(c, "Iniciar atendimento", self._iniciar, icone="play")
        self.btn_iniciar.grid(row=4, column=1, sticky="ew", padx=(6, px), pady=6)
        self.btn_ausente = W.botao(c, "Ausente", self._ausente, perigo=True, icone="ban")
        self.btn_ausente.grid(row=5, column=0, sticky="ew", padx=(px, 6), pady=6)
        self.btn_finalizar = W.botao(c, "Finalizar", self._finalizar, primario=True,
                                     icone="check")
        self.btn_finalizar.grid(row=5, column=1, sticky="ew", padx=(6, px), pady=6)

        self.lbl_msg = W.rotulo(c, "", 14, "bold", T.TXT_MUTED, height=40, wraplength=640)
        self.lbl_msg.grid(row=6, column=0, columnspan=2, sticky="ew", padx=px, pady=(4, 18))

    def _montar_listas(self):
        col = ctk.CTkFrame(self, fg_color="transparent")
        col.grid(row=1, column=1, sticky="nsew", padx=(8, 20), pady=(8, 20))
        col.grid_propagate(False)
        col.grid_columnconfigure(0, weight=1)
        col.grid_rowconfigure(0, weight=3, uniform="lst")
        col.grid_rowconfigure(1, weight=2, uniform="lst")
        self.lbl_fila, self.lst_fila, self._car_fila = self._card_lista(
            col, 0, "FILA DE ESPERA", (0, 8), None)
        self.lbl_aus, self.lst_aus, self._car_aus = self._card_lista(
            col, 1, "AUSENTES DE HOJE", (8, 0), self._reativar)

    def _card_lista(self, parent, row, titulo, pady, reativar_cb):
        c = W.card(parent)
        c.grid(row=row, column=0, sticky="nsew", pady=pady)
        c.grid_propagate(False)
        c.grid_columnconfigure(0, weight=1)
        c.grid_rowconfigure(1, weight=1)
        lbl = W.rotulo(c, titulo, 15, "bold", T.TXT_MUTED, anchor="w")
        lbl.grid(row=0, column=0, sticky="ew", padx=22, pady=(18, 6))
        lst = W.ListaSenhas(c, UI.max_itens_lista, reativar_cb)
        lst.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 14))
        carregando = W.rotulo(lst, _CARREGANDO, 14, cor=T.TXT_MUTED)
        carregando.pack(pady=16)
        return lbl, lst, carregando

    # =================================================================
    # API (chamada pelo App)
    # =================================================================
    def quando_pronto(self, cb: Callable[[], None]) -> None:
        """cb() quando a tela tiver conteúdo real (imediato se já tiver)."""
        if self._pronto:
            cb()
        else:
            self._ao_pronto.append(cb)

    def _sinalizar_pronto(self) -> None:
        if self._pronto:
            return
        self._pronto = True
        cbs, self._ao_pronto = self._ao_pronto, []
        for cb in cbs:
            self.after_idle(cb)

    def set_painel(self, online: bool) -> None:
        if self._ativo:
            W.configurar(self.lbl_painel,
                         text="●  Painel online" if online else "●  Painel OFFLINE",
                         text_color=T.NEON if online else T.DANGER)

    def encerrar(self) -> None:
        self._ativo = False
        self._ao_pronto.clear()
        if self._job:
            self.after_cancel(self._job)
            self._job = None

    # =================================================================
    # Atualização
    # =================================================================
    def _atualizar(self):
        self._job = None
        if not self._ativo:
            return
        if self._atualizando:
            self._pendente = True
            return
        self._atualizando = True
        ids, g, u = self._s.usuario.setor_ids, self._s.guiche_id, self._s.usuario.id

        def tarefa():
            return (fila_service.atendimento_aberto(g, u), fila_service.listar_fila(ids),
                    fila_service.listar_ausentes(ids), parametros.obter().max_repeticoes)

        self._bg(tarefa, self._ao_dados, self._ao_falha_dados)

    def _atualizar_agora(self):
        if self._job:
            self.after_cancel(self._job)
            self._job = None
        self._atualizar()

    def _primeiros_dados(self):
        self._carregado = True
        self._car_fila.destroy()
        self._car_aus.destroy()

    def _ao_dados(self, r):
        self._atualizando = False
        if not self._ativo:
            return
        atual, fila, ausentes, self._max_rep = r
        if not self._ocupado:
            self._atual = atual
        if self._offline:
            self._offline = False
            self._msg("")
        if not self._carregado:
            self._primeiros_dados()
        self._render_atual()
        W.configurar(self.lbl_fila, text=f"FILA DE ESPERA  ({len(fila)})")
        self.lst_fila.mostrar(fila)
        W.configurar(self.lbl_aus, text=f"AUSENTES DE HOJE  ({len(ausentes)})")
        self.lst_aus.mostrar(ausentes)
        self._estado_botoes()
        self._sinalizar_pronto()
        self._proximo()

    def _ao_falha_dados(self, exc):
        self._atualizando = False
        if not self._ativo:
            return
        self._offline = True
        self._msg(f"⚠ {descrever_erro(exc)} Tentando novamente...", T.WARN)
        self._sinalizar_pronto()
        self._proximo()

    def _proximo(self):
        if self._pendente:
            self._pendente = False
            self._atualizar()
        elif self._ativo and not self._job:
            self._job = self.after(UI.atualizar_ms, self._atualizar)

    # =================================================================
    # Renderização
    # =================================================================
    def _mostrar_numero(self, numero: bool):
        if self._num_visivel == numero:
            return
        self._num_visivel = numero
        if numero:
            self.lbl_vazio.grid_remove()
            self.lbl_numero.grid()
        else:
            self.lbl_numero.grid_remove()
            self.lbl_vazio.grid()

    def _render_atual(self):
        a = self._atual
        if not self._carregado:
            self._mostrar_numero(False)
            W.configurar(self.lbl_info, text=_CARREGANDO, text_color=T.TXT_MUTED)
            W.configurar(self.lbl_detalhe, text="Consultando o guichê e a fila.")
        elif a:
            self._mostrar_numero(True)
            W.configurar(self.lbl_numero, text=a["numero"], text_color=T.NEON)
            W.configurar(self.lbl_info, text=f"{a['setor']}  •  {a['prioridade']}",
                         text_color=T.TXT)
            if a["status"] == "chamando":
                det = (f"Chamando desde {a['chamada_em']:%H:%M}  •  "
                       f"repetições {a['repeticoes']}/{self._max_rep}")
            else:
                det = f"Em atendimento desde {a['atendimento_em']:%H:%M}"
            W.configurar(self.lbl_detalhe, text=det)
        elif self._s.pausada:
            self._mostrar_numero(True)
            W.configurar(self.lbl_numero, text="PAUSA", text_color=T.WARN)
            W.configurar(self.lbl_info, text="Guichê em pausa", text_color=T.TXT)
            W.configurar(self.lbl_detalhe, text="Clique em Retomar para voltar a chamar.")
        else:
            self._mostrar_numero(False)
            W.configurar(self.lbl_info, text="Guichê livre", text_color=T.TXT_MUTED)
            W.configurar(self.lbl_detalhe, text="Nenhuma senha em atendimento.")

    def _estado_botoes(self):
        a = self._atual
        st = a["status"] if a else None
        pausa = self._s.pausada
        pronto = self._carregado
        estados = {
            self.btn_chamar: pronto and not a and not pausa,
            self.btn_repetir: pronto and st == "chamando",
            self.btn_iniciar: pronto and st == "chamando",
            self.btn_ausente: pronto and st == "chamando",
            self.btn_finalizar: pronto and st == "em_atendimento",
            self.btn_pausa: pronto and (pausa or not a),
            self.btn_sair: not a,
            self.btn_senha: True,
        }
        for btn, on in estados.items():
            W.habilitar(btn, on)
        W.configurar(self.opt_setor,
                     state="normal" if pronto and not a and not pausa else "disabled")
        texto, ico = ("Retomar", "play") if pausa else ("Pausar", "pause")
        if self._rotulo_pausa != texto:
            self._rotulo_pausa = texto
            W.definir(self.btn_pausa, texto, ico)

    def _msg(self, texto: str, cor: str = T.TXT_MUTED):
        W.configurar(self.lbl_msg, text=texto, text_color=cor)

    # =================================================================
    # Ações
    # =================================================================
    def _liberar(self):
        self._ocupado = False
        self._render_atual()
        self._estado_botoes()

    def _acao(self, chave: str, func: Callable[[str], Optional[dict]], msg_ok: str):
        if self._ocupado or not self._ativo or not self._carregado:
            return
        req = self._reqs.setdefault(chave, str(uuid.uuid4()))
        self._ocupado = True

        def ok(res):
            self._reqs.pop(chave, None)
            if not self._ativo:
                return
            self._atual = res if res and res["status"] in fila_service.STATUS_ABERTOS else None
            self._liberar()
            if chave == "chamar" and res is None:
                self._msg("Nenhuma senha aguardando nos setores selecionados.", T.WARN)
            else:
                self._msg(msg_ok, T.NEON)
            self._atualizar_agora()

        def falha(exc):
            if isinstance(exc, RegraViolada) or not eh_erro_rede(exc):
                self._reqs.pop(chave, None)
            if not self._ativo:
                return
            self._ocupado = False
            msg = str(exc) if isinstance(exc, (RegraViolada, ErroSessao)) else descrever_erro(exc)
            self._msg(f"✖ {msg}", T.DANGER)
            self._atualizar_agora()

        self._bg(lambda: func(req), ok, falha)

    def _ids(self):
        return self._s.guiche_id, self._s.usuario.id

    def _chamar(self):
        setores = self._setores.get(self.opt_setor.get(), self._s.usuario.setor_ids)
        g, u = self._ids()
        self._acao("chamar", lambda r: fila_service.chamar_proxima(setores, g, u, r),
                   "✔ Senha chamada no painel.")

    def _sobre_atual(self, nome: str, func, msg: str):
        if not self._atual:
            return
        sid = self._atual["id"]
        g, u = self._ids()
        self._acao(f"{nome}:{sid}", lambda r: func(sid, g, u, r), msg)

    def _repetir(self):
        self._sobre_atual("repetir", fila_service.repetir_chamada, "✔ Chamada repetida no painel.")

    def _iniciar(self):
        self._sobre_atual("iniciar", fila_service.iniciar_atendimento, "✔ Atendimento iniciado.")

    def _finalizar(self):
        self._sobre_atual("finalizar", fila_service.finalizar_atendimento,
                          "✔ Atendimento finalizado.")

    def _ausente(self):
        self._sobre_atual("ausente", fila_service.marcar_ausente, "✔ Senha marcada como ausente.")

    def _reativar(self, senha_id: int):
        ids = self._s.usuario.setor_ids
        g, u = self._ids()
        atual = self._atual

        def func(r):
            fila_service.reativar(senha_id, ids, g, u, r)
            return atual

        self._acao(f"reativar:{senha_id}", func, "✔ Senha devolvida à fila.")

    def _pausar(self):
        if self._ocupado or not self._carregado:
            return
        pausada = self._s.pausada
        self._ocupado = True

        def ok(status):
            self._s.status = status
            if not self._ativo:
                return
            self._liberar()
            if pausada:
                self._msg("✔ Atendimento retomado.", T.NEON)
            else:
                self._msg("⏸ Guichê em pausa.", T.WARN)

        def falha(exc):
            if not self._ativo:
                return
            self._ocupado = False
            msg = str(exc) if isinstance(exc, ErroSessao) else descrever_erro(exc)
            self._msg(f"✖ {msg}", T.DANGER)

        func = sessao_svc.retomar if pausada else sessao_svc.pausar
        self._bg(lambda: func(self._s), ok, falha)

    def _trocar_senha(self):
        if not self._ocupado:
            self._on_trocar_senha()

    def _sair(self):
        if self._ocupado:
            return
        self._ocupado = True

        def ok(_r):
            self.encerrar()
            self._on_sair()

        def falha(exc):
            if not self._ativo:
                return
            self._ocupado = False
            msg = str(exc) if isinstance(exc, ErroSessao) else descrever_erro(exc)
            self._msg(f"✖ {msg}", T.DANGER)

        self._bg(lambda: sessao_svc.encerrar(self._s), ok, falha)
