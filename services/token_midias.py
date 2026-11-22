"""
Token do servidor de mídias (config 'slideshow.token').

- garantir(): gera uma única vez. UPDATE ... WHERE valor = '' + releitura:
  dois guichês simultâneos acabam com o MESMO token.
- recente(): token gerado por este app há pouco; os painéis guardam o token
  em cache por até 30 s e podem responder 401 nesse intervalo.
"""
import secrets
import time

from config_slideshow import SLIDESHOW
from database import db
from services import auditoria

_CHAVE = "slideshow.token"
_gerado_em = 0.0


def ler() -> str:
    row = db.fetch_one("SELECT valor FROM config WHERE chave = %s", (_CHAVE,))
    return ((row or {}).get("valor") or "").strip()


def garantir(usuario_id: int) -> str:
    global _gerado_em
    atual = ler()
    if atual:
        return atual
    novo = secrets.token_urlsafe(32)
    with db.cursor() as cur:
        cur.execute("INSERT IGNORE INTO config (chave, valor) VALUES (%s, '')", (_CHAVE,))
        cur.execute("UPDATE config SET valor = %s WHERE chave = %s AND valor = ''",
                    (novo, _CHAVE))
        gerou = cur.rowcount > 0
        if gerou:
            auditoria.registrar(cur, "slideshow_token", usuario_id, detalhe="gerado")
    if gerou:
        _gerado_em = time.monotonic()
    return ler()


def recente() -> bool:
    return bool(_gerado_em) and (
        time.monotonic() - _gerado_em < SLIDESHOW.token_cache_segundos + 5)
