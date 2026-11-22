"""SQL dos usuários (sempre dentro do cursor/transação recebido)."""
from typing import Optional, Sequence

_EM_SESSAO = ("EXISTS (SELECT 1 FROM sessoes_guiche sg "
              "WHERE sg.usuario_id = u.id AND sg.fim_em IS NULL)")
_HISTORICO = ("EXISTS (SELECT 1 FROM senhas s WHERE s.usuario_id = u.id "
              "AND s.status IN ('em_atendimento','atendido','ausente'))")
_SETORES = ("(SELECT GROUP_CONCAT(us.setor_id ORDER BY us.setor_id) "
            "FROM usuario_setores us JOIN setores st ON st.id = us.setor_id AND st.ativo = 1 "
            "WHERE us.usuario_id = u.id)")
_CAMPOS = (f"u.id, u.login, u.nome, u.perfil, u.ativo, "
           f"(u.bloqueado_ate IS NOT NULL AND u.bloqueado_ate > NOW()) AS bloqueado, "
           f"u.ultimo_login_em, {_EM_SESSAO} AS em_sessao, {_SETORES} AS setores")


def _setores(row: Optional[dict]) -> Optional[dict]:
    if row is not None:
        bruto = row.get("setores")
        row["setores"] = [int(x) for x in str(bruto).split(",")] if bruto else []
    return row


def listar(cur) -> list[dict]:
    cur.execute(f"SELECT {_CAMPOS} FROM usuarios u ORDER BY u.ativo DESC, u.nome")
    return [_setores(r) for r in cur.fetchall()]


def obter(cur, uid: int, travar: bool = False) -> Optional[dict]:
    cur.execute(f"SELECT {_CAMPOS}, {_HISTORICO} AS tem_historico FROM usuarios u "
                f"WHERE u.id = %s{' FOR UPDATE' if travar else ''}", (uid,))
    return _setores(cur.fetchone())


def login_em_uso(cur, login: str, ignorar_id: Optional[int] = None) -> bool:
    cur.execute("SELECT 1 AS ok FROM usuarios WHERE login = %s AND id <> %s",
                (login, ignorar_id or 0))
    return cur.fetchone() is not None


def outros_gestores_ativos(cur, uid: int) -> int:
    cur.execute("SELECT COUNT(*) AS qtd FROM usuarios "
                "WHERE perfil = 'gestor' AND ativo = 1 AND id <> %s FOR UPDATE", (uid,))
    return int(cur.fetchone()["qtd"])


def inserir(cur, login: str, nome: str, perfil: str, senha_hash: str) -> int:
    cur.execute("INSERT INTO usuarios (login, nome, perfil, senha_hash, trocar_senha) "
                "VALUES (%s, %s, %s, %s, 0)", (login, nome, perfil, senha_hash))
    return int(cur.lastrowid)


def atualizar(cur, uid: int, login: str, nome: str, perfil: str) -> None:
    cur.execute("UPDATE usuarios SET login = %s, nome = %s, perfil = %s WHERE id = %s",
                (login, nome, perfil, uid))


def definir_senha(cur, uid: int, senha_hash: str) -> None:
    cur.execute("UPDATE usuarios SET senha_hash = %s, trocar_senha = 0, tentativas_falhas = 0, "
                "bloqueado_ate = NULL WHERE id = %s", (senha_hash, uid))


def desbloquear(cur, uid: int) -> None:
    cur.execute("UPDATE usuarios SET tentativas_falhas = 0, bloqueado_ate = NULL "
                "WHERE id = %s", (uid,))


def definir_ativo(cur, uid: int, ativo: bool) -> None:
    cur.execute("UPDATE usuarios SET ativo = %s WHERE id = %s", (int(ativo), uid))


def gravar_setores(cur, uid: int, setor_ids: Sequence[int]) -> None:
    """
    Substitui os vínculos com setores ATIVOS (os do formulário).
    Vínculos com setores inativos são preservados: o usuário segue esvaziando a
    fila deles e o vínculo volta a valer se o setor for reativado.
    """
    cur.execute("DELETE us FROM usuario_setores us JOIN setores st ON st.id = us.setor_id "
                "WHERE us.usuario_id = %s AND st.ativo = 1", (uid,))
    ids = sorted({int(i) for i in setor_ids or ()})
    if ids:
        m = ", ".join(["%s"] * len(ids))
        cur.execute(f"INSERT IGNORE INTO usuario_setores (usuario_id, setor_id) "
                    f"SELECT %s, id FROM setores WHERE ativo = 1 AND id IN ({m})", (uid, *ids))


def excluir(cur, uid: int) -> int:
    cur.execute("DELETE FROM usuarios WHERE id = %s", (uid,))
    return cur.rowcount
