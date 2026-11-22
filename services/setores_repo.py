"""SQL dos setores (sempre dentro do cursor/transação recebido)."""
from typing import Optional, Sequence

_HOJE = "s.emitida_em >= CURDATE() AND s.emitida_em < CURDATE() + INTERVAL 1 DAY"
_PENDENTES = (f"(SELECT COUNT(*) FROM senhas s WHERE s.setor_id = st.id AND {_HOJE} "
              "AND s.status IN ('aguardando','chamando','em_atendimento','ausente'))")
_HISTORICO = "EXISTS (SELECT 1 FROM senhas s WHERE s.setor_id = st.id)"
_CAMPOS = (f"st.id, st.nome, st.descricao, st.prefixo, st.icone, st.cor, st.ordem, st.ativo, "
           f"st.icone_hash IS NOT NULL AS tem_png, {_PENDENTES} AS pendentes")


def listar(cur) -> list[dict]:
    cur.execute(f"SELECT {_CAMPOS} FROM setores st ORDER BY st.ordem, st.nome, st.id")
    return cur.fetchall()


def obter(cur, sid: int, travar: bool = False) -> Optional[dict]:
    cur.execute(f"SELECT {_CAMPOS}, {_HISTORICO} AS tem_historico FROM setores st "
                f"WHERE st.id = %s{' FOR UPDATE' if travar else ''}", (sid,))
    return cur.fetchone()


def obter_png(cur, sid: int) -> Optional[bytes]:
    cur.execute("SELECT icone_png FROM setores WHERE id = %s", (sid,))
    r = cur.fetchone()
    return bytes(r["icone_png"]) if r and r["icone_png"] else None


def prefixo_em_uso(cur, prefixo: str, ignorar_id: Optional[int] = None) -> bool:
    cur.execute("SELECT 1 AS ok FROM setores WHERE prefixo = %s AND id <> %s",
                (prefixo, ignorar_id or 0))
    return cur.fetchone() is not None


def nome_em_uso(cur, nome: str, ignorar_id: Optional[int] = None) -> bool:
    cur.execute("SELECT 1 AS ok FROM setores WHERE nome = %s AND id <> %s",
                (nome, ignorar_id or 0))
    return cur.fetchone() is not None


def outros_ativos(cur, sid: int) -> int:
    cur.execute("SELECT COUNT(*) AS qtd FROM setores WHERE ativo = 1 AND id <> %s FOR UPDATE",
                (sid,))
    return int(cur.fetchone()["qtd"])


def inserir(cur, d: dict) -> int:
    cur.execute(
        "INSERT INTO setores (nome, descricao, prefixo, icone, cor, ordem) "
        "SELECT %s, %s, %s, %s, %s, LEAST(COALESCE(MAX(ordem), 0) + 1, 255) FROM setores",
        (d["nome"], d["descricao"], d["prefixo"], d["icone"], d["cor"]))
    sid = int(cur.lastrowid)
    cur.execute("INSERT IGNORE INTO controle_fila (setor_id) VALUES (%s)", (sid,))
    return sid


def atualizar(cur, sid: int, d: dict) -> None:
    cur.execute("UPDATE setores SET nome = %s, descricao = %s, prefixo = %s, icone = %s, "
                "cor = %s WHERE id = %s",
                (d["nome"], d["descricao"], d["prefixo"], d["icone"], d["cor"], sid))


def gravar_icone(cur, sid: int, png: Optional[bytes], hash_hex: Optional[str]) -> None:
    """png e hash são gravados juntos (ambos NULL quando não há ícone)."""
    cur.execute("UPDATE setores SET icone_png = %s, icone_hash = %s WHERE id = %s",
                (png if png else None, hash_hex if png else None, sid))


def icones_para_regerar(cur) -> list[dict]:
    cur.execute("SELECT id, icone, icone_png FROM setores ORDER BY id FOR UPDATE")
    return cur.fetchall()


def definir_ativo(cur, sid: int, ativo: bool) -> None:
    cur.execute("UPDATE setores SET ativo = %s WHERE id = %s", (int(ativo), sid))


def ids_ordenados(cur) -> list[int]:
    cur.execute("SELECT id FROM setores ORDER BY ordem, nome, id FOR UPDATE")
    return [int(r["id"]) for r in cur.fetchall()]


def gravar_ordem(cur, ids: Sequence[int]) -> None:
    cur.executemany("UPDATE setores SET ordem = %s WHERE id = %s",
                    [(min(i, 255), sid) for i, sid in enumerate(ids, 1)])


def excluir(cur, sid: int) -> int:
    cur.execute("DELETE FROM setores WHERE id = %s", (sid,))
    return cur.rowcount
