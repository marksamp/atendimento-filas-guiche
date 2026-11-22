"""
Parâmetros centrais lidos da tabela `config` (iguais em todas as máquinas).

- obter(): valores com cache de 60 s; sem banco, usa o último lido ou o padrão.
- Valores inválidos ou ausentes no banco caem no padrão da dataclass.
"""
import logging
import threading
import time
from dataclasses import dataclass, fields
from typing import Optional

from database import db, descrever_erro

log = logging.getLogger(__name__)

_CACHE_SEG = 60


@dataclass(frozen=True)
class Parametros:
    max_repeticoes: int = 3
    intervalo_repeticao_seg: int = 5
    max_reativacoes: int = 2
    sessao_timeout_seg: int = 60
    ping_seg: int = 15
    painel_offline_seg: int = 45
    retencao_auditoria_dias: int = 90
    login_max_tentativas: int = 5
    login_bloqueio_min: int = 5
    senha_min: int = 6


_lock = threading.Lock()
_cache: Optional[Parametros] = None
_lido_em = 0.0


def _converter(linhas: list[dict]) -> Parametros:
    brutos = {r["chave"]: r["valor"] for r in linhas}
    valores = {}
    for f in fields(Parametros):
        bruto = brutos.get(f.name)
        if bruto is None:
            continue
        try:
            n = int(str(bruto).strip())
        except ValueError:
            log.warning("Parâmetro inválido em config: %s=%r; usando o padrão.", f.name, bruto)
            continue
        if n >= 0:
            valores[f.name] = n
    return Parametros(**valores)


def obter(forcar: bool = False) -> Parametros:
    global _cache, _lido_em
    with _lock:
        if _cache and not forcar and time.monotonic() - _lido_em < _CACHE_SEG:
            return _cache
    try:
        novo = _converter(db.fetch_all("SELECT chave, valor FROM config"))
    except Exception as exc:  # noqa: BLE001
        log.warning("Falha ao ler parâmetros: %s", descrever_erro(exc))
        return _cache or Parametros()
    with _lock:
        _cache, _lido_em = novo, time.monotonic()
    return novo


def ler_texto(chave: str, padrao: str = "") -> str:
    row = db.fetch_one("SELECT valor FROM config WHERE chave = %s", (chave,))
    return row["valor"] if row else padrao


def gravar_texto(chave: str, valor: str) -> None:
    db.execute(
        "INSERT INTO config (chave, valor) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE valor = VALUES(valor)",
        (chave, str(valor)[:255]),
    )
