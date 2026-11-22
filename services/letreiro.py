"""
Avisos do letreiro (rodapé do Painel): cadastro restrito ao perfil gestor.

- Toda operação revalida o perfil no banco (não confia só na sessão local).
- Auditoria na MESMA transação (ação 'letreiro'; detalhe só com ids).
- 'vigente' = ativo e dentro do período (regra de exibição do Painel).
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from database import db
from services import auditoria

TEXTO_MAX = 200
FORMATO = "dd/mm/aaaa hh:mm"
_FMT = "%d/%m/%Y %H:%M"


class ErroLetreiro(Exception):
    """Mensagem segura para a tela."""


@dataclass
class Aviso:
    id: Optional[int]
    texto: str
    setor_id: Optional[int] = None
    ativo: bool = True
    inicio_em: Optional[datetime] = None
    fim_em: Optional[datetime] = None


# ---- Utilitários (sem banco) ----------------------------------------------
def ler_data(txt: str) -> Optional[datetime]:
    txt = (txt or "").strip()
    if not txt:
        return None
    try:
        return datetime.strptime(txt, _FMT)
    except ValueError as exc:
        raise ErroLetreiro(f"Data inválida. Use {FORMATO}.") from exc


def formatar_data(d: Optional[datetime]) -> str:
    return d.strftime(_FMT) if d else ""


def validar(a: Aviso) -> None:
    a.texto = " ".join((a.texto or "").split())
    if not a.texto:
        raise ErroLetreiro("Informe o texto da mensagem.")
    if len(a.texto) > TEXTO_MAX:
        raise ErroLetreiro(f"Máximo de {TEXTO_MAX} caracteres.")
    if a.inicio_em and a.fim_em and a.fim_em <= a.inicio_em:
        raise ErroLetreiro("O fim deve ser posterior ao início.")


# ---- Banco ----------------------------------------------------------------
def _exigir_gestor(cur, usuario_id: int) -> None:
    cur.execute("SELECT perfil, ativo FROM usuarios WHERE id = %s", (usuario_id,))
    u = cur.fetchone()
    if not u or not u["ativo"] or u["perfil"] != "gestor":
        raise ErroLetreiro("Acesso restrito ao gestor.")


def listar(usuario_id: int) -> list[dict]:
    with db.cursor() as cur:
        _exigir_gestor(cur, usuario_id)
        cur.execute(
            "SELECT a.id, a.texto, a.setor_id, s.nome AS setor, a.ordem, a.ativo, "
            "       a.inicio_em, a.fim_em, "
            "       (a.ativo = 1 AND (a.inicio_em IS NULL OR a.inicio_em <= NOW()) "
            "        AND (a.fim_em IS NULL OR a.fim_em > NOW())) AS vigente "
            "FROM avisos_letreiro a LEFT JOIN setores s ON s.id = a.setor_id "
            "ORDER BY a.ordem, a.id")
        return cur.fetchall()


def listar_setores() -> list[dict]:
    return db.fetch_all("SELECT id, nome FROM setores WHERE ativo = 1 ORDER BY ordem, nome")


def salvar(usuario_id: int, login: str, a: Aviso) -> int:
    validar(a)
    with db.cursor() as cur:
        _exigir_gestor(cur, usuario_id)
        if a.id is None:
            cur.execute("SELECT COALESCE(MAX(ordem), 0) + 1 AS prox FROM avisos_letreiro")
            ordem = int(cur.fetchone()["prox"])
            cur.execute(
                "INSERT INTO avisos_letreiro "
                "(texto, setor_id, ordem, ativo, inicio_em, fim_em, criado_por) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (a.texto, a.setor_id, ordem, int(a.ativo), a.inicio_em, a.fim_em, login[:32]))
            aid, op = cur.lastrowid, "criar"
        else:
            cur.execute(
                "UPDATE avisos_letreiro SET texto = %s, setor_id = %s, ativo = %s, "
                "inicio_em = %s, fim_em = %s WHERE id = %s",
                (a.texto, a.setor_id, int(a.ativo), a.inicio_em, a.fim_em, a.id))
            if cur.rowcount == 0:
                raise ErroLetreiro("Mensagem não encontrada (excluída por outro gestor?).")
            aid, op = a.id, "editar"
        auditoria.registrar(cur, "letreiro", usuario_id, detalhe=f"{op}:{aid}")
    return aid


def alternar_ativo(usuario_id: int, aviso_id: int) -> None:
    with db.cursor() as cur:
        _exigir_gestor(cur, usuario_id)
        cur.execute("UPDATE avisos_letreiro SET ativo = 1 - ativo WHERE id = %s", (aviso_id,))
        if cur.rowcount == 0:
            raise ErroLetreiro("Mensagem não encontrada.")
        auditoria.registrar(cur, "letreiro", usuario_id, detalhe=f"alternar:{aviso_id}")


def excluir(usuario_id: int, aviso_id: int) -> None:
    with db.cursor() as cur:
        _exigir_gestor(cur, usuario_id)
        cur.execute("DELETE FROM avisos_letreiro WHERE id = %s", (aviso_id,))
        if cur.rowcount == 0:
            raise ErroLetreiro("Mensagem não encontrada.")
        auditoria.registrar(cur, "letreiro", usuario_id, detalhe=f"excluir:{aviso_id}")


def mover(usuario_id: int, aviso_id: int, delta: int) -> None:
    """Troca de posição com o vizinho e renumera 1..n (sob lock)."""
    with db.cursor() as cur:
        _exigir_gestor(cur, usuario_id)
        cur.execute("SELECT id, ordem FROM avisos_letreiro ORDER BY ordem, id FOR UPDATE")
        rows = cur.fetchall()
        ids = [int(r["id"]) for r in rows]
        if aviso_id not in ids:
            raise ErroLetreiro("Mensagem não encontrada.")
        i = ids.index(aviso_id)
        j = i + delta
        if not 0 <= j < len(ids):
            return
        ids[i], ids[j] = ids[j], ids[i]
        atuais = {int(r["id"]): int(r["ordem"]) for r in rows}
        for pos, aid in enumerate(ids, 1):
            if atuais[aid] != pos:
                cur.execute("UPDATE avisos_letreiro SET ordem = %s WHERE id = %s", (pos, aid))
        auditoria.registrar(cur, "letreiro", usuario_id, detalhe=f"mover:{aviso_id}:{delta:+d}")
