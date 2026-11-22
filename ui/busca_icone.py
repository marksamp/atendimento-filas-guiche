"""
Busca de ícones Tabler (embutida no formulário de setor).
- Filtra pelo nome (todos os termos), até _MAX resultados; debounce na digitação
  e só busca se o texto mudou (setas/Shift não disparam).
- Miniaturas geradas em segundo plano e recoloridas com cache (mesma imagem = sem redraw).
- Anti-flicker: botões só reconfigurados no que mudou (W.configurar) e repintura
  ignorada quando nada mudou.
- Anti-balanço: grade e texto informativo com tamanho fixo, dentro da largura
  da coluna do formulário (_LARG_GRADE <= 300).
- ao_escolher('tabler:<nome>'); ao_pronto() uma vez, na primeira carga (ok ou erro).
- colorir()/vazio() são reaproveitados na prévia e na lista de setores.
"""
import io
from functools import lru_cache
from typing import Callable, Optional

import customtkinter as ctk
from PIL import Image

from services import icone_png as gerador
from ui import tarefa
from ui import theme as T
from ui import widgets as W

_MAX, _COLS, _MINI, _ATRASO_MS = 24, 8, 22, 250
_BOTAO, _PAD = 32, 2
_LARG_GRADE = _COLS * (_BOTAO + 2 * _PAD) + 2 * _PAD          # 292 px
_INFO_MAX = 40


@lru_cache(maxsize=512)
def _png(nome: str) -> Optional[bytes]:
    return gerador.gerar_png(f"{gerador.PREFIXO_TABLER}{nome}")


@lru_cache(maxsize=512)
def colorir(png: Optional[bytes], cor: str, lado: int) -> Optional[ctk.CTkImage]:
    """PNG do contrato (branco + alfa) → CTkImage na cor (cacheado: mesmo objeto)."""
    if not png:
        return None
    with Image.open(io.BytesIO(png)) as im:
        alfa = im.convert("RGBA").getchannel("A")
    img = Image.new("RGBA", alfa.size, T.cor_segura(cor))
    img.putalpha(alfa)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(lado, lado))


@lru_cache(maxsize=16)
def vazio(lado: int) -> ctk.CTkImage:
    """Imagem transparente (CTk não limpa a imagem com None)."""
    img = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    return ctk.CTkImage(light_image=img, dark_image=img, size=(lado, lado))


def curto(texto: str, maximo: int) -> str:
    """Corta com reticências (texto longo não alarga o layout)."""
    return texto if len(texto) <= maximo else texto[:maximo - 1].rstrip() + "…"


def _filtrar(termo: str) -> list[str]:
    nomes = list(gerador._mapa())
    partes = termo.lower().split()
    achados = [n for n in nomes if all(p in n for p in partes)] if partes else nomes
    achados.sort(key=lambda n: (not partes or not n.startswith(partes[0]), len(n), n))
    return achados[:_MAX]


class BuscaIcone(ctk.CTkFrame):
    def __init__(self, master, ao_escolher: Callable[[str], None], cor: str = T.NEON,
                 ao_pronto: Optional[Callable[[], None]] = None):
        super().__init__(master, fg_color="transparent")
        self._cb = ao_escolher
        self._ao_pronto = ao_pronto
        self._cor = cor
        self._seq = 0
        self._agenda = None
        self._termo: Optional[str] = None
        self._sel: Optional[str] = None
        self._nomes: list[str] = []
        self._pngs: list[Optional[bytes]] = []
        self._pintado: Optional[tuple] = None
        self._vazio = vazio(_MINI)

        self._campo = ctk.CTkEntry(self, placeholder_text="Buscar ícone (ex.: heart, user)",
                                   height=36, font=T.font(13), fg_color=T.BG_ITEM,
                                   border_color=T.BORDER, text_color=T.TXT, corner_radius=10)
        self._campo.pack(fill="x")
        self._campo.bind("<KeyRelease>", self._digitado)
        linhas = (_MAX + _COLS - 1) // _COLS
        grade = ctk.CTkFrame(self, fg_color=T.BG_ITEM, corner_radius=12, width=_LARG_GRADE,
                             height=linhas * (_BOTAO + 2 * _PAD) + 2 * _PAD)
        grade.pack(anchor="w", pady=(8, 0))
        grade.grid_propagate(False)                 # tamanho fixo: nunca reflui
        self._botoes: list[ctk.CTkButton] = []
        for i in range(_MAX):
            b = ctk.CTkButton(grade, text="", width=_BOTAO, height=_BOTAO, corner_radius=8,
                              image=self._vazio, fg_color="transparent",
                              hover_color=T.BG_CARD_HOV, border_width=1,
                              border_color=T.BG_ITEM, state="disabled",
                              command=lambda i=i: self._escolher(i))
            b.grid(row=i // _COLS, column=i % _COLS, padx=_PAD, pady=_PAD)
            self._botoes.append(b)
        self._info = W.rotulo(self, "Carregando ícones…", 12, cor=T.TXT_MUTED, anchor="w",
                              width=_LARG_GRADE)
        self._info.pack(anchor="w", pady=(4, 0))
        self._buscar()

    # ---- API -----------------------------------------------------------
    def definir_cor(self, cor: str) -> None:
        if cor != self._cor:
            self._cor = cor
            self._pintar()

    def selecionar(self, icone: Optional[str]) -> None:
        nome = icone or ""
        sel = nome[len(gerador.PREFIXO_TABLER):] if nome.startswith(
            gerador.PREFIXO_TABLER) else None
        if sel != self._sel:
            self._sel = sel
            self._pintar()

    # ---- Busca ---------------------------------------------------------
    def _vivo(self) -> bool:
        try:
            return bool(self.winfo_exists())
        except Exception:  # noqa: BLE001
            return False

    def _digitado(self, _e=None) -> None:
        if self._agenda:
            self.after_cancel(self._agenda)
        self._agenda = self.after(_ATRASO_MS, self._buscar)

    def _buscar(self) -> None:
        self._agenda = None
        if not self._vivo():
            return
        termo = " ".join(self._campo.get().lower().split())
        if termo == self._termo:
            return
        self._termo = termo
        self._seq += 1
        seq = self._seq

        def tarefa_bg():
            nomes = _filtrar(termo)
            return seq, nomes, [_png(n) for n in nomes]

        tarefa.executar(tarefa_bg, self._recebido, self._falhou, "setores-icones")

    def _avisar_pronto(self) -> None:
        cb, self._ao_pronto = self._ao_pronto, None
        if cb:
            cb()

    def _falhou(self, _e) -> None:
        if self._vivo():
            W.configurar(self._info, text="Não foi possível carregar os ícones.")
            self._avisar_pronto()

    def _recebido(self, r: tuple) -> None:
        seq, nomes, pngs = r
        if seq != self._seq or not self._vivo():
            return
        self._nomes, self._pngs = nomes, pngs
        W.configurar(self._info,
                     text=f"{len(nomes)} ícone(s)" if nomes else "Nenhum ícone encontrado.")
        self._pintar()
        self._avisar_pronto()

    # ---- Desenho / escolha -----------------------------------------------
    def _pintar(self) -> None:
        estado = (tuple(self._nomes), self._cor, self._sel)
        if estado == self._pintado:
            return                                  # nada mudou: zero redesenho
        self._pintado = estado
        for i, b in enumerate(self._botoes):
            if i < len(self._nomes):
                img = colorir(self._pngs[i], self._cor, _MINI) or self._vazio
                sel = self._nomes[i] == self._sel
                W.configurar(b, image=img, state="normal",
                             border_color=T.NEON if sel else T.BG_ITEM)
            else:
                W.configurar(b, image=self._vazio, state="disabled", border_color=T.BG_ITEM)

    def _escolher(self, i: int) -> None:
        if i < len(self._nomes):
            self._sel = self._nomes[i]
            self._pintar()
            W.configurar(self._info, text=curto(self._sel, _INFO_MAX))
            self._cb(f"{gerador.PREFIXO_TABLER}{self._sel}")
