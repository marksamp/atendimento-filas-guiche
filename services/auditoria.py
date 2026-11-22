"""
Auditoria das ações do Guichê (quem, quando, de qual guichê).

- registrar(): grava na MESMA transação do cursor recebido, então a ação e
  o registro são confirmados juntos.
- ja_processada(): idempotência pelo uuid da requisição (reenvio após queda).
- limpar_expirados(): remove registros fora da retenção (em lotes).
LGPD: nunca grave nomes de pacientes nem texto livre com dados pessoais em `detalhe`.
"""
import logging
from typing import Optional

from database import db

log = logging.getLogger(__name__)

ACOES = frozenset({
    # Sessão / autenticação
    "login", "logout", "sessao_expirada", "sessao_encerrar", "troca_senha",
    # Atendimento
    "chamar", "repetir", "iniciar", "finalizar", "ausente", "reativar",
    "pausa", "retomar", "transferir", "chamada_manual", "senhas_liberar",
    # Gestão geral
    "letreiro", "usuario", "manutencao",
    # Mídias
    "midia_cadastrar", "midia_editar", "midia_excluir", "slideshow_token",
    # Guichês
    "guiche_cadastrar", "guiche_editar", "guiche_ativar", "guiche_desativar",
    "guiche_excluir",
    # Usuários
    "usuario_cadastrar", "usuario_editar", "usuario_ativar", "usuario_desativar",
    "usuario_desbloquear", "usuario_excluir",
    # Setores
    "setor_cadastrar", "setor_editar", "setor_ativar", "setor_desativar",
    "setor_excluir", "setor_ordem", "setor_icones",
})

_LOTE = 5000


def registrar(cur, acao: str, usuario_id: Optional[int] = None,
              guiche_id: Optional[int] = None, senha_id: Optional[int] = None,
              detalhe: Optional[str] = None, requisicao: Optional[str] = None) -> bool:
    """True se gravou; False se a requisição já existia."""
    if acao not in ACOES:
        raise ValueError(f"Ação de auditoria desconhecida: {acao}")
    cur.execute(
        "INSERT IGNORE INTO auditoria "
        "(usuario_id, guiche_id, senha_id, acao, detalhe, requisicao) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (usuario_id, guiche_id, senha_id, acao,
         (detalhe or None) and str(detalhe)[:255], requisicao),
    )
    return cur.rowcount > 0


def ja_processada(cur, requisicao: Optional[str]) -> bool:
    if not requisicao:
        return False
    cur.execute("SELECT 1 AS ok FROM auditoria WHERE requisicao = %s", (requisicao,))
    return cur.fetchone() is not None


def limpar_expirados(dias: int) -> int:
    total = 0
    while True:
        n = db.execute(
            "DELETE FROM auditoria WHERE ocorrido_em < NOW() - INTERVAL %s DAY LIMIT %s",
            (int(dias), _LOTE),
        )
        total += n
        if n < _LOTE:
            break
    if total:
        log.info("Auditoria: %s registro(s) expirado(s) removido(s).", total)
    return total
