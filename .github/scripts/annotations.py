"""CI : échecs rendus en annotations GitHub (lisibles par l'API des check-runs, même quand
les journaux complets ne sont pas accessibles).

    python .github/scripts/annotations.py junit backend/pytest.xml
    python .github/scripts/annotations.py fichiers <journal> [<journal>…]
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_ANNOTATIONS = 9  # GitHub en garde 10 par étape
MAX_CHARS = 6000


def escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def emit(title: str, message: str) -> None:
    print(f"::error title={escape(title)[:200]}::{escape(message[-MAX_CHARS:])}", flush=True)


def junit(path: Path) -> None:
    failures: list[tuple[str, str]] = []
    for case in ET.parse(path).iter("testcase"):
        for problem in [*case.iter("failure"), *case.iter("error")]:
            name = f"{case.get('classname', '')}::{case.get('name', '')}"
            detail = f"{problem.get('message', '')}\n{problem.text or ''}"
            failures.append((name, detail))
    for name, detail in failures[:MAX_ANNOTATIONS]:
        emit(name, detail)
    if len(failures) > MAX_ANNOTATIONS:
        emit("autres échecs", "\n".join(name for name, _ in failures[MAX_ANNOTATIONS:]))


def files(paths: list[str]) -> None:
    for name in paths[:MAX_ANNOTATIONS]:
        path = Path(name)
        if path.is_file():
            data = path.read_bytes()  # Tee-Object de PowerShell 5.1 écrit en UTF-16
            encoding = "utf-16" if data[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
            emit(path.name, data.decode(encoding, errors="replace"))
        else:
            emit(path.name, f"absent : {path}")


if __name__ == "__main__":
    if sys.argv[1] == "junit":
        junit(Path(sys.argv[2]))
    else:
        files(sys.argv[2:])
