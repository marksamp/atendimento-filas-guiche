"""
Acesso ao MySQL do Guichê (pool thread-safe).

- db.cursor(): uma transação (commit ao sair; rollback em exceção).
- FOUND_ROWS: rowcount = linhas encontradas (UPDATE sem mudança real conta).
- FUSO_HORARIO aplicado em todas as conexões (NOW()/CURDATE() coerentes).
- testar_conexao(): conecta e exige schema_versao >= SCHEMA_MIN.
"""
import itertools
import logging
from contextlib import contextmanager
from typing import Optional

import mysql.connector
from mysql.connector import errorcode, errors, pooling
from mysql.connector.constants import ClientFlag

from config import SCHEMA_MIN, DBSettings

log = logging.getLogger(__name__)

FUSO_HORARIO = "-03:00"
_ERROS_REDE = {2003, 2005, 2006, 2013, 2055}
_contador = itertools.count(1)


class ErroConexao(Exception):
    """Falha com mensagem pronta para a tela."""


def _parametros(s: DBSettings) -> dict:
    return {
        "host": s.host, "port": int(s.port), "database": s.database,
        "user": s.user, "password": s.password, "charset": "utf8mb4",
        "connection_timeout": 5, "autocommit": False, "time_zone": FUSO_HORARIO,
        "client_flags": [ClientFlag.FOUND_ROWS],
    }


def eh_erro_rede(exc: BaseException) -> bool:
    return isinstance(exc, (errors.InterfaceError, errors.OperationalError,
                            errors.PoolError, ErroConexao))


def descrever_erro(exc: BaseException, s: Optional[DBSettings] = None) -> str:
    if isinstance(exc, ErroConexao):
        return str(exc)
    if isinstance(exc, mysql.connector.Error):
        n = exc.errno
        if n == errorcode.ER_ACCESS_DENIED_ERROR:
            return "Usuário ou senha do banco inválidos."
        if n == errorcode.ER_BAD_DB_ERROR:
            return "Banco de dados não encontrado."
        if n in (errorcode.ER_TABLEACCESS_DENIED_ERROR, errorcode.ER_DBACCESS_DENIED_ERROR):
            return "Usuário do banco sem permissão."
        if n in _ERROS_REDE or n is None or n == -1:
            alvo = f" ({s.host}:{s.port})" if s else ""
            return f"Servidor do banco inacessível{alvo}."
        return f"Erro do banco de dados ({n})."
    return "Erro inesperado. Consulte o log."


def testar_conexao(s: DBSettings) -> None:
    try:
        conn = mysql.connector.connect(**_parametros(s))
    except mysql.connector.Error as exc:
        raise ErroConexao(descrever_erro(exc, s)) from exc
    try:
        cur = conn.cursor()
        try:
            cur.execute("SELECT MAX(versao) FROM schema_versao")
            versao = cur.fetchone()[0] or 0
        except mysql.connector.Error as exc:
            raise ErroConexao("Banco sem a migração 002 (schema_versao ausente).") from exc
        if versao < SCHEMA_MIN:
            raise ErroConexao(f"Esquema v{versao}; o Guichê requer v{SCHEMA_MIN}.")
    finally:
        conn.close()


class Database:
    def __init__(self):
        self._pool: Optional[pooling.MySQLConnectionPool] = None
        self.settings: Optional[DBSettings] = None

    def configure(self, s: DBSettings) -> None:
        # pool_reset_session=False: preserva time_zone da sessão
        self._pool = pooling.MySQLConnectionPool(
            pool_name=f"guiche{next(_contador)}", pool_size=max(2, s.pool_size),
            pool_reset_session=False, **_parametros(s),
        )
        self.settings = s
        log.info("Pool configurado (%s@%s:%s/%s).", s.user, s.host, s.port, s.database)

    def _conexao(self):
        if self._pool is None:
            raise ErroConexao("Banco de dados não configurado.")
        conn = self._pool.get_connection()
        try:
            conn.ping(reconnect=True, attempts=1, delay=0)
        except Exception:
            conn.close()
            raise
        return conn

    @contextmanager
    def cursor(self):
        conn = self._conexao()
        cur = conn.cursor(dictionary=True)
        try:
            yield cur
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            raise
        finally:
            cur.close()
            conn.close()

    def fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
        with self.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def fetch_one(self, sql: str, params: tuple = ()) -> Optional[dict]:
        with self.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def execute(self, sql: str, params: tuple = ()) -> int:
        with self.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount


db = Database()