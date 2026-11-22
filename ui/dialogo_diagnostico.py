"""
Diagnóstico de um painel em sobreposição (sem CTkToplevel, padrão do "Enviar mídia").
- Etapas pré-montadas: Aguardando → Verificando… → OK / Falha / Atenção / Não se aplica.
- A checagem roda em thread (tarefa.executar); o progresso chega ao Tk por tarefa.entregar.
- Barra geral determinada; resumo final no status; Copiar libera ao terminar.
- Pode ser fechado a qualquer momento (Esc/Fechar); entregas tardias são ignoradas.
"""
from tkinter import TclError
from typing import Callable, Optional

import customtkinter as ctk

from services import midias_service
from services.paineis_service import ETAPAS, Etapa
from ui import tarefa
from ui import theme as T
from ui import widgets as W
from ui.icones import icone
from ui.sobreposicao import Sobreposicao

_LARG = 560
_PONTOS_MS = 400
_VISUAL = {
    "pendente": ("refresh", T.TXT_MUTED, "Aguardando"),
    "andamento": ("refresh", T.NEON, "Verificando"),
    "ok": ("check", T.NEON, "OK"),
    "falha": ("x", T.DANGER, "Falha"),
    "aviso": ("help", T.WARN, "Atenção"),
    "na": ("ban", T.TXT_MUTED, "Não se aplica"),
}


class _LinhaEtapa(ctk.CTkFrame):
    def __init__(self, master, nome: str):
        super().__init__(master, fg_color=T.BG_ITEM, corner_radius=12)
        self.grid_columnconfigure(1, weight=1)
        self.estado = ""
        self._ico = ctk.CTkLabel(self, text="")
        self._ico.grid(row=0, column=0, rowspan=2, padx=12, pady=8)
        W.rotulo(self, nome, 14, "bold", anchor="w").grid(row=0, column=1, sticky="w", pady=(8, 0))
        self._det = W.rotulo(self, "", 12, cor=T.TXT_MUTED, anchor="w", justify="left",
                             wraplength=360)
        self._det.grid(row=1, column=1, sticky="w", pady=(0, 8))
        self._rot = W.rotulo(self, "", 12, "bold", width=110)
        self._rot.grid(row=0, column=2, rowspan=2, padx=12)
        self.definir("pendente", "")

    def definir(self, estado: str, detalhe: str) -> None:
        if estado != self.estado:
            ico, cor, rot = _VISUAL[estado]
            self._ico.configure(image=icone(ico, 20, cor))
            W.configurar(self._rot, text=rot, text_color=cor)
            self.estado = estado
        W.configurar(self._det, text=detalhe)

    def pontos(self, n: int) -> None:
        W.configurar(self._rot, text="Verificando" + "." * n)


class DialogoDiagnostico(Sobreposicao):
    def __init__(self, master, alvo: str, fn: Callable[[Callable], list[Etapa]]):
        super().__init__(master, "Diagnóstico do painel", alvo)
        self._alvo = alvo
        self._texto = ""
        self._atual: Optional[int] = None
        self._passo = 0
        self._job: Optional[str] = None
        self.ao_fechar(self._parar)

        lista = ctk.CTkFrame(self.corpo, fg_color="transparent", width=_LARG)
        lista.pack(fill="x")
        self._linhas = [_LinhaEtapa(lista, n) for n in ETAPAS]
        for linha in self._linhas:
            linha.pack(fill="x", pady=3)
        self._barra = ctk.CTkProgressBar(self.corpo, height=6, corner_radius=3,
                                         fg_color=T.BG_ITEM, progress_color=T.NEON)
        self._barra.set(0)
        self._barra.pack(fill="x", pady=(12, 0))
        barra = ctk.CTkFrame(self.corpo, fg_color="transparent")
        barra.pack(fill="x", pady=(8, 0))
        self._b_copiar = W.botao(barra, "Copiar resultado", self._copiar, icone="copy",
                                 height=36, size=12, width=160)
        self._b_copiar.pack(side="right")
        W.habilitar(self._b_copiar, False)

        self.rodape_padrao("Fechar", self.fechar, _LARG, cancelar=None)
        self.status("Verificando o painel… você pode fechar a qualquer momento.", T.NEON)
        self.exibir(foco=self.btn_ok)
        self._animar()
        rel = lambda i, e: tarefa.entregar(self._etapa, i, e)  # noqa: E731
        tarefa.executar(lambda: fn(rel), self.mostrar, self._erro, "paineis-diagnostico")

    def vivo(self) -> bool:
        return not self.fechado

    # ---- Animação --------------------------------------------------------
    def _animar(self) -> None:
        self._job = None
        if self.fechado:
            return
        self._passo = (self._passo + 1) % 4
        if self._atual is not None and self._linhas[self._atual].estado == "andamento":
            self._linhas[self._atual].pontos(self._passo)
        self._job = self.after(_PONTOS_MS, self._animar)

    def _parar(self) -> None:
        if self._job:
            try:
                self.after_cancel(self._job)
            except TclError:
                pass
            self._job = None

    # ---- Progresso (no Tk) -----------------------------------------------
    def _etapa(self, i: int, e: Optional[Etapa]) -> None:
        if self.fechado or i >= len(self._linhas):
            return
        if e is None:
            self._atual = i
            self._linhas[i].definir("andamento", "Em andamento…")
        else:
            self._linhas[i].definir(e.estado, e.detalhe)
            self._barra.set((i + 1) / len(self._linhas))

    def mostrar(self, etapas: list[Etapa]) -> None:
        if self.fechado:
            return
        self._parar()
        self._atual = None
        for linha, e in zip(self._linhas, etapas):
            linha.definir(e.estado, e.detalhe)
        self._barra.set(1)
        falhas = sum(e.estado == "falha" for e in etapas)
        avisos = sum(e.estado == "aviso" for e in etapas)
        if falhas:
            self._barra.configure(progress_color=T.DANGER)
            self.status(f"✖ Diagnóstico concluído: {falhas} falha(s). Veja os detalhes acima.",
                        T.DANGER)
        elif avisos:
            self._barra.configure(progress_color=T.WARN)
            self.status(f"⚠ Diagnóstico concluído com {avisos} ponto(s) de atenção.", T.WARN)
        else:
            self.status("✔ Tudo certo: o painel está acessível e sincronizado.", T.NEON)
        self._texto = f"Diagnóstico: {self._alvo}\n" + "\n".join(
            f"{i}. {e.nome}: {_VISUAL[e.estado][2]} - {e.detalhe}"
            for i, e in enumerate(etapas, 1))
        W.habilitar(self._b_copiar, True)

    def _erro(self, exc: Exception) -> None:
        if self.fechado:
            return
        self._parar()
        msg = midias_service.mensagem(exc)
        for linha in self._linhas:
            if linha.estado == "andamento":
                linha.definir("falha", msg)
            elif linha.estado == "pendente":
                linha.definir("na", "Não executado.")
        self._barra.configure(progress_color=T.DANGER)
        self._barra.set(1)
        self.status(f"✖ Não foi possível concluir o diagnóstico: {msg}", T.DANGER)
        self._texto = f"Diagnóstico: {self._alvo}\nErro: {msg}"
        W.habilitar(self._b_copiar, True)

    def _copiar(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self._texto)
        W.definir(self._b_copiar, texto="Copiado", icone="check")
