"""Formatação pt-BR de tamanhos e tempos (telas e diagnósticos)."""
from typing import Optional

_MB = 1024 * 1024


def mb(n_bytes: int) -> str:
    return f"{(n_bytes or 0) / _MB:.1f} MB".replace(".", ",")


def espaco(livre_mb: Optional[int]) -> str:
    if livre_mb is None:
        return "espaço livre desconhecido"
    if livre_mb >= 1024:
        return f"{livre_mb / 1024:.1f} GB livres".replace(".", ",")
    return f"{livre_mb} MB livres"


def idade(seg: int) -> str:
    seg = max(0, int(seg or 0))
    if seg < 10:
        return "agora"
    if seg < 60:
        return f"há {seg} s"
    if seg < 3600:
        return f"há {seg // 60} min"
    if seg < 86400:
        return f"há {seg // 3600} h"
    return f"há {seg // 86400} d"
