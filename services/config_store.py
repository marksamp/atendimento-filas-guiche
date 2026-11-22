"""
Persistência segura da conexão do Guichê (uma única conexão: banco de senhas).

- Dados não sensíveis -> JSON na pasta de configuração do usuário.
- Senha -> cofre do SO (keyring); fallback: Fernet com chave em arquivo 600.
- Preferências locais (último guichê usado) -> preferencias.json.
Gravações atômicas (arquivo temporário + os.replace).
"""
import json
import logging
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from config import APP_NAME, DBSettings

log = logging.getLogger(__name__)

_SERVICO = f"{APP_NAME}-db"
_CONTA = "db_password"


# ---------------------------------------------------------------------
# Caminhos
# ---------------------------------------------------------------------
def _restringir(caminho: Path, modo: int) -> None:
    try:
        os.chmod(caminho, modo)
    except OSError:
        pass


def pasta_config() -> Path:
    if sys.platform == "win32":
        base = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
    pasta = base / APP_NAME
    pasta.mkdir(parents=True, exist_ok=True)
    _restringir(pasta, 0o700)
    return pasta


def _arquivo(nome: str) -> Path:
    return pasta_config() / nome


def _gravar_json(arq: Path, conteudo: dict) -> None:
    tmp = arq.with_suffix(".tmp")
    tmp.write_text(json.dumps(conteudo, indent=2, ensure_ascii=False), encoding="utf-8")
    _restringir(tmp, 0o600)
    os.replace(tmp, arq)


def _ler_json(arq: Path) -> dict:
    try:
        dados = json.loads(arq.read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


# ---------------------------------------------------------------------
# Segredo
# ---------------------------------------------------------------------
def _keyring():
    try:
        import keyring
        from keyring.backends import fail

        return None if isinstance(keyring.get_keyring(), fail.Keyring) else keyring
    except Exception:  # noqa: BLE001
        return None


def _fernet():
    from cryptography.fernet import Fernet

    arq = _arquivo(".db_key")
    if not arq.exists():
        arq.write_bytes(Fernet.generate_key())
        _restringir(arq, 0o600)
    return Fernet(arq.read_bytes())


def _guardar_senha(senha: str) -> dict:
    kr = _keyring()
    if kr:
        try:
            kr.set_password(_SERVICO, _CONTA, senha)
            return {"metodo": "keyring"}
        except Exception:  # noqa: BLE001
            log.warning("Cofre do SO indisponível; usando criptografia local.")
    return {"metodo": "fernet", "valor": _fernet().encrypt(senha.encode()).decode("ascii")}


def _ler_senha(segredo: dict) -> Optional[str]:
    try:
        if segredo.get("metodo") == "keyring":
            kr = _keyring()
            return kr.get_password(_SERVICO, _CONTA) if kr else None
        if segredo.get("metodo") == "fernet":
            return _fernet().decrypt(segredo["valor"].encode("ascii")).decode()
    except Exception:  # noqa: BLE001
        log.warning("Não foi possível recuperar a senha armazenada.")
    return None


# ---------------------------------------------------------------------
# API pública: conexão
# ---------------------------------------------------------------------
def carregar() -> tuple[Optional[DBSettings], bool]:
    """(settings, completo). completo = dados válidos e senha recuperada."""
    dados = _ler_json(_arquivo("db_config.json"))
    bruto = dados.get("db")
    if not isinstance(bruto, dict):
        return None, False
    try:
        s = DBSettings(tipo=str(bruto["tipo"]), host=str(bruto["host"]),
                       port=int(bruto["port"]), database=str(bruto["database"]),
                       user=str(bruto["user"]), pool_size=int(bruto.get("pool_size", 5)))
    except Exception:  # noqa: BLE001
        log.warning("Arquivo de configuração inválido.")
        return None, False
    senha = _ler_senha(dados.get("segredo", {}))
    if senha is None:
        return s, False
    s.password = senha
    return s, not s.validar()


def salvar(s: DBSettings) -> None:
    publico = asdict(s)
    publico.pop("password")
    _gravar_json(_arquivo("db_config.json"),
                 {"versao": 1, "db": publico, "segredo": _guardar_senha(s.password)})
    log.info("Conexão salva (%s@%s:%s/%s).", s.user, s.host, s.port, s.database)


def remover() -> None:
    kr = _keyring()
    if kr:
        try:
            kr.delete_password(_SERVICO, _CONTA)
        except Exception:  # noqa: BLE001
            pass
    for nome in ("db_config.json", ".db_key"):
        _arquivo(nome).unlink(missing_ok=True)


# ---------------------------------------------------------------------
# API pública: preferências locais
# ---------------------------------------------------------------------
def ler_preferencia(chave: str, padrao: Any = None) -> Any:
    return _ler_json(_arquivo("preferencias.json")).get(chave, padrao)


def gravar_preferencia(chave: str, valor: Any) -> None:
    arq = _arquivo("preferencias.json")
    dados = _ler_json(arq)
    dados[chave] = valor
    _gravar_json(arq, dados)
