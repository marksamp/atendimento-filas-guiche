"""
Reenvio de mídias em sobreposição: explica a ação, pede confirmação, mostra o
progresso (thread + tarefa.entregar) e o resultado. Pode ser fechado durante o
reenvio: ele continua em segundo plano e o resultado chega por ao_fim.
"""
from typing import Callable

import customtkinter as ctk

from services import midias_service, paineis_service
from services.paineis_service import Painel
from ui import tarefa
from ui import theme as T
from ui import widgets as W
from ui.sobreposicao import Sobreposicao

_LARG = 520
_DESCRICAO = ("Copia para este painel as mídias ativas que estão faltando nele.\n\n"
              "• O Guichê não guarda arquivos: cada mídia é baixada de outro painel online "
              "que já a possua e enviada a este.\n"
              "• Mídias já presentes não são reenviadas e nada é apagado.\n"
              "• Pode levar alguns minutos, conforme o tamanho dos arquivos.")


class DialogoReenvio(Sobreposicao):
    def __init__(self, master, p: Painel, ao_fim: Callable[[str, bool, bool], None]):
        super().__init__(master, "Reenviar mídias", f"{p.maquina} • {p.endereco}")
        self._p = p
        self._ao_fim = ao_fim                     # (texto, sucesso, dialogo_fechado)
        self._rodando = False

        bloco = ctk.CTkFrame(self.corpo, fg_color=T.BG_ITEM, corner_radius=12, width=_LARG)
        bloco.pack(fill="x")
        W.rotulo(bloco, "O que esta ação faz", 13, "bold", T.NEON).pack(
            anchor="w", padx=14, pady=(10, 2))
        W.rotulo(bloco, _DESCRICAO, 12, cor=T.TXT_MUTED, justify="left", anchor="w",
                 wraplength=_LARG - 28).pack(anchor="w", padx=14, pady=(0, 10))
        self._etapa = W.rotulo(self.corpo, "", 13, "bold", anchor="w", width=_LARG)
        self._barra = ctk.CTkProgressBar(self.corpo, height=6, corner_radius=3,
                                         fg_color=T.BG_ITEM, progress_color=T.NEON)
        self._barra.set(0)
        self._resultado = W.rotulo(self.corpo, "", 12, cor=T.TXT_MUTED, justify="left",
                                   anchor="w", wraplength=_LARG)

        self.rodape_padrao("Iniciar reenvio", self._iniciar, _LARG)
        self.exibir(foco=self.btn_ok)

    def _iniciar(self) -> None:
        if self._rodando or self.fechado:
            return
        self._rodando = True
        W.habilitar(self.btn_ok, False)
        W.definir(self.btn_ok, "Reenviando…")
        self.btn_cancelar.configure(text="Fechar (o reenvio continua em segundo plano)")
        self.btn_cancelar.pack()
        self._resultado.pack_forget()
        self._etapa.pack(fill="x", pady=(12, 2))
        self._barra.configure(progress_color=T.NEON)
        self._barra.set(0)
        self._barra.pack(fill="x", pady=(2, 0))
        self._progresso("Conectando ao painel…", 0, 0)
        self.status("")
        rel = lambda t, f, n: tarefa.entregar(self._progresso, t, f, n)  # noqa: E731
        tarefa.executar(lambda: paineis_service.reenviar(self._p, rel), self._ok, self._erro,
                        "paineis-reenviar")

    def _progresso(self, texto: str, feitos: int, total: int) -> None:
        if self.fechado:
            return
        W.configurar(self._etapa, text=texto, text_color=T.TXT)
        if total:
            self._barra.set(feitos / total)

    def _finalizar(self, etapa: str, cor: str, detalhe: str) -> None:
        self._rodando = False
        self._barra.configure(progress_color=cor)
        self._barra.set(1)
        W.configurar(self._etapa, text=etapa, text_color=cor)
        W.configurar(self._resultado, text=detalhe)
        self._resultado.pack(fill="x", pady=(8, 0))
        W.habilitar(self.btn_ok, True)
        self.btn_cancelar.pack_forget()

    def _ok(self, texto: str) -> None:
        self._ao_fim(texto, True, self.fechado)
        if self.fechado:
            return
        falhou = "Falhas:" in texto
        self._finalizar("⚠ Reenvio concluído com falhas." if falhou else "✔ Reenvio concluído.",
                        T.WARN if falhou else T.NEON, texto)
        W.definir(self.btn_ok, "OK")
        self.btn_ok.configure(command=self.fechar)
        self._focar(self.btn_ok)

    def _erro(self, exc: Exception) -> None:
        msg = midias_service.mensagem(exc)
        self._ao_fim(msg, False, self.fechado)
        if self.fechado:
            return
        self._finalizar("✖ Não foi possível reenviar.", T.DANGER, msg)
        W.definir(self.btn_ok, "Tentar novamente")
        self.btn_ok.configure(command=self._iniciar)
        self.btn_cancelar.configure(text="Fechar")
        self.btn_cancelar.pack()
