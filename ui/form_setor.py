"""
Formulário de setor (cadastro/edição) em sobreposição, no padrão de FormUsuario.
- Nome, descrição, prefixo (1-2 letras), cor livre (SeletorCor) e ícone.
- Ícone: busca Tabler, arquivo do gestor (icone_png.gerar_png_arquivo) ou nenhum.
- Prévia ao vivo: barra na cor, prefixo e ícone recolorido (só quando algo mudou).
- Anti-flicker: só exibe após a grade de ícones e a prévia estarem prontas
  (ou _LIMITE_MS), evitando redesenho com o diálogo já visível.
- Anti-balanço: colunas uniformes, prévia com tamanho fixo, textos cortados e
  ícone sempre do mesmo tamanho (nada altera a geometria do diálogo).
- Na edição com ícone 'arquivo:', a prévia carrega o PNG gravado (sem reenvio).
- Validação local instantânea (setores_service.validar); erro fica no formulário.
- Salvar trava o formulário; erro destrava; sucesso fecha.
"""
from tkinter import filedialog
from typing import Callable, Optional

import customtkinter as ctk

from services import icone_png as gerador
from services import setores_service as svc
from ui import tarefa
from ui import theme as T
from ui import widgets as W
from ui.busca_icone import BuscaIcone, colorir, curto, vazio
from ui.seletor_cor import SeletorCor
from ui.sobreposicao import Sobreposicao

_LARG = 300
_PREVIA = 40
_ALT_PREVIA = 64
_NOME_MAX = 22
_LIMITE_MS = 800
_SUB = "Desativados não emitem senhas no Totem; as já emitidas continuam na fila."
_TIPOS = [("Imagens", " ".join(f"*{e}" for e in gerador.FORMATOS_ARQUIVO))]


class FormSetor(Sobreposicao):
    def __init__(self, master, valores: dict,
                 ao_salvar: Callable[[dict, "FormSetor"], None], editar: bool = False):
        super().__init__(master, "Editar setor" if editar else "Novo setor", _SUB)
        self._cb = ao_salvar
        self._icone: Optional[str] = valores.get("icone") or None
        self._png: Optional[bytes] = None          # PNG da prévia (e do 'arquivo:' novo)
        self._png_novo = False                     # True = arquivo escolhido agora
        self._seq_png = 0
        self._pendentes = 2                        # grade de ícones + prévia
        self._exibido = False
        self._ultima_previa: Optional[tuple] = None
        self._vazio = vazio(_PREVIA)
        cor = T.cor_segura(valores.get("cor"))

        c = self.corpo
        c.grid_columnconfigure((0, 1), weight=1, uniform="col")   # larguras iguais e fixas
        esq = ctk.CTkFrame(c, fg_color="transparent")
        esq.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        dir_ = ctk.CTkFrame(c, fg_color="transparent")
        dir_.grid(row=0, column=1, sticky="nsew", padx=(12, 0))

        # ---- Coluna esquerda: dados + cor ----------------------------------
        self._f_nome = self._campo(esq, "Nome", W.entrada(esq, "Ex.: Consultas", width=_LARG))
        self._f_nome.insert(0, valores.get("nome") or "")
        self._f_desc = self._campo(esq, "Descrição (opcional)",
                                   W.entrada(esq, "Texto exibido no Totem", width=_LARG))
        self._f_desc.insert(0, valores.get("descricao") or "")
        self._f_pref = self._campo(esq, "Prefixo", W.entrada(esq, "1 ou 2 letras", width=_LARG))
        self._f_pref.insert(0, valores.get("prefixo") or "")
        for f in (self._f_nome, self._f_pref):
            f.bind("<KeyRelease>", lambda _e: self._previa(), add="+")
        W.rotulo(esq, "Cor", 14, "bold").pack(anchor="w", pady=(8, 4))
        self._cor = SeletorCor(esq, cor, self._cor_mudou)
        self._cor.pack(anchor="w")

        # ---- Coluna direita: ícone + prévia --------------------------------
        W.rotulo(dir_, "Ícone", 14, "bold").pack(anchor="w", pady=(8, 4))
        self._busca = BuscaIcone(dir_, self._tabler, cor, ao_pronto=self._parte_pronta)
        self._busca.pack(fill="x")
        self._busca.selecionar(self._icone)
        acoes = ctk.CTkFrame(dir_, fg_color="transparent")
        acoes.pack(fill="x", pady=(8, 0))
        W.botao(acoes, "Escolher arquivo", self._arquivo, icone="image",
                height=36, size=12).pack(side="left")
        W.botao(acoes, "Sem ícone", self._sem_icone, icone="x",
                height=36, size=12).pack(side="left", padx=8)

        W.rotulo(dir_, "Prévia", 14, "bold").pack(anchor="w", pady=(12, 4))
        prev = ctk.CTkFrame(dir_, fg_color=T.BG_ITEM, corner_radius=12, height=_ALT_PREVIA)
        prev.pack(fill="x")
        prev.grid_propagate(False)                  # altura fixa: conteúdo não estica
        prev.grid_rowconfigure(0, weight=1)
        prev.grid_columnconfigure(2, weight=1)
        self._p_barra = ctk.CTkFrame(prev, width=6, height=44, corner_radius=3, fg_color=cor)
        self._p_barra.grid(row=0, column=0, padx=(10, 10))
        self._p_icone = ctk.CTkLabel(prev, text="", image=self._vazio, width=_PREVIA,
                                     height=_PREVIA)
        self._p_icone.grid(row=0, column=1)
        self._p_nome = W.rotulo(prev, "", 15, "bold", anchor="w", width=160)
        self._p_nome.grid(row=0, column=2, sticky="ew", padx=10)
        self._p_pref = W.rotulo(prev, "", 22, "bold", cor, width=90)
        self._p_pref.grid(row=0, column=3, padx=(0, 14))

        self.rodape_padrao("Salvar", self._salvar, _LARG * 2 + 24)
        self._carregar_png(valores.get("id"), inicial=True)
        self.after(_LIMITE_MS, self._exibir_form)

    @staticmethod
    def _campo(pai, titulo: str, widget):
        W.rotulo(pai, titulo, 14, "bold").pack(anchor="w", pady=(8, 4))
        widget.pack(fill="x")
        return widget

    # ---- Exibição (só depois de pronto) -------------------------------------
    def _parte_pronta(self) -> None:
        self._pendentes -= 1
        if self._pendentes <= 0:
            self._exibir_form()

    def _exibir_form(self) -> None:
        if self._exibido or self.fechado:
            return
        self._exibido = True
        self._previa()
        self.exibir(foco=self._f_nome)

    # ---- Ícone -------------------------------------------------------------
    def _carregar_png(self, sid: Optional[int], inicial: bool = False) -> None:
        """PNG da prévia em segundo plano: gravado ('arquivo:') ou gerado (Tabler)."""
        self._seq_png += 1
        seq, icone = self._seq_png, self._icone
        if not icone:
            self._png_recebido((seq, None), inicial)
            return
        if icone.startswith(gerador.PREFIXO_ARQUIVO):
            fn = (lambda: (seq, svc.obter_png(int(sid)))) if sid else (lambda: (seq, None))
        else:
            fn = lambda: (seq, gerador.gerar_png(icone))  # noqa: E731
        tarefa.executar(fn, lambda r: self._png_recebido(r, inicial),
                        lambda _e: self._png_recebido((seq, None), inicial),
                        "setores-previa")

    def _png_recebido(self, r: tuple, inicial: bool = False) -> None:
        seq, png = r
        if self.fechado:
            return
        if seq == self._seq_png:
            self._png = png
            self._previa()
        if inicial:
            self._parte_pronta()

    def _tabler(self, icone: str) -> None:
        if icone == self._icone and not self._png_novo:
            return
        self._icone, self._png_novo = icone, False
        self._carregar_png(None)

    def _sem_icone(self) -> None:
        self._icone, self._png_novo = None, False
        self._busca.selecionar(None)
        self._carregar_png(None)

    def _arquivo(self) -> None:
        if self.travado or self.fechado:
            return
        caminho = filedialog.askopenfilename(parent=self, title="Ícone do setor",
                                             filetypes=_TIPOS)
        if not caminho:
            return
        self.status("Processando imagem…")
        self._seq_png += 1
        seq = self._seq_png
        tarefa.executar(lambda: (seq, gerador.gerar_png_arquivo(caminho)),
                        self._arquivo_ok, lambda e: self.erro(
                            str(e) if isinstance(e, ValueError) else svc.mensagem(e)),
                        "setores-arquivo")

    def _arquivo_ok(self, r: tuple) -> None:
        seq, png = r
        if seq != self._seq_png or self.fechado:
            return
        self._icone, self._png, self._png_novo = gerador.icone_arquivo(png), png, True
        self._busca.selecionar(None)
        self.status("Imagem pronta.", T.NEON)
        self._previa()

    # ---- Prévia ------------------------------------------------------------
    def _cor_mudou(self, cor: str) -> None:
        self._busca.definir_cor(cor)
        self._previa()

    def _previa(self) -> None:
        if self.fechado:
            return
        cor = self._cor.get()
        nome = " ".join(self._f_nome.get().split()) or "Nome do setor"
        pref = (self._f_pref.get().strip().upper() or "A") + "001"
        estado = (cor, nome, pref, self._png)
        if estado == self._ultima_previa:
            return                                  # nada mudou: zero redesenho
        self._ultima_previa = estado
        W.configurar(self._p_barra, fg_color=cor)
        W.configurar(self._p_icone, image=colorir(self._png, cor, _PREVIA) or self._vazio)
        W.configurar(self._p_nome, text=curto(nome, _NOME_MAX))
        W.configurar(self._p_pref, text=pref, text_color=cor)

    # ---- Salvar ------------------------------------------------------------
    def _dados(self) -> dict:
        d = {
            "nome": self._f_nome.get(),
            "descricao": self._f_desc.get(),
            "prefixo": self._f_pref.get(),
            "cor": self._cor.get(),
            "icone": self._icone or "",
        }
        if self._png_novo and self._png:
            d["icone_png"] = self._png
        return d

    def _salvar(self) -> None:
        if self.travado or self.fechado:
            return
        d = self._dados()
        erros = svc.validar(d)
        if erros:
            self.erro(next(iter(erros.values())))
            return
        self.travar(True)
        self.status("Salvando…")
        self._cb(d, self)

    def erro(self, msg: str) -> None:
        if self.fechado:
            return
        self.travar(False)
        self.status(msg, T.DANGER)

    def concluir(self) -> None:
        if self.fechado:
            return
        self.travar(False)
        self.fechar()
