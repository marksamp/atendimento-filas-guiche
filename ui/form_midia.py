"""
Formulário de mídia (cadastro/edição) em sobreposição, no padrão da tela de login.
- Novo: campo Arquivo + Selecionar; nada é analisado antes de Salvar.
- Editar: arquivo bloqueado (para trocar, exclua a mídia e cadastre de novo).
- GIF: tipo "imagem"; requisitos e checagens próprios (tamanho, quadros).
- Salvar (novo), sem flicker:
  1. pre_validar() instantâneo: erro fica no formulário (nenhuma troca de tela);
  2. loading sobre os campos durante a análise (layout intacto);
  3. só no evento "destinos" o card troca para a tela de progresso.
  Fila de UI: enquanto o loading não cumpriu o tempo mínimo, eventos/erros/fim
  esperam (o loading nunca "pisca"). Erro: some o loading, volta ao formulário.
- Fim (sucesso ou avisos): mensagem única na etapa; espera o OK do usuário.
"""
from pathlib import Path
from tkinter import filedialog
from typing import Callable, Optional

import customtkinter as ctk

from config_slideshow import EXT_IMAGEM, EXT_VIDEO, SLIDESHOW
from services import midias_service
from services.midias_arquivo import ErroArquivo
from services.midias_prevalidacao import pre_validar
from ui import info_midias
from ui import theme as T
from ui import widgets as W
from ui.campo_data import CampoDataHora
from ui.carregando import Carregando
from ui.progresso_envio import ProgressoEnvio, Relator
from ui.sobreposicao import Sobreposicao

_AJUSTES = {"Conter (sem corte)": "conter", "Cobrir (preenche a tela)": "cobrir"}
_ESTADO = {True: ("✔", T.NEON), False: ("✖", T.DANGER), None: ("•", T.TXT_MUTED),
           info_midias.AVISO: ("⚠", T.WARN)}
_ESQ = 340
_COL = 230
_DIR = _COL * 2 + 16
_LARG = _ESQ + 24 + _DIR
_PENDENTE = [("Analisado ao salvar.", None)]
_SUB_NOVO = "Selecione o arquivo e preencha os dados. A análise é feita ao salvar."


def _ext_de(caminho: str) -> str:
    return Path(caminho).suffix.lstrip(".").lower()


def tipo_do(caminho: str) -> Optional[str]:
    ext = _ext_de(caminho)
    return "video" if ext in EXT_VIDEO else ("imagem" if ext in EXT_IMAGEM else None)


def _filtros() -> list[tuple[str, str]]:
    img = " ".join(f"*.{e}" for e in sorted(EXT_IMAGEM))
    vid = " ".join(f"*.{e}" for e in sorted(EXT_VIDEO))
    return [("Imagens, GIFs e vídeos", f"{img} {vid}"), ("Imagens e GIFs", img),
            ("GIFs", "*.gif"), ("Vídeos", vid)]


def _switch(parent, texto: str, ligado: bool) -> ctk.CTkSwitch:
    s = ctk.CTkSwitch(parent, text=texto, font=T.font(13), text_color=T.TXT, width=46,
                      progress_color=T.NEON, fg_color=T.BORDER, button_color=T.TXT,
                      button_hover_color=T.NEON_DARK)
    s.select() if ligado else s.deselect()
    return s


class FormMidia(Sobreposicao):
    def __init__(self, master, valores: dict,
                 ao_salvar: Callable[[dict, Optional[str], "FormMidia"], None],
                 editar: bool = False, arquivo: str = "", info: str = "",
                 checagens: Optional[list] = None):
        super().__init__(master, "Editar mídia" if editar else "Nova mídia",
                         info if editar else _SUB_NOVO)
        self._editar = editar
        self._cb = ao_salvar
        self._caminho: Optional[str] = None
        self._tipo: Optional[str] = valores.get("tipo") if editar else None
        self._ext: str = (valores.get("extensao") or _ext_de(arquivo)) if editar else ""
        self._auto_titulo = ""
        self._sub = info if editar else _SUB_NOVO
        self._em_progresso = False
        self._carregando = False
        self._arq = None
        self._fila: list[Callable[[], None]] = []
        self._job_fila: Optional[str] = None
        self.relator = Relator(self._evento)
        self.ao_fechar(self._cancelar_fila)

        c = self.corpo
        c.grid_columnconfigure(0, weight=1)
        self._campos = ctk.CTkFrame(c, fg_color="transparent")
        self._campos.grid(row=0, column=0, sticky="ew")
        self._campos.grid_columnconfigure(1, weight=1)
        esq = ctk.CTkFrame(self._campos, fg_color="transparent", width=_ESQ)
        esq.grid(row=0, column=0, sticky="n", padx=(0, 24))
        self._grade = ctk.CTkFrame(self._campos, fg_color="transparent")
        self._grade.grid(row=0, column=1, sticky="new")
        self._grade.grid_columnconfigure((0, 1), weight=1, uniform="col")

        self._montar_arquivo(esq, arquivo, valores)
        self._montar_campos(valores)
        self._loading = Carregando(c)
        self._prog = ProgressoEnvio(c, _LARG)
        self.rodape_padrao("Salvar", self._salvar, _LARG)
        self._preencher(checagens or _PENDENTE)
        self._mostrar_tipo()
        self.exibir(foco=self._f_titulo)

    # ---- Montagem ------------------------------------------------------------
    def _montar_arquivo(self, esq, arquivo: str, valores: dict) -> None:
        W.rotulo(esq, "Arquivo", 14, "bold").pack(anchor="w")
        linha = ctk.CTkFrame(esq, fg_color="transparent")
        linha.pack(fill="x", pady=(4, 2))
        linha.grid_columnconfigure(0, weight=1)
        self._f_arq = W.entrada(linha, "Nenhum arquivo selecionado", width=_ESQ - 52)
        self._f_arq.grid(row=0, column=0, sticky="ew")
        self._definir_arquivo(arquivo)
        self._b_arq = W.botao(linha, "", self._selecionar, icone="upload", height=44,
                              size=12, width=44)
        self._b_arq.grid(row=0, column=1, padx=(8, 0))
        if self._editar:
            W.habilitar(self._b_arq, False)
            W.rotulo(esq, "Para trocar o arquivo, exclua a mídia e cadastre de novo.", 11,
                     cor=T.WARN, wraplength=_ESQ, justify="left").pack(anchor="w")

        bloco = ctk.CTkFrame(esq, fg_color=T.BG_ITEM, corner_radius=12)
        bloco.pack(fill="x", pady=(10, 0))
        W.rotulo(bloco, "Características do arquivo", 13, "bold", T.NEON).pack(
            anchor="w", padx=12, pady=(8, 2))
        self._f_checks = ctk.CTkFrame(bloco, fg_color="transparent")
        self._f_checks.pack(fill="x", padx=12)
        self._lbl_req = W.rotulo(bloco, "", 11, cor=T.TXT_MUTED, wraplength=_ESQ - 24,
                                 justify="left")
        self._lbl_req.pack(anchor="w", padx=12, pady=(4, 8))

        opc = ctk.CTkFrame(esq, fg_color=T.BG_ITEM, corner_radius=12)
        opc.pack(fill="x", pady=(10, 0))
        self._f_ativo = _switch(opc, "Ativa", bool(valores.get("ativo", True)))
        self._f_ativo.pack(anchor="w", padx=14, pady=(10, 2))
        self._f_mudo = _switch(opc, "Sem som", bool(valores.get("mudo", True)))
        self._lbl_max = W.rotulo(opc, f"Máximo de {SLIDESHOW.max_midias} mídias ativas.", 11,
                                 cor=T.TXT_MUTED)
        self._lbl_max.pack(anchor="w", padx=14, pady=(2, 10))

    def _montar_campos(self, valores: dict) -> None:
        cel = self._celula(0, 0, "Título", span=2)
        self._f_titulo = W.entrada(cel, "Título", width=_DIR)
        self._f_titulo.pack(fill="x")
        self._f_titulo.insert(0, valores.get("titulo") or "")

        cel = self._celula(1, 0, "Tempo na tela (s)")
        self._f_dur = W.entrada(cel, "segundos", width=_COL)
        self._f_dur.pack(anchor="w")
        self._f_dur.insert(0, str(valores.get("duracao_seg") or 10))
        self._ini_dur = self._f_dur.get()
        self._lbl_dur = self._dica(cel, "")

        cel = self._celula(1, 1, "Ajuste")
        self._f_ajuste = W.opcoes(cel, list(_AJUSTES), comando=self._dica_ajuste, width=_COL)
        self._f_ajuste.pack(anchor="w")
        ajuste = valores.get("ajuste") or "conter"
        self._f_ajuste.set(next(k for k, v in _AJUSTES.items() if v == ajuste))
        self._lbl_ajuste = self._dica(cel, info_midias.AJUSTE_DICA[ajuste])

        cel = self._celula(2, 0, "Válida de")
        self._f_de = CampoDataHora(cel, so_data=True, largura=_COL)
        self._f_de.pack(anchor="w")
        self._f_de.definir_data(valores.get("valido_de"))
        self._dica(cel, "Em branco = sem limite.")

        cel = self._celula(2, 1, "Válida até")
        self._f_ate = CampoDataHora(cel, so_data=True, largura=_COL)
        self._f_ate.pack(anchor="w")
        self._f_ate.definir_data(valores.get("valido_ate"))

    def _celula(self, linha: int, col: int, rotulo: str, span: int = 1) -> ctk.CTkFrame:
        padx = (0, 8) if col == 0 and span == 1 else ((8, 0) if col == 1 else 0)
        cel = ctk.CTkFrame(self._grade, fg_color="transparent")
        cel.grid(row=linha, column=col, columnspan=span, sticky="new", padx=padx, pady=(0, 10))
        W.rotulo(cel, rotulo, 14, "bold").pack(anchor="w", pady=(0, 4))
        return cel

    @staticmethod
    def _dica(cel, texto: str):
        lbl = W.rotulo(cel, texto, 11, cor=T.TXT_MUTED, wraplength=_COL, justify="left")
        lbl.pack(anchor="w", pady=(3, 0))
        return lbl

    def _dica_ajuste(self, escolha: str) -> None:
        self._lbl_ajuste.configure(text=info_midias.AJUSTE_DICA[_AJUSTES[escolha]])

    # ---- Arquivo -------------------------------------------------------------
    def _definir_arquivo(self, texto: str) -> None:
        self._f_arq.configure(state="normal")
        self._f_arq.delete(0, "end")
        if texto:
            self._f_arq.insert(0, texto)
        self._f_arq.configure(state="readonly")

    def _selecionar(self) -> None:
        if self.travado or self._editar:
            return
        caminho = filedialog.askopenfilename(parent=self.winfo_toplevel(),
                                             title="Selecionar mídia", filetypes=_filtros())
        if not caminho or self.fechado:
            return
        tipo = tipo_do(caminho)
        if tipo is None:
            return self.status("Formato não suportado.", T.DANGER)
        self._caminho, self._tipo, self._ext = caminho, tipo, _ext_de(caminho)
        p = Path(caminho)
        self._definir_arquivo(p.name)
        titulo = self._f_titulo.get().strip()
        if not titulo or titulo == self._auto_titulo:
            self._auto_titulo = p.stem[:120]
            self._f_titulo.delete(0, "end")
            self._f_titulo.insert(0, self._auto_titulo)
        self._preencher(_PENDENTE)
        self._mostrar_tipo()
        self.status("")

    def _mostrar_tipo(self) -> None:
        a, b = SLIDESHOW.duracao_limite
        dica = f"De {a} a {b} segundos."
        if self._ext == "gif":
            dica += " O GIF animado repete durante esse tempo."
        W.configurar(self._lbl_dur, text=dica)
        if self._tipo:
            W.configurar(self._lbl_req, text=info_midias.requisitos(self._tipo, self._ext))
        else:
            W.configurar(self._lbl_req, text="Selecione um arquivo para ver os requisitos.")
        if self._tipo == "video":
            self._f_mudo.pack(anchor="w", padx=14, pady=2, before=self._lbl_max)
        else:
            self._f_mudo.pack_forget()

    def _preencher(self, checagens: list) -> None:
        for w in self._f_checks.winfo_children():
            w.destroy()
        for texto, estado in checagens:
            simbolo, cor = _ESTADO.get(estado, _ESTADO[None])
            W.rotulo(self._f_checks, f"{simbolo} {texto}", 12, cor=cor, wraplength=_ESQ - 24,
                     justify="left").pack(anchor="w")

    def padroes(self, duracao: int, mudo: bool) -> None:
        """Padrões do banco (chegam em segundo plano); só preenche o que não foi mexido."""
        if self.fechado or self._editar:
            return
        if self._f_dur.get() == self._ini_dur:
            self._f_dur.delete(0, "end")
            self._f_dur.insert(0, str(duracao))
            self._ini_dur = self._f_dur.get()
        self._f_mudo.select() if mudo else self._f_mudo.deselect()

    # ---- Fila de UI (respeita o tempo mínimo do loading) ---------------------
    def _executar(self, fn: Callable[[], None]) -> None:
        self._fila.append(fn)
        if self._job_fila is None:
            self._drenar()

    def _drenar(self) -> None:
        self._job_fila = None
        while self._fila and not self.fechado:
            espera = self._loading.restante_ms() if self._carregando else 0
            if espera > 0:
                self._job_fila = self.after(espera, self._drenar)
                return
            self._fila.pop(0)()

    def _cancelar_fila(self) -> None:
        self._fila.clear()
        if self._job_fila is not None:
            try:
                self.after_cancel(self._job_fila)
            except Exception:  # noqa: BLE001
                pass
            self._job_fila = None

    # ---- Alternância formulário / loading / progresso -------------------------
    def _modo_carregando(self) -> None:
        self._carregando = True
        self._arq = None
        self._loading.mostrar(self._campos, "Analisando o arquivo…",
                              Path(self._caminho).name)
        self.lbl_sub.configure(text="Analisando a mídia. Aguarde…")
        self.suspender_buffer()

    def _sair_carregando(self) -> None:
        if self._carregando:
            self._carregando = False
            self._loading.esconder()

    def _modo_progresso(self) -> None:
        self.corpo.grid_rowconfigure(0, minsize=self._campos.winfo_height())
        self._prog.iniciar(Path(self._caminho).name)
        if self._arq is not None:
            self._prog.evento("analisado", (self._arq,))
        self._prog.grid(row=0, column=0, sticky="new")
        self._campos.grid_remove()
        self._sair_carregando()
        self.lbl_sub.configure(text="Enviando a mídia aos painéis. Não feche o sistema.")
        self._em_progresso = True

    def _modo_formulario(self) -> None:
        self._campos.grid()
        self._prog.grid_remove()
        self.lbl_sub.configure(text=self._sub)
        self._em_progresso = False

    # ---- Salvar --------------------------------------------------------------
    def _salvar(self) -> None:
        if self.travado or self.fechado:
            return
        if not self._editar and not self._caminho:
            return self.erro("Selecione o arquivo da mídia.")
        try:
            de, ate = self._f_de.data(), self._f_ate.data()
        except ValueError as exc:
            return self.erro(str(exc))
        try:
            dur = int(self._f_dur.get().strip())
        except ValueError:
            return self.erro("Tempo na tela inválido.")
        dados = {"titulo": self._f_titulo.get().strip(), "duracao_seg": dur,
                 "ajuste": _AJUSTES[self._f_ajuste.get()], "mudo": bool(self._f_mudo.get()),
                 "ativo": bool(self._f_ativo.get()), "valido_de": de, "valido_ate": ate}
        erros = midias_service.validar(dados, self._tipo or "")
        if erros:
            return self.erro(next(iter(erros.values())))
        if not self._editar:
            try:
                pre_validar(self._caminho)
            except ErroArquivo as exc:
                return self.erro(str(exc))
        self.travar(True)
        W.habilitar(self._b_arq, False)
        self.status("Salvando…" if self._editar else "")
        if not self._editar:
            self._modo_carregando()
        self._cb(dados, self._caminho, self)

    def _evento(self, evento: str, dados: tuple) -> None:
        self._executar(lambda: self._tratar(evento, dados))

    def _tratar(self, evento: str, dados: tuple) -> None:
        if self.fechado:
            return
        if evento == "analisado":
            arq = self._arq = dados[0]
            self._preencher(info_midias.verificar(arq.tipo, arq.tamanho, arq.largura,
                                                  arq.altura, arq.duracao_video,
                                                  bool(arq.temporario), arq.extensao,
                                                  arq.quadros))
        if self._carregando:
            if evento == "etapa":
                return self._loading.texto(dados[0])
            if evento == "analisado":
                return self._loading.texto("Arquivo analisado.")
            if evento != "destinos":
                return
            self._modo_progresso()
        self._prog.evento(evento, dados)

    # ---- Encerramento --------------------------------------------------------
    def erro(self, msg: str) -> None:
        self._executar(lambda: self._erro(msg))

    def _erro(self, msg: str) -> None:
        if self.fechado:
            return
        self._sair_carregando()
        if self._em_progresso:
            self._modo_formulario()
        else:
            self.lbl_sub.configure(text=self._sub)
        self.travar(False)
        W.habilitar(self._b_arq, not self._editar)
        self.status(msg, T.DANGER)

    def _aguardar_ok(self, etapa: str, cor: str, detalhe: str = "") -> None:
        """Mantém a tela de progresso e espera o usuário confirmar."""
        self._sair_carregando()
        self._prog.concluir(etapa, cor)
        self.travar(False)
        self.status(detalhe, cor)
        W.definir(self.btn_ok, "OK")
        self.btn_ok.configure(command=self.fechar)
        if self.btn_cancelar is not None:
            self.btn_cancelar.pack_forget()
        self.lbl_sub.configure(text="Processo finalizado.")
        self._focar(self.btn_ok)

    def finalizar(self, texto: str, avisos: list[str]) -> None:
        """Concluído com avisos."""
        self._executar(lambda: self.fechado or self._aguardar_ok(texto, T.WARN,
                                                                 "\n".join(avisos)))

    def concluir(self) -> None:
        """Sucesso: no cadastro espera o OK; na edição fecha na hora."""
        self._executar(self._concluir)

    def _concluir(self) -> None:
        if self.fechado:
            return
        if not self._em_progresso:
            self._sair_carregando()
            self.travar(False)
            self.fechar()
            return
        self._aguardar_ok("✔ Mídia cadastrada e enviada.", T.NEON)
