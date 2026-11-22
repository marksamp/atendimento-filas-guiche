"""
Configurações locais do app Guichê (autônomo).
FILA deve ter os MESMOS valores do config.py do Totem (posição estimada coerente).
"""
from dataclasses import dataclass

APP_NAME = "SistemaFilas-Guiche"
VERSAO = "1.3.0"
SCHEMA_MIN = 9                      # migração 009 (ícone PNG dos setores no banco)
TIPOS_BANCO = {"MySQL": 3306}       # MySQL 8+ (FOR UPDATE OF ... SKIP LOCKED)


@dataclass
class DBSettings:
    tipo: str = "MySQL"
    host: str = ""
    port: int = 3306
    database: str = "sistema_filas"
    user: str = ""
    password: str = ""
    pool_size: int = 5

    def validar(self) -> dict[str, str]:
        erros: dict[str, str] = {}
        if self.tipo not in TIPOS_BANCO:
            erros["tipo"] = "Tipo de banco não suportado."
        if not self.host:
            erros["host"] = "Informe o host ou IP."
        if not 1 <= int(self.port or 0) <= 65535:
            erros["port"] = "Porta entre 1 e 65535."
        if not self.database:
            erros["database"] = "Informe o nome do banco."
        if not self.user:
            erros["user"] = "Informe o usuário."
        if not self.password:
            erros["password"] = "Informe a senha."
        return erros


@dataclass(frozen=True)
class FilaConfig:
    # Após N prioritárias seguidas, uma normal é chamada obrigatoriamente
    max_prioritarias_seguidas: int = 2
    # Cada ponto de peso equivale a N minutos de espera (aging) — igual ao Totem
    fator_peso: int = 15


@dataclass(frozen=True)
class UIConfig:
    atualizar_ms: int = 3000        # refresh da fila na tela de atendimento
    max_itens_lista: int = 40


FILA = FilaConfig()
UI = UIConfig()
