"""
Regras de fila do Guichê (chamada e atendimento). App autônomo: a emissão
de senhas é responsabilidade exclusiva do Totem.

ALGORITMO JUSTO (anti-starvation), em duas camadas:
1) Aging:  score = peso * FATOR_PESO + minutos_de_espera
2) Intercalação: após MAX_PRIORITARIAS_SEGUIDAS prioritárias seguidas no
   setor, havendo normal aguardando, chama a normal mais antiga.
Desempate: a mais antiga (emitida_em, depois id).
Vários setores ("próxima geral"): aplica a regra em cada setor. Se algum setor
tiver intercalação obrigatória, a normal forçada vence (a mais antiga entre
elas); senão, vence a de maior score (desempate: a mais antiga).

LISTA DA FILA: simula chamadas sucessivas com o mesmo algoritmo, partindo
do estado atual de controle_fila → mostra a ordem real de chamada.

CICLO DE VIDA:
    aguardando → chamando → em_atendimento → atendido
                    ↓
                 ausente → (reativar) → aguardando
    Dias anteriores: aguardando → cancelada | chamando → ausente
                     em_atendimento → atendido
    Liberação (sessão expirada / usuário desativado ou excluído):
                     chamando → aguardando | em_atendimento → atendido

- Setor inativo: não recebe senhas novas (bloqueio no Totem); as senhas já
  emitidas continuam sendo chamadas, listadas e reativadas até zerar.
- listar_setores() devolve só os ativos (cadastro de usuários).
- O atendente só chama a próxima depois de finalizar a atual ou marcá-la como ausente.
- qtd_chamadas é contado SOMENTE pelo Painel.
- repetir_chamada(): nova chamada_em + anunciada = 0 (o Painel anuncia de novo).
- Toda ação grava auditoria na mesma transação; `requisicao` (uuid) torna
  a ação idempotente.

FUSO HORÁRIO: definido em database.py (FUSO_HORARIO) para todas as conexões.
"""
import logging
from typing import Optional, Sequence

from config import FILA
from database import db
from services import auditoria, parametros

log = logging.getLogger(__name__)

# Filtro "somente hoje" compatível com índice (evita DATE(coluna) = ...)
_FILTRO_HOJE = ("s.emitida_em >= CURDATE() "
                "AND s.emitida_em < CURDATE() + INTERVAL 1 DAY")

STATUS_ABERTOS = ("chamando", "em_atendimento")

_SELECT_SENHA = """
    SELECT s.id, s.numero, s.status, s.setor_id, st.nome AS setor, st.cor,
           c.nome AS prioridade, c.peso, s.emitida_em, s.chamada_em,
           s.atendimento_em, s.finalizada_em, s.repeticoes, s.reativacoes,
           s.guiche_id, s.usuario_id,
           TIMESTAMPDIFF(MINUTE, s.emitida_em, NOW()) AS espera_min
    FROM senhas s
    JOIN setores st              ON st.id = s.setor_id
    JOIN categorias_prioridade c ON c.id  = s.prioridade_id
"""


class RegraViolada(ValueError):
    """Ação não permitida pela regra de negócio (mensagem segura para a tela)."""


# ---------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------
def _ids(setor_ids: Sequence[int]) -> tuple[int, ...]:
    ids = tuple(sorted({int(i) for i in setor_ids or ()}))
    if not ids:
        raise RegraViolada("Nenhum setor selecionado.")
    return ids


def _marcadores(n: int) -> str:
    return ", ".join(["%s"] * n)


def _pontuacao(c: dict) -> int:
    return int(c["peso"]) * FILA.fator_peso + max(0, int(c["espera_min"] or 0))


def _antiguidade(c: dict) -> tuple:
    return c["emitida_em"], int(c["id"])


def _chave(c: dict) -> tuple:
    """Maior score; desempate: a mais antiga (emitida_em, depois id)."""
    return _pontuacao(c), -c["emitida_em"].timestamp(), -int(c["id"])


def _normalizar(row: Optional[dict]) -> Optional[dict]:
    if row:
        row["prioritaria"] = int(row["peso"]) > 0
        row["pontuacao"] = _pontuacao(row)
    return row


def _detalhar(cur, senha_id: int) -> Optional[dict]:
    cur.execute(_SELECT_SENHA + " WHERE s.id = %s", (senha_id,))
    return _normalizar(cur.fetchone())


def _aberta(cur, guiche_id: int, usuario_id: int) -> Optional[dict]:
    cur.execute(
        _SELECT_SENHA
        + " WHERE (s.guiche_id = %s OR s.usuario_id = %s) AND s.status IN (%s, %s)"
        + " ORDER BY s.chamada_em DESC LIMIT 1",
        (guiche_id, usuario_id, *STATUS_ABERTOS),
    )
    return _normalizar(cur.fetchone())


# ---------------------------------------------------------------------
# Cadastro
# ---------------------------------------------------------------------
def listar_setores() -> list[dict]:
    return db.fetch_all(
        "SELECT id, nome, descricao, prefixo, icone, cor "
        "FROM setores WHERE ativo = 1 ORDER BY ordem, nome"
    )


# ---------------------------------------------------------------------
# Escolha (funções puras, testáveis)
# ---------------------------------------------------------------------
def _escolher_proxima(candidatas: list[dict], prioritarias_seguidas: int) -> tuple[dict, bool]:
    """Intercalação obrigatória + aging, dentro de um setor. Retorna (senha, forçada)."""
    normais = [c for c in candidatas if int(c["peso"]) == 0]
    if prioritarias_seguidas >= FILA.max_prioritarias_seguidas and normais:
        return min(normais, key=_antiguidade), True
    return max(candidatas, key=_chave), False


def _escolher_entre_setores(candidatas: list[dict], seguidas: dict[int, int]) -> dict:
    por_setor: dict[int, list[dict]] = {}
    for c in candidatas:
        por_setor.setdefault(c["setor_id"], []).append(c)
    vencedoras = [_escolher_proxima(lista, seguidas.get(sid, 0))
                  for sid, lista in por_setor.items()]
    forcadas = [c for c, forcada in vencedoras if forcada]
    if forcadas:
        return min(forcadas, key=_antiguidade)
    return max((c for c, _ in vencedoras), key=_chave)


def _proximo_contador(seguidas: dict[int, int], escolhida: dict) -> int:
    sid = escolhida["setor_id"]
    return min(seguidas.get(sid, 0) + 1, 255) if int(escolhida["peso"]) > 0 else 0


def _ordem_chamada(candidatas: list[dict], seguidas: dict[int, int]) -> list[dict]:
    """Simula chamadas sucessivas: retorna as senhas na ordem real de chamada."""
    restantes = list(candidatas)
    seg = dict(seguidas)
    ordem: list[dict] = []
    while restantes:
        e = _escolher_entre_setores(restantes, seg)
        seg[e["setor_id"]] = _proximo_contador(seg, e)
        ordem.append(e)
        restantes = [c for c in restantes if c is not e]
    return ordem


# ---------------------------------------------------------------------
# Chamada
# ---------------------------------------------------------------------
def chamar_proxima(setor_ids: Sequence[int], guiche_id: int, usuario_id: int,
                   requisicao: Optional[str] = None) -> Optional[dict]:
    """
    Chama a próxima senha entre os setores informados (um setor = "próxima do
    setor"; todos os do usuário = "próxima geral"). None = fila vazia.
    Setor inativo também é chamado (esvazia as senhas já emitidas).
    """
    ids = _ids(setor_ids)
    m = _marcadores(len(ids))
    with db.cursor() as cur:
        if auditoria.ja_processada(cur, requisicao):
            return _aberta(cur, guiche_id, usuario_id)
        if _aberta(cur, guiche_id, usuario_id):
            raise RegraViolada("Finalize o atendimento atual antes de chamar a próxima senha.")

        # Linhas de controle travadas em ordem de id (evita deadlock entre guichês)
        cur.execute(f"INSERT IGNORE INTO controle_fila (setor_id) "
                    f"SELECT id FROM setores WHERE id IN ({m})", ids)
        cur.execute(f"SELECT setor_id, prioritarias_seguidas FROM controle_fila "
                    f"WHERE setor_id IN ({m}) ORDER BY setor_id FOR UPDATE", ids)
        seguidas = {r["setor_id"]: r["prioritarias_seguidas"] for r in cur.fetchall()}

        # OF s: trava só as senhas (não as categorias, compartilhadas)
        cur.execute(
            f"""
            SELECT s.id, s.numero, s.setor_id, s.emitida_em, c.peso,
                   TIMESTAMPDIFF(MINUTE, s.emitida_em, NOW()) AS espera_min
            FROM senhas s
            JOIN categorias_prioridade c ON c.id = s.prioridade_id
            WHERE s.setor_id IN ({m}) AND s.status = 'aguardando' AND {_FILTRO_HOJE}
            ORDER BY s.emitida_em, s.id
            FOR UPDATE OF s SKIP LOCKED
            """,
            ids,
        )
        candidatas = cur.fetchall()
        if not candidatas:
            return None

        escolhida = _escolher_entre_setores(candidatas, seguidas)
        sid = escolhida["setor_id"]

        cur.execute(
            """
            UPDATE senhas
               SET status = 'chamando', chamada_em = NOW(), guiche_id = %s,
                   usuario_id = %s, anunciada = 0, repeticoes = 0
             WHERE id = %s
            """,
            (guiche_id, usuario_id, escolhida["id"]),
        )
        cur.execute("UPDATE controle_fila SET prioritarias_seguidas = %s WHERE setor_id = %s",
                    (_proximo_contador(seguidas, escolhida), sid))
        cur.execute(
            "UPDATE painel_estado SET modo = 'chamada', ultima_senha_id = %s WHERE id = 1",
            (escolhida["id"],),
        )
        auditoria.registrar(cur, "chamar", usuario_id, guiche_id, escolhida["id"],
                            "geral" if len(ids) > 1 else f"setor={sid}", requisicao)
        dados = _detalhar(cur, escolhida["id"])

    log.info("Chamada: %s (guichê %s)", escolhida["numero"], guiche_id)
    return dados


def repetir_chamada(senha_id: int, guiche_id: int, usuario_id: int,
                    requisicao: Optional[str] = None) -> dict:
    """O paciente não apareceu ainda: o Painel anuncia a mesma senha de novo."""
    p = parametros.obter()
    with db.cursor() as cur:
        if not auditoria.ja_processada(cur, requisicao):
            cur.execute(
                """
                UPDATE senhas
                   SET chamada_em = NOW(), anunciada = 0, repeticoes = repeticoes + 1
                 WHERE id = %s AND usuario_id = %s AND status = 'chamando'
                   AND repeticoes < %s
                   AND chamada_em <= NOW() - INTERVAL %s SECOND
                """,
                (senha_id, usuario_id, p.max_repeticoes, p.intervalo_repeticao_seg),
            )
            if cur.rowcount == 0:
                atual = _detalhar(cur, senha_id)
                if not atual or atual["status"] != "chamando" or atual["usuario_id"] != usuario_id:
                    raise RegraViolada("Esta senha não está mais em chamada.")
                if atual["repeticoes"] >= p.max_repeticoes:
                    raise RegraViolada(f"Limite de {p.max_repeticoes} repetições atingido.")
                raise RegraViolada(f"Aguarde {p.intervalo_repeticao_seg} s entre as chamadas.")
            cur.execute(
                "UPDATE painel_estado SET modo = 'chamada', ultima_senha_id = %s WHERE id = 1",
                (senha_id,),
            )
            auditoria.registrar(cur, "repetir", usuario_id, guiche_id, senha_id,
                                requisicao=requisicao)
        return _detalhar(cur, senha_id)


def _transicao(acao: str, senha_id: int, guiche_id: int, usuario_id: int,
               requisicao: Optional[str], de: str, sets: str, erro: str) -> dict:
    with db.cursor() as cur:
        if not auditoria.ja_processada(cur, requisicao):
            cur.execute(
                f"UPDATE senhas SET {sets} WHERE id = %s AND usuario_id = %s AND status = %s",
                (senha_id, usuario_id, de),
            )
            if cur.rowcount == 0:
                raise RegraViolada(erro)
            auditoria.registrar(cur, acao, usuario_id, guiche_id, senha_id,
                                requisicao=requisicao)
        return _detalhar(cur, senha_id)


def iniciar_atendimento(senha_id: int, guiche_id: int, usuario_id: int,
                        requisicao: Optional[str] = None) -> dict:
    return _transicao("iniciar", senha_id, guiche_id, usuario_id, requisicao,
                      "chamando", "status = 'em_atendimento', atendimento_em = NOW()",
                      "Só é possível iniciar o atendimento de uma senha em chamada.")


def finalizar_atendimento(senha_id: int, guiche_id: int, usuario_id: int,
                          requisicao: Optional[str] = None) -> dict:
    return _transicao("finalizar", senha_id, guiche_id, usuario_id, requisicao,
                      "em_atendimento", "status = 'atendido', finalizada_em = NOW()",
                      "Só é possível finalizar uma senha em atendimento.")


def marcar_ausente(senha_id: int, guiche_id: int, usuario_id: int,
                   requisicao: Optional[str] = None) -> dict:
    return _transicao("ausente", senha_id, guiche_id, usuario_id, requisicao,
                      "chamando", "status = 'ausente', finalizada_em = NOW()",
                      "Só é possível marcar como ausente uma senha em chamada.")


def reativar(senha_id: int, setor_ids: Sequence[int], guiche_id: int, usuario_id: int,
             requisicao: Optional[str] = None) -> dict:
    """Ausente de hoje volta para a fila com o emitida_em original (setor inativo incluso)."""
    ids = _ids(setor_ids)
    p = parametros.obter()
    with db.cursor() as cur:
        if not auditoria.ja_processada(cur, requisicao):
            cur.execute(
                f"""
                UPDATE senhas s
                   SET s.status = 'aguardando', s.chamada_em = NULL, s.atendimento_em = NULL,
                       s.finalizada_em = NULL, s.guiche_id = NULL, s.usuario_id = NULL,
                       s.anunciada = 0, s.repeticoes = 0, s.reativacoes = s.reativacoes + 1
                 WHERE s.id = %s AND s.status = 'ausente' AND s.reativacoes < %s
                   AND s.setor_id IN ({_marcadores(len(ids))}) AND {_FILTRO_HOJE}
                """,
                (senha_id, p.max_reativacoes, *ids),
            )
            if cur.rowcount == 0:
                atual = _detalhar(cur, senha_id)
                if atual and atual["status"] == "ausente" and atual["reativacoes"] >= p.max_reativacoes:
                    raise RegraViolada(f"Limite de {p.max_reativacoes} reativações atingido.")
                raise RegraViolada("Esta senha não pode ser reativada.")
            auditoria.registrar(cur, "reativar", usuario_id, guiche_id, senha_id,
                                requisicao=requisicao)
        return _detalhar(cur, senha_id)


# ---------------------------------------------------------------------
# Liberação (sessão expirada, usuário desativado/excluído)
# ---------------------------------------------------------------------
def liberar_abertas(cur, usuario_id: int, motivo: str) -> int:
    """
    Dentro da transação recebida: 'chamando' volta à fila (aguardando);
    'em_atendimento' é dado como atendido. Retorna o total alterado.
    """
    cur.execute(
        "UPDATE senhas SET status = 'aguardando', chamada_em = NULL, guiche_id = NULL, "
        "usuario_id = NULL, anunciada = 0, repeticoes = 0 "
        "WHERE usuario_id = %s AND status = 'chamando'",
        (usuario_id,),
    )
    devolvidas = cur.rowcount
    cur.execute(
        "UPDATE senhas SET status = 'atendido', finalizada_em = NOW() "
        "WHERE usuario_id = %s AND status = 'em_atendimento'",
        (usuario_id,),
    )
    finalizadas = cur.rowcount
    total = devolvidas + finalizadas
    if total:
        auditoria.registrar(cur, "senhas_liberar", usuario_id,
                            detalhe=f"{motivo} fila={devolvidas} atendido={finalizadas}"[:255])
        log.info("Senhas liberadas do usuário %s (%s): %s", usuario_id, motivo, total)
    return total


# ---------------------------------------------------------------------
# Listagens
# ---------------------------------------------------------------------
def listar_fila(setor_ids: Sequence[int]) -> list[dict]:
    """Aguardando de hoje na ORDEM REAL de chamada ("próxima geral" dos setores)."""
    ids = _ids(setor_ids)
    m = _marcadores(len(ids))
    rows = db.fetch_all(
        _SELECT_SENHA
        + f" WHERE s.setor_id IN ({m}) AND s.status = 'aguardando'"
        + f" AND {_FILTRO_HOJE} ORDER BY s.emitida_em, s.id",
        ids,
    )
    if not rows:
        return []
    seguidas = {r["setor_id"]: int(r["prioritarias_seguidas"]) for r in db.fetch_all(
        f"SELECT setor_id, prioritarias_seguidas FROM controle_fila WHERE setor_id IN ({m})",
        ids,
    )}
    return [_normalizar(r) for r in _ordem_chamada(rows, seguidas)]


def listar_ausentes(setor_ids: Sequence[int], limite: int = 50) -> list[dict]:
    ids = _ids(setor_ids)
    rows = db.fetch_all(
        _SELECT_SENHA
        + f" WHERE s.setor_id IN ({_marcadores(len(ids))})"
        + f" AND s.status = 'ausente' AND {_FILTRO_HOJE}"
        + " ORDER BY s.finalizada_em DESC LIMIT %s",
        (*ids, int(limite)),
    )
    return [_normalizar(r) for r in rows]


def atendimento_aberto(guiche_id: int, usuario_id: int) -> Optional[dict]:
    """Senha em chamada/atendimento do usuário ou do guichê (restauração após queda)."""
    with db.cursor() as cur:
        return _aberta(cur, guiche_id, usuario_id)


# ---------------------------------------------------------------------
# Manutenção diária
# ---------------------------------------------------------------------
def encerrar_dias_anteriores() -> int:
    """Encerra senhas abertas de dias anteriores. Retorna o total alterado."""
    total = 0
    with db.cursor() as cur:
        for de, para in (("aguardando", "cancelada"), ("chamando", "ausente"),
                         ("em_atendimento", "atendido")):
            cur.execute(
                "UPDATE senhas SET status = %s, finalizada_em = COALESCE(finalizada_em, NOW()) "
                "WHERE status = %s AND emitida_em < CURDATE()",
                (para, de),
            )
            total += cur.rowcount
        if total:
            auditoria.registrar(cur, "manutencao", detalhe=f"encerradas={total}")
    if total:
        log.info("Senhas de dias anteriores encerradas: %s", total)
    return total
