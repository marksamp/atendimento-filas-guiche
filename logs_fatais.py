"""
Logs fatais (nível CRITICAL/FATAL) separados por dia, com retenção configurável.

- Arquivos: <pasta>/fatal-AAAA-MM-DD.log (data local do evento).
  O nome com a data garante a separação diária mesmo com Totem, Guichê e
  Painel gravando ao mesmo tempo (cada evento abre o arquivo em modo append,
  escreve um bloco único e fecha; não há rotação por renomeação).
- Registra: log.critical()/log.fatal() de qualquer módulo, exceções não
  tratadas no programa (sys.excepthook) e em threads (threading.excepthook).
- Eventos relacionados de nível menor (ex.: retorno da conexão após uma
  queda) também podem ser gravados: log.info(..., extra=EXTRA_FATAL).
- Retenção: padrão em config.LOGS; o valor escolhido pelo técnico fica em
  <pasta>/retencao.json. A limpeza roda ao iniciar, a cada hora e na troca
  de dia; usa a data do NOME do arquivo (não a data de modificação).
- Falhas de escrita/limpeza nunca propagam: geram um único aviso no stderr.
"""
import json
import logging
import os
import re
import sys
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from config import APP_NAME, LOGS

log = logging.getLogger(__name__)

_RE_ARQUIVO = re.compile(r"^fatal-(\d{4}-\d{2}-\d{2})\.log$")
_ARQ_CONFIG = "retencao.json"
_SEPARADOR = "-" * 80
_FORMATO = ("%(asctime)s [%(levelname)s] programa=%(programa)s pid=%(process)d "
            "thread=%(threadName)s origem=%(name)s %(module)s:%(lineno)d\n%(message)s")

# Marca para gravar no log fatal um registro de nível menor que CRITICAL
_MARCA = "registrar_fatal"
EXTRA_FATAL = {_MARCA: True}

_avisos: set[str] = set()
_avisos_lock = threading.Lock()
_handler: Optional["FatalDiarioHandler"] = None
_instalar_lock = threading.Lock()


# ---------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------
def pasta_padrao() -> Path:
    """%LOCALAPPDATA%/SistemaFilas/logs/fatal (Windows) ou ~/.local/state/... ."""
    base = os.environ.get("LOCALAPPDATA") if sys.platform == "win32" else None
    raiz = Path(base) if base else Path.home() / ".local" / "state"
    return raiz / APP_NAME / "logs" / "fatal"


def _avisar(tipo: str, mensagem: str) -> None:
    """Avisa uma única vez por tipo/processo, sem nunca lançar exceção."""
    with _avisos_lock:
        if tipo in _avisos:
            return
        _avisos.add(tipo)
    stream = sys.__stderr__
    if stream is None:          # pythonw.exe: sem console
        return
    try:
        stream.write(f"[logs_fatais] {mensagem}\n")
        stream.flush()
    except Exception:  # noqa: BLE001
        pass


def _deve_gravar(record: logging.LogRecord) -> bool:
    """CRITICAL sempre; níveis menores somente se marcados com EXTRA_FATAL."""
    return record.levelno >= logging.CRITICAL or bool(getattr(record, _MARCA, False))


# ---------------------------------------------------------------------
# Retenção
# ---------------------------------------------------------------------
def validar_retencao(valor) -> tuple[Optional[int], str]:
    """Retorna (dias, "") se válido ou (None, mensagem de erro)."""
    try:
        dias = int(str(valor).strip())
    except (TypeError, ValueError):
        return None, "Informe um número inteiro de dias."
    if not LOGS.retencao_min_dias <= dias <= LOGS.retencao_max_dias:
        return None, f"Use entre {LOGS.retencao_min_dias} e {LOGS.retencao_max_dias} dias."
    return dias, ""


def retencao_dias(pasta: Optional[Path] = None) -> int:
    """Retenção configurada; usa o padrão se ausente ou inválida."""
    arq = Path(pasta or pasta_padrao()) / _ARQ_CONFIG
    try:
        dados = json.loads(arq.read_text(encoding="utf-8"))
        dias, erro = validar_retencao(dados.get("retencao_dias"))
        if not erro:
            return dias
        log.warning("Retenção inválida em %s; usando o padrão.", arq)
    except FileNotFoundError:
        pass
    except (OSError, ValueError, AttributeError) as exc:
        log.warning("Configuração de retenção ilegível (%s); usando o padrão.", exc)
    return LOGS.retencao_padrao_dias


def definir_retencao(dias: int, pasta: Optional[Path] = None) -> None:
    """
    Grava a retenção (escrita atômica) e aplica a limpeza imediatamente.
    Lança ValueError (valor inválido) ou OSError (falha de gravação).
    """
    valor, erro = validar_retencao(dias)
    if erro:
        raise ValueError(erro)
    pasta = Path(pasta or pasta_padrao())
    pasta.mkdir(parents=True, exist_ok=True)
    tmp = pasta / f"{_ARQ_CONFIG}.{os.getpid()}.tmp"
    tmp.write_text(json.dumps({"retencao_dias": valor}), encoding="utf-8")
    os.replace(tmp, pasta / _ARQ_CONFIG)
    log.info("Retenção de logs fatais definida para %s dia(s).", valor)
    limpar_expirados(pasta, valor)


def limpar_expirados(pasta: Optional[Path] = None, dias: Optional[int] = None,
                     hoje: Optional[date] = None) -> list[Path]:
    """
    Remove arquivos fatal-AAAA-MM-DD.log fora da retenção.
    Mantém o dia atual + (dias - 1) anteriores. Nunca lança exceção.
    """
    pasta = Path(pasta or pasta_padrao())
    dias = dias or retencao_dias(pasta)
    hoje = hoje or date.today()
    limite = hoje - timedelta(days=dias - 1)
    removidos: list[Path] = []
    try:
        itens = list(pasta.iterdir())
    except FileNotFoundError:
        return removidos
    except OSError as exc:
        _avisar("limpeza", f"Não foi possível listar {pasta}: {exc}")
        return removidos

    for arq in itens:
        m = _RE_ARQUIVO.match(arq.name)
        if not m:
            continue
        try:
            dia = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if dia >= limite:
            continue
        try:
            arq.unlink()
            removidos.append(arq)
        except FileNotFoundError:
            pass                                    # outro programa já removeu
        except OSError as exc:
            _avisar("limpeza", f"Não foi possível remover {arq}: {exc}")
    if removidos:
        log.info("Logs fatais expirados removidos: %s", len(removidos))
    return removidos


# ---------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------
class FatalDiarioHandler(logging.Handler):
    """Grava CRITICAL (e registros marcados) em um arquivo por dia; nunca propaga falhas."""

    def __init__(self, programa: str, pasta: Optional[Path] = None):
        super().__init__(level=logging.DEBUG)
        self.addFilter(_deve_gravar)
        self.programa = programa
        self.pasta = Path(pasta) if pasta else pasta_padrao()
        self._dia_limpo: Optional[date] = None
        self._parar = threading.Event()
        self.setFormatter(logging.Formatter(_FORMATO))

    def arquivo_do_dia(self, dia: date) -> Path:
        return self.pasta / f"fatal-{dia.isoformat()}.log"

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if not hasattr(record, "programa"):
                record.programa = self.programa
            texto = f"{self.format(record)}\n{_SEPARADOR}\n"
            dia = datetime.fromtimestamp(record.created).date()
            self.pasta.mkdir(parents=True, exist_ok=True)
            with open(self.arquivo_do_dia(dia), "a", encoding="utf-8") as f:
                f.write(texto)                      # bloco único por evento
        except Exception as exc:  # noqa: BLE001
            _avisar("escrita", f"Falha ao gravar log fatal em {self.pasta}: {exc}")
        self.verificar_limpeza()

    def verificar_limpeza(self, hoje: Optional[date] = None) -> None:
        """Limpa no máximo uma vez por dia (troca de dia dispara nova limpeza)."""
        hoje = hoje or date.today()
        if self._dia_limpo == hoje:
            return
        self._dia_limpo = hoje
        try:
            limpar_expirados(self.pasta, hoje=hoje)
        except Exception as exc:  # noqa: BLE001
            _avisar("limpeza", f"Falha na limpeza de logs fatais: {exc}")

    def iniciar_agendador(self) -> None:
        """Thread daemon: garante a limpeza em totens que ficam dias ligados."""
        def loop():
            while not self._parar.wait(LOGS.intervalo_limpeza_segundos):
                self.verificar_limpeza()
        threading.Thread(target=loop, name="limpeza-logs-fatais", daemon=True).start()

    def close(self) -> None:
        self._parar.set()
        super().close()


# ---------------------------------------------------------------------
# Instalação
# ---------------------------------------------------------------------
def _instalar_hooks() -> None:
    fatal = logging.getLogger("fatal")
    anterior_sys = sys.excepthook
    anterior_thread = threading.excepthook

    def hook_sys(tipo, valor, tb):
        if not issubclass(tipo, KeyboardInterrupt):
            fatal.critical("Exceção não tratada encerrou o programa.",
                           exc_info=(tipo, valor, tb))
        anterior_sys(tipo, valor, tb)

    def hook_thread(args):
        if not issubclass(args.exc_type, SystemExit):
            nome = args.thread.name if args.thread else "?"
            fatal.critical("Exceção não tratada na thread %s.", nome,
                           exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        anterior_thread(args)

    sys.excepthook = hook_sys
    threading.excepthook = hook_thread


def instalar(programa: str, pasta: Optional[Path] = None) -> FatalDiarioHandler:
    """Ativa o registro de logs fatais no processo (idempotente)."""
    global _handler
    with _instalar_lock:
        if _handler is not None:
            return _handler
        h = FatalDiarioHandler(programa, pasta)
        logging.getLogger().addHandler(h)
        _instalar_hooks()
        h.verificar_limpeza()
        h.iniciar_agendador()
        _handler = h
        log.info("Logs fatais ativos em %s (retenção %s dia(s)).",
                 h.pasta, retencao_dias(h.pasta))
        return h
