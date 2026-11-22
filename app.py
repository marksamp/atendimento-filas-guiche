"""
Janela principal e navegação: Config → Login → (Troca de senha) → Atendimento.
Gestor: barra fixa "Menu Gestão" no topo (Atendimento / Mensagens do letreiro /
Mídias do painel / Setores / Guichês / Usuários). Não gestor: só Atendimento e troca
de senha (nada de gestão é criado).
Transição sem flash (TELA DE LOADING):
  1. loading opaco cobre a janela (e invalida revelações pendentes);
  2. por baixo: buffer (anti-flicker), monta/ergue a tela, menu e abrir();
  3. a tela avisa quando_pronto() (dados recebidos e renderizados, ok OU erro);
     sem quando_pronto → idle do Tk;
  4. layout estável: tamanhos iguais em duas leituras seguidas;
  5. folga (_ASSENTAR_MS) + tempo mínimo (_MINIMO_MS) → loading sai.
  Lento: aviso em _LENTO_MS; limite de segurança em _LIMITE_MS.
Primeiro acesso: janela nasce transparente e só aparece já com o loading.
Executor: tarefas em threads; callbacks sempre na thread da UI (fila + after).
"""
import logging
import queue
import time
from concurrent.futures import ThreadPoolExecutor
from tkinter import TclError
from typing import Callable, Optional

import customtkinter as ctk

from config import APP_NAME, VERSAO, DBSettings
from database import db, descrever_erro, testar_conexao
from services import config_store
from services import sessao as sessao_svc
from services.auth import Usuario
from services.sessao import ErroSessao, Heartbeat, Sessao
from ui import anti_flicker, sobreposicao
from ui import theme as T
from ui.menu_gestao import MenuGestao
from ui.tela_atendimento import TelaAtendimento
from ui.tela_carregando import TelaCarregando
from ui.tela_config import TelaConfig
from ui.tela_guiches import TelaGuiches
from ui.tela_letreiro import TelaLetreiro
from ui.tela_login import TelaLogin
from ui.tela_midias import TelaMidias
from ui.tela_setores import TelaSetores
from ui.tela_troca_senha import TelaTrocaSenha
from ui.tela_usuarios import TelaUsuarios

log = logging.getLogger(__name__)

_ASSENTAR_MS = 350          # folga estética após o layout estável
_MINIMO_MS = 600            # tempo mínimo do loading visível (evita "piscada")
_QUADRO_MS = 16             # intervalo entre medições do layout
_CICLOS_MAX = 15            # medições máximas até considerar estável
_WIDGETS_MAX = 400          # teto de widgets medidos por leitura
_LENTO_MS = 1500            # troca o texto para "Ainda carregando…"
_LIMITE_MS = 8000           # revela mesmo assim (a tela mostra o próprio estado)


class Executor:
    def __init__(self, root: ctk.CTk):
        self._root = root
        self._fila: "queue.Queue[tuple[Optional[Callable], object]]" = queue.Queue()
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bg")
        self._root.after(50, self._drenar)

    def executar(self, func: Callable, ok: Optional[Callable] = None,
                 falha: Optional[Callable] = None) -> None:
        def tarefa():
            try:
                res = func()
            except Exception as exc:  # noqa: BLE001
                log.debug("Tarefa falhou: %r", exc, exc_info=exc)
                self._fila.put((falha, exc))
            else:
                self._fila.put((ok, res))
        self._pool.submit(tarefa)

    def na_ui(self, func: Callable, *args) -> None:
        """Agenda func(*args) na thread da UI (seguro a partir de qualquer thread)."""
        self._fila.put((lambda _a: func(*args), None))

    def _drenar(self):
        try:
            while True:
                cb, arg = self._fila.get_nowait()
                if cb:
                    try:
                        cb(arg)
                    except Exception:  # noqa: BLE001
                        log.exception("Erro em callback da UI.")
        except queue.Empty:
            pass
        self._root.after(50, self._drenar)

    def desligar(self):
        self._pool.shutdown(wait=False, cancel_futures=True)


class App(ctk.CTk):
    def __init__(self):
        super().__init__(fg_color=T.BG_APP)
        self.attributes("-alpha", 0.0)          # nada aparece antes do loading
        self.title(f"Guichê de Atendimento • v{VERSAO}")
        self.geometry("1366x820")
        self.minsize(1180, 760)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)     # linha 0 = menu do gestor

        self.bg = Executor(self)
        self._tela: Optional[ctk.CTkFrame] = None
        self._seq = 0
        self._revelado = 0
        self._inicio_loading = time.monotonic()
        self.sessao: Optional[Sessao] = None
        self.heartbeat: Optional[Heartbeat] = None
        self.tela_atend: Optional[TelaAtendimento] = None
        self.tela_letreiro: Optional[TelaLetreiro] = None
        self.tela_midias: Optional[TelaMidias] = None
        self.tela_setores: Optional[TelaSetores] = None
        self.tela_guiches: Optional[TelaGuiches] = None
        self.tela_usuarios: Optional[TelaUsuarios] = None
        self.menu: Optional[MenuGestao] = None

        self._loading = TelaCarregando(self)
        self._exibir_loading("Iniciando…")

        self.tela_config = TelaConfig(self, self.bg.executar, self._conectar, self._ir_login)
        self.tela_login = TelaLogin(self, self.bg.executar, self._logou, self.abrir_config)
        self.tela_troca = TelaTrocaSenha(self, self.bg.executar)

        self.protocol("WM_DELETE_WINDOW", self._fechar)
        self.after(10, self._iniciar)

    def report_callback_exception(self, exc, val, tb):
        log.error("Erro não tratado na UI.", exc_info=(exc, val, tb))

    # ---- Loading -----------------------------------------------------
    def _exibir_loading(self, texto: str):
        """Cobre a janela e invalida qualquer revelação pendente."""
        self._seq += 1
        if not self._loading.visivel:
            self._inicio_loading = time.monotonic()
        sobreposicao.reter(True)
        self._loading.mostrar(texto)

    def _avisar_lento(self, seq: int):
        if seq == self._seq and self._revelado != seq and self._loading.visivel:
            self._loading.mostrar("Ainda carregando…")

    # ---- Navegação com tela de loading --------------------------------
    def _ajustar_buffer(self):
        """Double buffering em tudo, exceto na tela com animação em Canvas."""
        anti_flicker.preferir(self, self._tela is None or self._tela is not self.tela_letreiro)

    def _mostrar(self, tela: ctk.CTkFrame, ao_exibir: Optional[Callable[[], None]] = None,
                 texto: str = "Carregando…"):
        if self._tela is tela and not self._loading.visivel:
            if ao_exibir:
                ao_exibir()
            self._marcar(tela)
            return
        self._exibir_loading(texto)
        seq = self._seq
        if self._tela is not tela:
            anterior, self._tela = self._tela, tela
            self._ajustar_buffer()              # repintura do estilo fica sob o loading
            if not tela.winfo_manager():
                tela.grid(row=1, column=0, sticky="nsew")
            tela.tkraise()
            if anterior is not None and hasattr(anterior, "ocultar"):
                anterior.ocultar()
        if ao_exibir:
            ao_exibir()
        self._marcar(tela)
        self._loading.lift()

        self.after(_LENTO_MS, lambda: self._avisar_lento(seq))
        self.after(_LIMITE_MS, lambda: self._revelar(seq, limite=True))
        pronto = getattr(tela, "quando_pronto", None)
        if pronto:
            pronto(lambda: self._revelar(seq))
        else:
            self.after_idle(lambda: self._revelar(seq))

    def _revelar(self, seq: int, limite: bool = False):
        if seq != self._seq or self._revelado == seq:
            return
        self._revelado = seq
        if limite:
            log.warning("Tela não sinalizou prontidão em %d ms; revelando.", _LIMITE_MS)
        self._assentar(seq, None, 0)

    def _medir(self) -> tuple:
        fila = [w for w in (self.menu, self._tela) if w is not None]
        medidas = []
        while fila and len(medidas) < _WIDGETS_MAX:
            w = fila.pop(0)
            if not w.winfo_ismapped():
                continue
            medidas.append((w.winfo_width(), w.winfo_height()))
            fila.extend(w.winfo_children())
        return tuple(medidas)

    def _assentar(self, seq: int, anterior: Optional[tuple], ciclo: int):
        """Espera o layout parar de mudar (duas leituras iguais)."""
        if seq != self._seq:
            return
        try:
            self.update_idletasks()
            medida = self._medir()
        except TclError:
            return
        if medida != anterior and ciclo < _CICLOS_MAX:
            self.after(_QUADRO_MS, lambda: self._assentar(seq, medida, ciclo + 1))
            return
        decorrido = int((time.monotonic() - self._inicio_loading) * 1000)
        espera = max(_ASSENTAR_MS, _MINIMO_MS - decorrido)
        self.after(espera, lambda: self._concluir(seq))

    def _concluir(self, seq: int):
        if seq != self._seq:
            return
        try:
            self.update_idletasks()
        except TclError:
            return
        self._loading.esconder()
        sobreposicao.reter(False)
        sobreposicao.reerguer()

    def _marcar(self, tela: ctk.CTkFrame):
        if self.menu:
            self.menu.marcar("atend" if tela is self.tela_atend else
                             "letreiro" if tela is self.tela_letreiro else
                             "midias" if tela is self.tela_midias else
                             "setores" if tela is self.tela_setores else
                             "guiches" if tela is self.tela_guiches else
                             "usuarios" if tela is self.tela_usuarios else None)

    def _iniciar(self):
        self.update_idletasks()
        self.attributes("-alpha", 1.0)          # aparece já com o loading pintado
        s, completo = config_store.carregar()
        if completo:
            self._conectar(s)
        else:
            self.abrir_config(s, False, "Configure a conexão com o banco de dados.")

    def abrir_config(self, s: Optional[DBSettings] = None, cancelavel: bool = True,
                     aviso: str = ""):
        s = s or db.settings
        self.tela_config.preencher(s, bool(s) and not s.validar(), cancelavel, aviso)
        self._mostrar(self.tela_config)

    def _conectar(self, s: DBSettings):
        """Só o loading: o login é revelado depois, já com os guichês."""
        self.tela_login.aguardando("Conectando ao banco de dados...")
        self._exibir_loading("Conectando…")

        def tarefa():
            testar_conexao(s)
            db.configure(s)

        self.bg.executar(tarefa, lambda _r: self._ir_login(),
                         lambda e: self.abrir_config(s, False, f"✖ {descrever_erro(e, s)}"))

    def _ir_login(self, msg: str = "", cor: str = T.TXT_MUTED):
        if db.settings is None:
            self.abrir_config(None, False)
            return
        self.tela_login.preparar(msg, cor)
        self._mostrar(self.tela_login)

    # ---- Menu do gestor ----------------------------------------------
    def _montar_menu(self):
        self.menu = MenuGestao(self, [
            ("atend", "Atendimento", "monitor", self._voltar_atendimento),
            ("letreiro", "Mensagens do letreiro", "message-square", self._abrir_letreiro),
            ("midias", "Mídias do painel", "image", self._abrir_midias),
            ("setores", "Setores", "copy", self._abrir_setores),
            ("guiches", "Guichês", "counter", self._abrir_guiches),
            ("usuarios", "Usuários", "users", self._abrir_usuarios),
        ])

    def _exibir_menu(self):
        if self.menu and not self.menu.winfo_manager():
            self.menu.grid(row=0, column=0, sticky="ew")

    def _remover_menu(self):
        if self.menu:
            self.menu.destroy()
            self.menu = None

    def _gestor(self) -> bool:
        return bool(self.sessao and self.sessao.usuario.gestor)

    def _abrir_letreiro(self):
        if not self._gestor():
            return
        if self.tela_letreiro is None:
            self.tela_letreiro = TelaLetreiro(self, self.bg.executar, self.sessao,
                                              self._voltar_atendimento)
        self._mostrar(self.tela_letreiro, self.tela_letreiro.abrir)

    def _abrir_midias(self):
        if not self._gestor():
            return
        if self.tela_midias is None:
            self.tela_midias = TelaMidias(self, self.sessao.usuario)
        self._mostrar(self.tela_midias, self.tela_midias.abrir)

    def _abrir_setores(self):
        if not self._gestor():
            return
        if self.tela_setores is None:
            self.tela_setores = TelaSetores(self, self.sessao.usuario)
        self._mostrar(self.tela_setores, self.tela_setores.abrir)

    def _abrir_guiches(self):
        if not self._gestor():
            return
        if self.tela_guiches is None:
            self.tela_guiches = TelaGuiches(self, self.sessao.usuario)
        self._mostrar(self.tela_guiches, self.tela_guiches.abrir)

    def _abrir_usuarios(self):
        if not self._gestor():
            return
        if self.tela_usuarios is None:
            self.tela_usuarios = TelaUsuarios(self, self.sessao.usuario)
        self._mostrar(self.tela_usuarios, self.tela_usuarios.abrir)

    def _voltar_atendimento(self):
        if self.tela_atend:
            self._mostrar(self.tela_atend)

    # ---- Login / sessão ---------------------------------------------
    def _logou(self, usuario: Usuario, guiche_id: int):
        if usuario.trocar_senha:
            self.tela_troca.preparar(usuario, True,
                                     lambda: self._abrir_sessao(usuario, guiche_id),
                                     self._ir_login)
            self._mostrar(self.tela_troca)
        else:
            self._abrir_sessao(usuario, guiche_id)

    def _abrir_sessao(self, usuario: Usuario, guiche_id: int):
        self.tela_login.aguardando("Abrindo o guichê...")
        self._exibir_loading("Abrindo o guichê…")

        def falha(exc):
            msg = str(exc) if isinstance(exc, ErroSessao) else descrever_erro(exc)
            self._ir_login(f"✖ {msg}", T.DANGER)    # revela o login já pronto

        self.bg.executar(lambda: sessao_svc.abrir(usuario, guiche_id),
                         self._sessao_aberta, falha)

    def _sessao_aberta(self, sessao: Sessao):
        self.sessao = sessao
        self.tela_atend = TelaAtendimento(self, self.bg.executar, sessao,
                                          self._encerrar_sessao, self._troca_voluntaria)
        self.heartbeat = Heartbeat(
            sessao,
            ao_perder=lambda msg: self.bg.na_ui(self._sessao_perdida, msg),
            ao_painel=lambda on: self.bg.na_ui(self._painel, on),
        )
        self.heartbeat.iniciar()
        if sessao.usuario.gestor:
            self._montar_menu()
        self._mostrar(self.tela_atend, self._exibir_menu, "Abrindo o guichê…")

    def _painel(self, online: bool):
        if self.tela_atend:
            self.tela_atend.set_painel(online)

    def _troca_voluntaria(self):
        self.tela_troca.preparar(self.sessao.usuario, False, self._voltar_atendimento,
                                 self._voltar_atendimento)
        self._mostrar(self.tela_troca)

    def _descartar(self, tela: Optional[ctk.CTkFrame]):
        if tela is None:
            return
        tela.encerrar()
        if self._tela is tela:
            self._tela = None
        tela.destroy()

    def _limpar_sessao(self):
        self._exibir_loading("Encerrando…")
        if self.heartbeat:
            self.heartbeat.parar()
        self._remover_menu()
        self._descartar(self.tela_usuarios)
        self._descartar(self.tela_guiches)
        self._descartar(self.tela_setores)
        self._descartar(self.tela_midias)
        self._descartar(self.tela_letreiro)
        self._descartar(self.tela_atend)
        self.sessao = self.heartbeat = self.tela_atend = None
        self.tela_letreiro = self.tela_midias = self.tela_guiches = None
        self.tela_setores = self.tela_usuarios = None

    def _encerrar_sessao(self):
        self._limpar_sessao()
        self._ir_login("Sessão encerrada.", T.NEON)

    def _sessao_perdida(self, msg: str):
        if self.sessao:
            log.warning(msg)
            self._limpar_sessao()
            self._ir_login(f"✖ {msg}", T.DANGER)

    # ---- Encerramento -----------------------------------------------
    def _fechar(self):
        if self.sessao:
            if self.heartbeat:
                self.heartbeat.parar()
            try:
                sessao_svc.encerrar(self.sessao, forcar=True)
            except Exception as exc:  # noqa: BLE001
                log.warning("Não foi possível encerrar a sessão: %s", descrever_erro(exc))
        self.bg.desligar()
        self.destroy()
        log.info("%s finalizado.", APP_NAME)
