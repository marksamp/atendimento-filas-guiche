"""
Tela de progresso do cadastro (substitui o formulário no mesmo card):
arquivo, etapa atual, barra geral, características analisadas e uma linha por
painel (barra, %, MB enviados e velocidade).
Suavidade: sem barra indeterminada; um único timer (~30 fps) interpola todas as
barras até o alvo; textos só são reconfigurados quando mudam.
Lista: montada fora da tela e exibida de uma vez; acima de _MAX_SEM_ROLAGEM, rolagem.
Relator: callable thread-safe passado ao serviço; entrega no Tk via tarefa.entregar.
Checagens: inclui GIF (extensão/quadros) e o estado AVISO (⚠).
"""
import threading
import time
from typing import Callable, Optional

import customtkinter as ctk

from services import formato
from ui import info_midias, tarefa
from ui import theme as T
from ui import widgets as W

_INTERVALO = 0.25           # throttle dos eventos de envio por painel (s)
_TICK_MS = 33               # ~30 fps da interpolação
_SUAVIDADE = 0.18           # fração da distância percorrida por quadro
_PASSO_MIN = 0.003
_FASE_ANALISE = 0.30        # parte da barra geral reservada à análise
_MAX_SEM_ROLAGEM = 4
_ALTURA_LISTA = 260
_ESTADO = {True: ("✔", T.NEON), False: ("✖", T.DANGER), None: ("•", T.TXT_MUTED),
           info_midias.AVISO: ("⚠", T.WARN)}


class Relator:
    def __init__(self, destino: Callable[[str, tuple], None]):
        self._destino = destino
        self._ultimo: dict[str, float] = {}
        self._lock = threading.Lock()

    def __call__(self, evento: str, *dados) -> None:
        if evento == "envio":
            maquina, enviados, total = dados
            agora = time.monotonic()
            with self._lock:
                if enviados < total and agora - self._ultimo.get(maquina, 0) < _INTERVALO:
                    return
                self._ultimo[maquina] = agora
        tarefa.entregar(self._destino, evento, dados)


class _Cache:
    """Só reconfigura o widget quando algum valor mudou."""

    def __init__(self, widget):
        self.w = widget
        self._v: dict = {}

    def set(self, **kw) -> None:
        novos = {k: v for k, v in kw.items() if self._v.get(k) != v}
        if novos:
            self._v.update(novos)
            self.w.configure(**novos)


class _Suave:
    """Barra que desliza até o alvo; avançada pelo timer do ProgressoEnvio."""

    def __init__(self, barra: ctk.CTkProgressBar):
        self.b = barra
        self.atual = 0.0
        self.alvo = 0.0
        barra.set(0)

    def zerar(self) -> None:
        self.atual = self.alvo = 0.0
        self.b.set(0)

    def passo(self) -> None:
        d = self.alvo - self.atual
        if d == 0:
            return
        if abs(d) <= _PASSO_MIN:
            self.atual = self.alvo
        else:
            self.atual += max(abs(d) * _SUAVIDADE, _PASSO_MIN) * (1 if d > 0 else -1)
        self.b.set(self.atual)


class _Linha(ctk.CTkFrame):
    def __init__(self, master, maquina: str):
        super().__init__(master, fg_color=T.BG_ITEM, corner_radius=12)
        self.grid_columnconfigure(0, weight=1)
        self._t0: Optional[float] = None
        self._ultimo = 0
        self.fim = False
        W.rotulo(self, maquina, 13, "bold", anchor="w").grid(
            row=0, column=0, sticky="w", padx=12, pady=(8, 2))
        self._pct = _Cache(W.rotulo(self, "0%", 13, "bold", T.NEON, anchor="e", width=56))
        self._pct.w.grid(row=0, column=1, sticky="e", padx=12, pady=(8, 2))
        barra = ctk.CTkProgressBar(self, height=8, corner_radius=4, fg_color=T.BG_APP,
                                   progress_color=T.NEON)
        barra.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12)
        self.barra = _Suave(barra)
        self._det = _Cache(W.rotulo(self, "Aguardando…", 11, cor=T.TXT_MUTED, anchor="w"))
        self._det.w.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=(2, 8))

    @property
    def frac(self) -> float:
        return 1.0 if self.fim else self.barra.alvo

    def progresso(self, enviados: int, total: int) -> None:
        agora = time.monotonic()
        if self._t0 is None or enviados < self._ultimo:      # nova tentativa reinicia
            self._t0 = agora
        self._ultimo = enviados
        frac = min(1.0, enviados / total) if total else 1.0
        self.barra.alvo = frac
        self._pct.set(text=f"{frac * 100:.0f}%")
        if enviados >= total:
            txt = "Aguardando confirmação do painel…"
        else:
            dt = agora - self._t0
            vel = f" • {formato.mb(enviados / dt)}/s" if dt > 0.5 else ""
            txt = f"{formato.mb(enviados)} de {formato.mb(total)}{vel}"
        self._det.set(text=txt)

    def ok(self, novo: bool) -> None:
        self.fim = True
        self.barra.alvo = 1.0
        self._pct.set(text="100%")
        self._det.set(text="✔ Recebido." if novo else "✔ O painel já tinha o arquivo.",
                      text_color=T.NEON)

    def falha(self, msg: str) -> None:
        self.fim = True
        self.barra.b.configure(progress_color=T.DANGER)
        self._pct.set(text="✖", text_color=T.DANGER)
        self._det.set(text=f"✖ {msg}"[:90], text_color=T.DANGER)


class ProgressoEnvio(ctk.CTkFrame):
    def __init__(self, master, largura: int):
        super().__init__(master, fg_color="transparent", width=largura)
        self.grid_columnconfigure(0, weight=1)
        self._largura = largura
        self._linhas: dict[str, _Linha] = {}
        self._lista: Optional[ctk.CTkFrame] = None
        self._analise = True
        self._tick_id: Optional[str] = None

        topo = ctk.CTkFrame(self, fg_color=T.BG_ITEM, corner_radius=12)
        topo.grid(row=0, column=0, sticky="ew")
        topo.grid_columnconfigure(0, weight=1)
        W.rotulo(topo, "Arquivo", 12, "bold", T.NEON, anchor="w").grid(
            row=0, column=0, sticky="w", padx=14, pady=(10, 0))
        self._arquivo = _Cache(W.rotulo(topo, "", 14, "bold", anchor="w", width=largura - 28))
        self._arquivo.w.grid(row=1, column=0, sticky="w", padx=14)
        self._checks = ctk.CTkFrame(topo, fg_color="transparent")
        self._checks.grid(row=2, column=0, sticky="ew", padx=14, pady=(4, 10))

        self._etapa = _Cache(W.rotulo(self, "", 13, "bold", T.TXT, anchor="w", width=largura))
        self._etapa.w.grid(row=1, column=0, sticky="w", pady=(12, 2))
        barra = ctk.CTkProgressBar(self, mode="determinate", height=6, corner_radius=3,
                                   fg_color=T.BG_ITEM, progress_color=T.NEON, width=largura)
        barra.grid(row=2, column=0, sticky="ew", pady=(2, 8))
        self._geral = _Suave(barra)

        self._vazio = W.rotulo(self, "Os painéis aparecem aqui durante o envio.", 12,
                               cor=T.TXT_MUTED)
        self._vazio.grid(row=3, column=0, pady=16)

    # ---- API -----------------------------------------------------------------
    def iniciar(self, nome_arquivo: str) -> None:
        if self._lista is not None:
            self._lista.destroy()
            self._lista = None
        self._linhas.clear()
        for w in self._checks.winfo_children():
            w.destroy()
        self._vazio.grid()
        self._analise = True
        self._geral.zerar()
        self._arquivo.set(text=nome_arquivo)
        self._etapa.set(text="Iniciando…", text_color=T.TXT)
        self._ligar_tick()

    def parar(self) -> None:
        """Fim do processo: leva a barra geral a 100% (o timer termina a animação)."""
        self._analise = False
        if not any(l.barra.b.cget("progress_color") == T.DANGER for l in self._linhas.values()):
            self._geral.alvo = 1.0

    def concluir(self, texto: str, cor: str) -> None:
        """Mensagem final única (na linha de etapa)."""
        self.parar()
        self._etapa.set(text=texto, text_color=cor)

    def evento(self, evento: str, dados: tuple) -> None:
        if evento == "etapa":
            self._etapa.set(text=dados[0])
        elif evento == "analisado":
            self._analisado(dados[0])
        elif evento == "destinos":
            self._destinos(dados[0])
        elif dados and dados[0] in self._linhas:
            linha = self._linhas[dados[0]]
            if evento == "envio":
                linha.progresso(dados[1], dados[2])
            elif evento == "recebido":
                linha.ok(dados[1])
            elif evento == "falha":
                linha.falha(dados[1])
            self._atualizar_geral()

    # ---- Internos ------------------------------------------------------------
    def _destinos(self, maquinas) -> None:
        self._analise = False
        self._geral.alvo = max(self._geral.alvo, _FASE_ANALISE)
        self._etapa.set(text=f"Enviando a {len(maquinas)} painel(is)…")
        rolar = len(maquinas) > _MAX_SEM_ROLAGEM
        if rolar:
            self._lista = W.ListaRolavel(self, height=_ALTURA_LISTA, width=self._largura - 20)
        else:
            self._lista = ctk.CTkFrame(self, fg_color="transparent")
        for maquina in maquinas:
            linha = _Linha(self._lista, maquina)
            linha.pack(fill="x", pady=3, padx=(0, 6) if rolar else 0)
            self._linhas[maquina] = linha
        self._vazio.grid_remove()
        self._lista.grid(row=3, column=0, sticky="ew")
        if rolar:
            self._lista.ajustar_barra()

    def _atualizar_geral(self) -> None:
        if not self._linhas:
            return
        media = sum(l.frac for l in self._linhas.values()) / len(self._linhas)
        self._geral.alvo = _FASE_ANALISE + (1 - _FASE_ANALISE) * media

    def _analisado(self, arq) -> None:
        if self._checks.winfo_children():
            return
        for texto, estado in info_midias.verificar(arq.tipo, arq.tamanho, arq.largura,
                                                   arq.altura, arq.duracao_video,
                                                   bool(arq.temporario), arq.extensao,
                                                   getattr(arq, "quadros", None)):
            simbolo, cor = _ESTADO.get(estado, _ESTADO[None])
            W.rotulo(self._checks, f"{simbolo} {texto}", 12, cor=cor, anchor="w").pack(
                anchor="w")

    # ---- Timer único de animação ---------------------------------------------
    def _ligar_tick(self) -> None:
        if self._tick_id is None:
            self._tick_id = self.after(_TICK_MS, self._tick)

    def _tick(self) -> None:
        self._tick_id = None
        try:
            if not self.winfo_exists():
                return
        except Exception:  # noqa: BLE001
            return
        if self._analise:                       # avanço assintótico durante a análise
            self._geral.alvo += (_FASE_ANALISE * 0.95 - self._geral.alvo) * 0.015
        self._geral.passo()
        for linha in self._linhas.values():
            linha.barra.passo()
        self._tick_id = self.after(_TICK_MS, self._tick)

    def destroy(self) -> None:
        if self._tick_id is not None:
            try:
                self.after_cancel(self._tick_id)
            except Exception:  # noqa: BLE001
                pass
            self._tick_id = None
        super().destroy()
