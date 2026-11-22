"""
SQL das mídias do slideshow (Guichê). Funções com `cur` rodam na transação
de quem chama; as demais abrem a própria.
"""
from typing import Optional

from database import db

_FILTRO = "tipo IN ('imagem','video') AND sha256 IS NOT NULL"
_CAMPOS = ("id, tipo, titulo, arquivo_nome, extensao, sha256, tamanho_bytes, largura, altura, "
           "duracao_video_seg, duracao_seg, mudo, ajuste, ordem, ativo, valido_de, valido_ate")


def listar() -> list[dict]:
    return db.fetch_all(
        f"SELECT {_CAMPOS}, "
        "(valido_de IS NOT NULL AND valido_de > CURDATE()) AS agendada, "
        "(valido_ate IS NOT NULL AND valido_ate < CURDATE()) AS vencida "
        f"FROM midias WHERE {_FILTRO} ORDER BY ordem, id")


def ativas() -> list[tuple[str, str]]:
    """(sha256, extensao) das mídias ativas (o painel exige todas no cache)."""
    linhas = db.fetch_all(f"SELECT sha256, extensao FROM midias WHERE ativo = 1 AND {_FILTRO}")
    return [(r["sha256"].lower(), r["extensao"].lower()) for r in linhas]


def versao() -> int:
    row = db.fetch_one("SELECT valor FROM config WHERE chave = 'slideshow.versao'")
    try:
        return int((row or {}).get("valor") or 0)
    except ValueError:
        return 0


def padroes() -> tuple[int, bool]:
    """(duração padrão, mudo padrão) da tabela config."""
    linhas = db.fetch_all("SELECT chave, valor FROM config WHERE chave IN "
                          "('slideshow.duracao_padrao', 'slideshow.mudo_padrao')")
    d = {r["chave"]: r["valor"] for r in linhas}
    try:
        dur = int(d.get("slideshow.duracao_padrao") or 10)
    except ValueError:
        dur = 10
    return max(1, min(600, dur)), str(d.get("slideshow.mudo_padrao", "1")).strip() != "0"


def contar_ativas(cur, travar: bool = False) -> int:
    cur.execute(f"SELECT COUNT(*) AS n FROM midias WHERE ativo = 1 AND {_FILTRO}"
                + (" FOR UPDATE" if travar else ""))
    return int(cur.fetchone()["n"])


def sha_cadastrado(cur, sha: str) -> bool:
    cur.execute("SELECT 1 AS ok FROM midias WHERE sha256 = %s LIMIT 1", (sha,))
    return cur.fetchone() is not None


def obter(cur, mid: int, travar: bool = False) -> Optional[dict]:
    cur.execute(f"SELECT {_CAMPOS} FROM midias WHERE id = %s AND {_FILTRO}"
                + (" FOR UPDATE" if travar else ""), (mid,))
    return cur.fetchone()


def inserir(cur, arq, d: dict, usuario_id: int) -> int:
    cur.execute(
        "INSERT INTO midias (tipo, titulo, arquivo_nome, extensao, sha256, tamanho_bytes, "
        "largura, altura, duracao_video_seg, caminho, duracao_seg, mudo, ajuste, ordem, ativo, "
        "valido_de, valido_ate, criado_por) "
        "SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
        "COALESCE(MAX(ordem), 0) + 1, %s, %s, %s, %s FROM midias",
        (arq.tipo, d["titulo"], arq.nome_original[:255], arq.extensao, arq.sha256, arq.tamanho,
         arq.largura, arq.altura, arq.duracao_video, arq.nome_cache, d["duracao_seg"],
         int(d["mudo"]), d["ajuste"], int(d["ativo"]), d["valido_de"], d["valido_ate"],
         usuario_id))
    return int(cur.lastrowid)


def atualizar(cur, mid: int, d: dict) -> None:
    cur.execute(
        "UPDATE midias SET titulo = %s, duracao_seg = %s, mudo = %s, ajuste = %s, ativo = %s, "
        "valido_de = %s, valido_ate = %s WHERE id = %s",
        (d["titulo"], d["duracao_seg"], int(d["mudo"]), d["ajuste"], int(d["ativo"]),
         d["valido_de"], d["valido_ate"], mid))


def excluir(cur, mid: int) -> None:
    cur.execute("DELETE FROM midias WHERE id = %s", (mid,))


def ids_ordenados(cur) -> list[int]:
    cur.execute(f"SELECT id FROM midias WHERE {_FILTRO} ORDER BY ordem, id FOR UPDATE")
    return [int(r["id"]) for r in cur.fetchall()]


def definir_ordem(cur, ids: list[int]) -> None:
    for pos, mid in enumerate(ids, 1):
        cur.execute("UPDATE midias SET ordem = %s WHERE id = %s", (pos, mid))


def incrementar_versao(cur) -> None:
    cur.execute(
        "INSERT INTO config (chave, valor) VALUES ('slideshow.versao', '1') "
        "ON DUPLICATE KEY UPDATE valor = "
        "CAST(IF(valor REGEXP '^[0-9]+$', valor, '0') AS UNSIGNED) + 1")
