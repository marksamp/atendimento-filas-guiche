"""
Aba "Status dos painéis": online/offline/inativos, diagnóstico e reenvio.
Linhas reaproveitadas (sem destroy a cada atualização automática).
Auto-atualização só quando visível (visivel(True) pela TelaMidias) e sem sobreposição aberta.
Atualizar (manual): botão "Atualizando…" + confirmação com horário; erro em vermelho.
Diagnóstico e reenvio: sobreposições com progresso; serviço em thread.
Prontidão (self.pronto): conta a carga da lista (ok OU erro).
"""
from datetime import datetime
from tkinter import TclError
from typing import Optional

import customtkinter as ctk

from config_slideshow import SLIDESHOW
from services import formato, midias_service, paineis_service
from services.auth import Usuario
from services.paineis_service import Painel
from ui import dialogos, sobreposicao, tarefa
from ui import theme as T
from ui import widgets as W
from ui.dialogo_diagnostico import DialogoDiagnostico
from ui.dialogo_reenvio import DialogoReenvio
from ui.prontidao import Prontidao

_AUTO_MS = 10_000
_GRUPOS = (("online", "Online"), ("offline", "Offline"), ("encerrado", "Inativos"))
_COR = {"online": T.NEON, "offline": T.DANGER, "encerrado": T.TXT_MUTED}
_DICA = ("Diagnosticar: testa conexão, token e mídias do painel.   "
         "Reenviar mídias: copia ao painel as mídias ativas que faltam nele.")


def _vivo(w) -> bool:
    try:
        return bool(w.winfo_exists())
    except TclError:
        return False


def _sync(p: Painel, versao: int) -> tuple[str, str]:
    if not p.online:
        return "—", T.TXT_MUTED
    if versao == 0:
        return "Sem mídias", T.TXT_MUTED
    if p.sincronizado:
        return "Sincronizado", T.NEON
    return "Pendente", T.WARN


def _endereco(texto: str) -> tuple[str, int]:
    texto = texto.strip()
    if not texto:
        raise ValueError("Informe IP:porta.")
    host, porta = texto, SLIDESHOW.porta
    if texto.count(":") == 1:
        host, p = texto.split(":")
        porta = int(p)
    if not host.strip() or not 1 <= porta <= 65535:
        raise ValueError
    return host.strip(), porta


def _detalhe(p: Painel) -> str:
    if p.estado == "encerrado":
        return "Encerrado"
    return " • ".join(x for x in (
        p.endereco if p.ip else paineis_service.SEM_IP,
        f"v{p.versao_app}" if p.versao_app else "",
        formato.espaco(p.espaco_livre_mb) if p.espaco_livre_mb is not None else "") if x)


class LinhaPainel(ctk.CTkFrame):
    """Widgets criados uma vez; mostrar() só troca o conteúdo."""

    def __init__(self, master, diagnosticar, reenviar):
        super().__init__(master, fg_color=T.BG_ITEM, corner_radius=12)
        self.grid_columnconfigure(1, weight=1)
        self._p: Optional[Painel] = None
        self._ponto = ctk.CTkFrame(self, width=12, height=12, corner_radius=6)
        self._ponto.grid(row=0, column=0, rowspan=2, padx=(14, 8))
        self._nome = W.rotulo(self, "", 15, "bold", anchor="w")
        self._nome.grid(row=0, column=1, sticky="sw", pady=(10, 0))
        self._det = W.rotulo(self, "", 12, cor=T.TXT_MUTED, anchor="w")
        self._det.grid(row=1, column=1, sticky="nw", pady=(0, 10))
        self._sync = W.rotulo(self, "", 13, "bold", width=110)
        self._sync.grid(row=0, column=2, padx=8)
        self._visto = W.rotulo(self, "", 12, cor=T.TXT_MUTED, width=110)
        self._visto.grid(row=1, column=2, padx=8)
        self._b_diag = W.botao(self, "Diagnosticar", lambda: self._p and diagnosticar(self._p),
                               icone="help", height=36, size=12, width=130)
        self._b_diag.grid(row=0, column=3, rowspan=2, padx=4)
        self._b_reenv = W.botao(self, "Reenviar mídias", lambda: self._p and reenviar(self._p),
                                icone="upload", height=36, size=12, width=150)
        self._b_reenv.grid(row=0, column=4, rowspan=2, padx=(4, 12))

    def mostrar(self, p: Painel, versao: int) -> None:
        self._p = p
        W.configurar(self._ponto, fg_color=_COR[p.estado])
        W.configurar(self._nome, text=p.maquina)
        W.configurar(self._det, text=_detalhe(p))
        texto, cor = _sync(p, versao)
        W.configurar(self._sync, text=texto, text_color=cor)
        W.configurar(self._visto,
                     text="—" if p.estado == "encerrado" else formato.idade(p.idade))
        W.habilitar(self._b_reenv, p.online and bool(p.ip))


class AbaPaineis(ctk.CTkFrame):
    def __init__(self, master, usuario: Usuario):
        super().__init__(master, fg_color="transparent")
        self._usuario = usuario
        self._carregando = False
        self._manual = False
        self._visivel = False
        self.pronto = Prontidao()
        self._linhas: dict[str, LinhaPainel] = {}
        self._ordem: list = []
        self._job: Optional[str] = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.grid(row=0, column=0, sticky="ew")
        self._b_atual = W.botao(topo, "Atualizar", lambda: self.atualizar(True),
                                icone="refresh", height=44, size=14, width=150)
        self._b_atual.pack(side="left")
        self._b_avulso = W.botao(topo, "Diagnosticar", self._avulso, icone="wifi", height=44,
                                 size=14)
        self._b_avulso.pack(side="right")
        self._e_end = W.entrada(topo, "IP:porta (diagnóstico avulso)", width=260)
        self._e_end.pack(side="right", padx=8)
        self._e_end.bind("<Return>", lambda _e: self._avulso())
        W.rotulo(self, _DICA, 11, cor=T.TXT_MUTED, anchor="w").grid(
            row=1, column=0, sticky="ew", pady=(8, 0))
        self._info = W.rotulo(self, "", 13, cor=T.TXT_MUTED, anchor="w")
        self._info.grid(row=2, column=0, sticky="ew", pady=(4, 4))
        self._lista = W.ListaRolavel(self)
        self._lista.grid(row=3, column=0, sticky="nsew")
        self._vazio = W.rotulo(self._lista, "Carregando painéis…", 14, cor=T.TXT_MUTED)
        self._vazio.pack(pady=24)
        self._ordem = [("vazio", None)]
        self._cabs = {e: W.rotulo(self._lista, "", 12, "bold", _COR[e], anchor="w")
                      for e, _t in _GRUPOS}

    def destroy(self):
        self._parar_auto()
        super().destroy()

    # ---- Visibilidade / auto-atualização ----------------------------------
    def visivel(self, on: bool) -> None:
        self._visivel = on
        if on and not self._job:
            self._job = self.after(_AUTO_MS, self._auto)
        elif not on:
            self._parar_auto()

    def _parar_auto(self) -> None:
        if self._job:
            try:
                self.after_cancel(self._job)
            except TclError:
                pass
            self._job = None

    def _auto(self) -> None:
        self._job = None
        if not _vivo(self) or not self._visivel:
            return
        if not (sobreposicao.aberta() or self.grab_current()):
            self.atualizar()
        self._job = self.after(_AUTO_MS, self._auto)

    def _status(self, texto: str, cor: str = T.TXT_MUTED) -> None:
        W.configurar(self._info, text=texto, text_color=cor)

    # ---- Lista ------------------------------------------------------------
    def atualizar(self, manual: bool = False) -> None:
        if manual and not self._manual:
            self._manual = True
            W.habilitar(self._b_atual, False)
            W.definir(self._b_atual, "Atualizando…")
            self._status("Atualizando a lista de painéis…", T.NEON)
        if self._carregando:
            return                          # a carga em curso já está na prontidão
        self._carregando = True
        self.pronto.iniciar()
        tarefa.executar(paineis_service.listar, self._mostrar, self._falha, "paineis-listar")

    def _fim_carga(self) -> bool:
        """Restaura o botão; devolve se a carga era manual."""
        self._carregando = False
        manual, self._manual = self._manual, False
        if manual and _vivo(self):
            W.definir(self._b_atual, "Atualizar")
            W.habilitar(self._b_atual, True)
        return manual

    def _falha(self, exc: Exception) -> None:
        self._fim_carga()
        try:
            if _vivo(self):
                if self._ordem == [("vazio", None)]:
                    W.configurar(self._vazio, text="Não foi possível carregar os painéis.")
                self._status(f"✖ Falha ao atualizar: {midias_service.mensagem(exc)}", T.DANGER)
        finally:
            self.pronto.concluir()

    def _mostrar(self, r: tuple[list[Painel], int]) -> None:
        manual = self._fim_carga()
        try:
            if _vivo(self):
                self._render(r, manual)
        finally:
            self.pronto.concluir()

    def _render(self, r: tuple[list[Painel], int], manual: bool) -> None:
        paineis, versao = r
        ordem: list = []
        usados = set()
        for estado, titulo in _GRUPOS:
            grupo = [p for p in paineis if p.estado == estado]
            if not grupo:
                continue
            W.configurar(self._cabs[estado], text=f"{titulo.upper()} ({len(grupo)})")
            ordem.append(("cab", estado))
            for p in grupo:
                linha = self._linhas.get(p.maquina)
                if linha is None:
                    linha = self._linhas[p.maquina] = LinhaPainel(
                        self._lista, self._diagnosticar, self._reenviar)
                linha.mostrar(p, versao)
                usados.add(p.maquina)
                ordem.append(("lin", p.maquina))
        removidas = [k for k in self._linhas if k not in usados]
        if not paineis:
            W.configurar(self._vazio, text="Nenhum painel registrado.")
            ordem.append(("vazio", None))
        if ordem != self._ordem:
            self._reempacotar(ordem)
        for chave in removidas:
            self._linhas.pop(chave).destroy()
        online = sum(p.online for p in paineis)
        hora = datetime.now().strftime("%H:%M:%S")
        resumo = f"{online} painel(is) online • versão do slideshow: {versao}"
        if manual:
            self._status(f"✔ Lista atualizada às {hora} • {resumo}", T.NEON)
        else:
            self._status(f"{resumo} • atualizado às {hora}")

    def _widget(self, item):
        tipo, chave = item
        if tipo == "cab":
            return self._cabs[chave]
        if tipo == "vazio":
            return self._vazio
        return self._linhas.get(chave)

    def _reempacotar(self, ordem: list) -> None:
        for item in self._ordem:
            w = self._widget(item)
            if w is not None:
                w.pack_forget()
        for item in ordem:
            w = self._widget(item)
            if item[0] == "cab":
                w.pack(fill="x", padx=4, pady=(12, 4))
            elif item[0] == "vazio":
                w.pack(pady=24)
            else:
                w.pack(fill="x", pady=3, padx=2)
        self._ordem = ordem
        self._lista.ajustar_barra()

    # ---- Diagnóstico -----------------------------------------------------
    def _iniciar_diag(self, alvo: str, fn) -> None:
        if sobreposicao.aberta():
            return
        DialogoDiagnostico(self, alvo, fn)

    def _diagnosticar(self, p: Painel) -> None:
        self._iniciar_diag(p.maquina,
                           lambda rel: paineis_service.diagnosticar(p, progresso=rel))

    def _avulso(self) -> None:
        try:
            ip, porta = _endereco(self._e_end.get())
        except ValueError:
            self._status("Endereço inválido. Use IP:porta (ex.: 192.168.0.20:8765).", T.DANGER)
            return
        self._status("")
        self._iniciar_diag(f"{ip}:{porta}",
                           lambda rel: paineis_service.diagnosticar(None, ip, porta, rel))

    # ---- Reenvio ---------------------------------------------------------
    def _reenviar(self, p: Painel) -> None:
        if sobreposicao.aberta():
            return

        def fim(texto: str, sucesso: bool, fechado: bool) -> None:
            if not _vivo(self):
                return
            self.atualizar()
            if fechado:                     # diálogo fechado durante o reenvio
                dialogos.avisar(self, "Reenvio concluído" if sucesso else "Falha no reenvio",
                                texto)

        DialogoReenvio(self, p, fim)
