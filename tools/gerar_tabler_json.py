"""
Gera assets/tabler/tabler-icons.json (nome -> código hex) a partir do tabler-icons.css.
Uso (na pasta guiche):  python tools/gerar_tabler_json.py
"""
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / "assets" / "tabler"
_RE = re.compile(r'\.ti-([a-z0-9-]+):before\s*\{\s*content:\s*"\\([0-9a-fA-F]+)"')


def main() -> int:
    css = BASE / "tabler-icons.css"
    if not css.exists():
        print(f"Arquivo não encontrado: {css}")
        return 1
    icones = {n: c.lower() for n, c in _RE.findall(css.read_text(encoding="utf-8"))}
    if not icones:
        print("Nenhum ícone encontrado no CSS.")
        return 1
    destino = BASE / "tabler-icons.json"
    destino.write_text(json.dumps(dict(sorted(icones.items())), separators=(",", ":")),
                       encoding="utf-8")
    print(f"{len(icones)} ícones gravados em {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
