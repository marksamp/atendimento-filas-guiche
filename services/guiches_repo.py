"""SQL dos guichês (sempre dentro do cursor/transação recebido)."""
from typing import Optional

_EM_USO = (
    "EXISTS (SELECT 1 FROM sessoes_guiche sg WHERE sg.guiche_id = g.id AND sg.fim_em IS NULL)"
)
_ATENDENDO = (
    "EXISTS (SELECT 1 FROM senhas s WHERE s.guiche_id = g.id "
    "AND s.status IN ('chamando','em_atendimento'))"
)
_HISTORICO = (
    "(EXISTS (SELECT 1 FROM senhas s WHERE s.guiche_id = g.id) "
    "OR EXISTS (SELECT 1 FROM sessoes_guiche sg WHERE sg.guiche_id = g.id))"
)


def listar(cur) -> list[dict]:
    cur.execute(
        f"SELECT g.id, g.nome, g.ativo, {_EM_USO} AS em_uso "
        "FROM guiches g "
        "ORDER BY g.ativo DESC, g.nome")
    return cur.fetchall()


def obter(cur, gid: int, travar: bool = False) -> Optional[dict]:
    cur.execute(
        f"SELECT g.id, g.nome, g.ativo, {_EM_USO} AS em_uso, "
        f"       {_ATENDENDO} AS atendendo, {_HISTORICO} AS tem_historico "
        f"FROM guiches g WHERE g.id = %s{' FOR UPDATE' if travar else ''}", (gid,))
    return cur.fetchone()


def nome_em_uso(cur, nome: str, ignorar_id: Optional[int] = None) -> bool:
    cur.execute("SELECT 1 AS ok FROM guiches WHERE nome = %s AND id <> %s",
                (nome, ignorar_id or 0))
    return cur.fetchone() is not None


def inserir(cur, nome: str) -> int:
    cur.execute("INSERT INTO guiches (nome) VALUES (%s)", (nome,))
    return int(cur.lastrowid)


def atualizar(cur, gid: int, nome: str) -> None:
    cur.execute("UPDATE guiches SET nome = %s WHERE id = %s", (nome, gid))


def definir_ativo(cur, gid: int, ativo: bool) -> None:
    cur.execute("UPDATE guiches SET ativo = %s WHERE id = %s", (int(ativo), gid))


def excluir(cur, gid: int) -> int:
    cur.execute("DELETE FROM guiches WHERE id = %s", (gid,))
    return cur.rowcount
