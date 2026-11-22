"""
Aba "Mídias": especificações, lista ordenada, cadastro, edição, exclusão e ordem.
Linhas reaproveitadas (pool): só o conteúdo muda; miniatura só troca se o arquivo mudar.
Prontidão (self.pronto): conta a carga da lista; miniaturas NÃO bloqueiam
(espaço fixo de 96x54 → chegar depois não altera o layout).
"""
import logging
from pathlib import Path
from tkinter import TclError
from typing import Optional

import customtkinter as ctk
from PIL import Image

from config_slideshow import SLIDESHOW
from services import formato, midias_service, miniaturas
from services.auth import Usuario
from ui import info_midias, tarefa
from ui import theme as T
from ui import widgets as W
from ui.confirmacao import Confirmacao
from ui.form_midia import FormMidia
from ui.icones import icone
from ui.prontidao import Prontidao
from ui.sobreposicao import Sobreposicao

log = logging.getLogger(__name__)

_MB = 1024 * 1024
_MINI = (96, 54)
_AJUSTES_OK = ("conter", "cobrir")


def _vivo(w) -> bool:
    try:
        return tarefa.ativo() and bool(w.winfo_exists())
    except TclError:
        return False


def _situacao(m: dict) -> tuple[str, str]:
    if not m["ativo"]:
        return "Inativa", T.TXT_MUTED
    if m["vencida"]:
        return "Vencida", T.DANGER
    if m["agendada"]:
        return "Agendada", T.WARN
    return "Ativa", T.NEON


def _descricao(m: dict) -> str:
    partes = ["Vídeo" if m["tipo"] == "video" else "Imagem"]
    if m["largura"] and m["altura"]:
        partes.append(f"{m['largura']}x{m['altura']}")
    partes += [formato.mb(m["tamanho_bytes"]), f"{m['duracao_seg']} s na tela",
               "Cobrir" if m["ajuste"] == "cobrir" else "Conter"]
    if m["tipo"] == "video":
        partes.append("sem som" if m["mudo"] else "com som")
    de, ate = m["valido_de"], m["valido_ate"]
    if de or ate:
        partes.append(f"{de.strftime('%d/%m/%Y') if de else '…'} a "
                      f"{ate.strftime('%d/%m/%Y') if ate else '…'}")
    return " • ".join(partes)


def _nome_arquivo(m: dict) -> str:
    return (m.get("nome_original") or
            f"{(m.get('sha256') or '')[:12]}….{m.get('extensao') or ''}")


def _valores_edicao(m: dict) -> dict:
    """Normaliza a linha do banco para o formulário (tipos e valores válidos)."""
    ajuste = m.get("ajuste") if m.get("ajuste") in _AJUSTES_OK else "conter"
    return {**m, "ajuste": ajuste,
            "mudo": bool(m.get("mudo") if m.get("mudo") is not None else True),
            "ativo": bool(m.get("ativo")),
            "duracao_seg": int(m.get("duracao_seg") or 10)}


class LinhaMidia(ctk.CTkFrame):
    """Widgets criados uma vez; mostrar() troca só o conteúdo."""

    def __init__(self, master, acoes: dict):
        super().__init__(master, fg_color=T.BG_ITEM, corner_radius=12)
        self.grid_columnconfigure(1, weight=1)
        self._m: Optional[dict] = None
        self._img = None
        self._chave_thumb: Optional[str] = None
        self._thumb = ctk.CTkLabel(self, text="", width=_MINI[0], height=_MINI[1],
                                   fg_color=T.BG_APP, corner_radius=8)
        self._thumb.grid(row=0, column=0, rowspan=2, padx=10, pady=8)
        self._tit = W.rotulo(self, "", 15, "bold", anchor="w")
        self._tit.grid(row=0, column=1, sticky="sw", padx=6, pady=(10, 0))
        self._desc = W.rotulo(self, "", 12, cor=T.TXT_MUTED, anchor="w")
        self._desc.grid(row=1, column=1, sticky="nw", padx=6, pady=(0, 10))
        self._sit = W.rotulo(self, "", 13, "bold", width=80)
        self._sit.grid(row=0, column=2, rowspan=2, padx=8)
        self._bts = []
        for col, (ico, cmd, perigo) in enumerate((
                ("arrow-up", lambda: self._m and acoes["mover"](self._m["id"], -1), False),
                ("arrow-down", lambda: self._m and acoes["mover"](self._m["id"], 1), False),
                ("edit", lambda: self._m and acoes["editar"](self._m), False),
                ("trash", lambda: self._m and acoes["excluir"](self._m), True)), 3):
            b = W.botao(self, "", cmd, perigo=perigo, icone=ico, height=36, size=12, width=40)
            b.grid(row=0, column=col, rowspan=2, padx=(0, 10 if col == 6 else 4))
            self._bts.append(b)

    @property
    def mid(self) -> Optional[int]:
        return self._m["id"] if self._m else None

    def mostrar(self, m: dict, primeiro: bool, ultimo: bool) -> None:
        self._m = m
        chave = f"{m['tipo']}:{m.get('sha256')}"
        if chave != self._chave_thumb:
            self._chave_thumb = chave
            self._img = None
            self._thumb.configure(image=icone("video" if m["tipo"] == "video" else "image",
                                              26, T.TXT_MUTED))
        W.configurar(self._tit, text=m["titulo"] or "(sem título)")
        W.configurar(self._desc, text=_descricao(m))
        texto, cor = _situacao(m)
        W.configurar(self._sit, text=texto, text_color=cor)
        W.habilitar(self._bts[0], not primeiro)
        W.habilitar(self._bts[1], not ultimo)

    def tem_miniatura(self) -> bool:
        return self._img is not None

    def miniatura(self, caminho: Path) -> None:
        try:
            with Image.open(caminho) as img:
                pil = img.copy()
        except OSError:
            return
        self._img = ctk.CTkImage(light_image=pil, dark_image=pil, size=_MINI)
        self._thumb.configure(image=self._img)


class AbaMidias(ctk.CTkFrame):
    def __init__(self, master, usuario: Usuario):
        super().__init__(master, fg_color="transparent")
        self._usuario = usuario
        self._linhas: list[LinhaMidia] = []
        self._qtd = 0
        self._geracao = 0
        self._carregando = False
        self.pronto = Prontidao()
        self._dialogo: Optional[Sobreposicao] = None
        self._acoes = {"mover": self._mover, "editar": self._editar, "excluir": self._excluir}
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.grid(row=0, column=0, sticky="ew")
        W.botao(topo, "Adicionar mídia", self._adicionar, primario=True, icone="upload",
                height=44, size=14).pack(side="left")
        W.botao(topo, "Atualizar", self.atualizar, icone="refresh", height=44,
                size=14).pack(side="left", padx=8)
        self._contador = W.rotulo(topo, "", 13, cor=T.TXT_MUTED)
        self._contador.pack(side="right")
        info_midias.CartaoEspecificacoes(self).grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self._aviso = W.rotulo(self, "", 13, cor=T.TXT_MUTED, anchor="w")
        self._aviso.grid(row=2, column=0, sticky="ew", pady=(8, 4))
        self._lista = W.ListaRolavel(self)
        self._lista.grid(row=3, column=0, sticky="nsew")
        self._vazio = W.rotulo(self._lista, "Carregando mídias…", 14, cor=T.TXT_MUTED)
        self._vazio.pack(pady=24)

    # ---- Carregamento ----------------------------------------------------
    def atualizar(self) -> None:
        if self._carregando:
            return                          # a carga em curso já está na prontidão
        self._carregando = True
        self.pronto.iniciar()
        tarefa.executar(midias_service.listar, self._mostrar, self._falha_lista, "midias-listar")

    def _falha_lista(self, exc: Exception) -> None:
        self._carregando = False
        try:
            if _vivo(self):
                if self._qtd == 0:
                    W.configurar(self._vazio, text="Não foi possível carregar as mídias.")
                self._status(midias_service.mensagem(exc), T.DANGER)
        finally:
            self.pronto.concluir()

    def _mostrar(self, itens: list[dict]) -> None:
        self._carregando = False
        try:
            if _vivo(self):
                self._render(itens)
        finally:
            self.pronto.concluir()

    def _render(self, itens: list[dict]) -> None:
        self._geracao += 1
        n = len(itens)
        while len(self._linhas) < n:
            self._linhas.append(LinhaMidia(self._lista, self._acoes))
        for i, (linha, m) in enumerate(zip(self._linhas, itens)):
            linha.mostrar(m, i == 0, i == n - 1)
        if n:
            self._vazio.pack_forget()
        else:
            W.configurar(self._vazio, text="Nenhuma mídia cadastrada. Use \"Adicionar mídia\".")
            self._vazio.pack(pady=24)
        if n != self._qtd:
            for i in range(self._qtd, n):
                self._linhas[i].pack(fill="x", pady=3, padx=2)
            for i in range(n, self._qtd):
                self._linhas[i].pack_forget()
            self._qtd = n
            self._lista.ajustar_barra()

        ativas = [m for m in itens if m["ativo"]]
        total = sum(int(m["tamanho_bytes"] or 0) for m in ativas)
        alerta = len(ativas) >= SLIDESHOW.max_midias or total > SLIDESHOW.alerta_total_mb * _MB
        W.configurar(self._contador,
                     text=f"{len(ativas)}/{SLIDESHOW.max_midias} ativas • {formato.mb(total)}",
                     text_color=T.WARN if alerta else T.TXT_MUTED)
        self._carregar_miniaturas(self._geracao)

    def _carregar_miniaturas(self, geracao: int) -> None:
        pendentes = [(l.mid, l._m["sha256"], l._m["extensao"])
                     for l in self._linhas[:self._qtd]
                     if l._m["tipo"] == "imagem" and not l.tem_miniatura()]
        if not pendentes:
            return

        def trabalho():
            for mid, sha, ext in pendentes:
                p = miniaturas.obter(sha, ext)
                if p:
                    tarefa.entregar(self._aplicar_miniatura, geracao, mid, p)
        tarefa.executar(trabalho, nome="midias-miniaturas")

    def _aplicar_miniatura(self, geracao: int, mid: int, caminho: Path) -> None:
        if geracao != self._geracao or not _vivo(self):
            return
        for linha in self._linhas[:self._qtd]:
            if linha.mid == mid:
                linha.miniatura(caminho)
                return

    def _status(self, texto: str, cor: str = T.TXT_MUTED) -> None:
        W.configurar(self._aviso, text=texto, text_color=cor)

    def _ocupado(self) -> bool:
        return self._dialogo is not None and not self._dialogo.fechado

    # ---- Cadastro --------------------------------------------------------
    def _adicionar(self) -> None:
        if self._ocupado():
            return
        form = FormMidia(self, {"duracao_seg": 10, "mudo": True, "ativo": True},
                         self._cadastrar)
        self._dialogo = form
        tarefa.executar(midias_service.padroes, lambda r: form.padroes(*r),
                        nome="midias-padroes")

    def _cadastrar(self, dados: dict, caminho: Optional[str], form: FormMidia) -> None:
        tarefa.executar(
            lambda: midias_service.cadastrar_caminho(self._usuario, caminho, dados,
                                                     form.relator),
            lambda r: self._cadastrado(r, form),
            lambda e: form.erro(midias_service.mensagem(e)), "midias-cadastrar")

    def _cadastrado(self, r: dict, form: FormMidia) -> None:
        texto = f"Mídia cadastrada e enviada a {len(r['recebido_por'])} painel(is)."
        if r["avisos"]:
            form.finalizar(texto, r["avisos"])
        else:
            form.concluir()
        if _vivo(self):
            self._status(texto, T.WARN if r["avisos"] else T.NEON)
            self.atualizar()

    # ---- Edição ----------------------------------------------------------
    def _editar(self, m: dict) -> None:
        if self._ocupado():
            return
        try:
            checagens = info_midias.verificar(m["tipo"], m["tamanho_bytes"], m["largura"],
                                              m["altura"], m.get("duracao_video"), False)
            self._dialogo = FormMidia(self, _valores_edicao(m),
                                      lambda d, _c, f: self._salvar_edicao(m["id"], d, f),
                                      editar=True, arquivo=_nome_arquivo(m),
                                      info=_descricao(m), checagens=checagens)
        except Exception as exc:  # noqa: BLE001
            log.exception("Falha ao abrir a edição da mídia %s.", m.get("id"))
            self._status(f"Não foi possível abrir a edição: {exc}", T.DANGER)

    def _salvar_edicao(self, mid: int, dados: dict, form: FormMidia) -> None:
        tarefa.executar(lambda: midias_service.editar(self._usuario, mid, dados),
                        lambda _r: self._editado(form),
                        lambda e: form.erro(midias_service.mensagem(e)), "midias-editar")

    def _editado(self, form: FormMidia) -> None:
        form.concluir()
        if _vivo(self):
            self._status("Mídia atualizada.", T.NEON)
            self.atualizar()

    # ---- Exclusão / ordem ------------------------------------------------
    def _excluir(self, m: dict) -> None:
        if self._ocupado():
            return

        def confirmar(c: Confirmacao):
            c.ocupado("Excluindo…")
            tarefa.executar(lambda: midias_service.excluir(self._usuario, m["id"]),
                            lambda _r: self._excluido(c),
                            lambda e: c.erro(midias_service.mensagem(e)), "midias-excluir")

        self._dialogo = Confirmacao(
            self, "Excluir mídia",
            f"Excluir \"{m['titulo'] or '(sem título)'}\"?\n"
            "Os painéis apagam o arquivo na próxima sincronização.",
            ok="Excluir", perigo=True, ao_confirmar=confirmar)

    def _excluido(self, c: Confirmacao) -> None:
        c.fechar(forcar=True)
        if _vivo(self):
            self._status("Mídia excluída.", T.NEON)
            self.atualizar()

    def _mover(self, mid: int, delta: int) -> None:
        def ok(_r):
            if _vivo(self):
                self.atualizar()

        def erro(exc):
            if _vivo(self):
                self._status(midias_service.mensagem(exc), T.DANGER)

        tarefa.executar(lambda: midias_service.mover(self._usuario, mid, delta), ok, erro,
                        "midias-mover")
