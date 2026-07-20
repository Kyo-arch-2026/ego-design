"""アーキテクチャ規約の固定テスト(規約1: 依存の向きはアダプタ→ポート→Core)。

Core(ego/core/)とポート(ego/ports/)がアダプタ・構成ルートを import して
いないことをソースから機械的に検証する。規約違反はここで即検出される。
"""

import re
from pathlib import Path

import ego

_PACKAGE_ROOT = Path(ego.__file__).parent
_FORBIDDEN = re.compile(r"^\s*(?:from|import)\s+ego\.(adapters|bootstrap)\b", re.MULTILINE)


def _violations(subdir: str) -> list[str]:
    found = []
    for path in (_PACKAGE_ROOT / subdir).rglob("*.py"):
        if _FORBIDDEN.search(path.read_text(encoding="utf-8")):
            found.append(str(path.relative_to(_PACKAGE_ROOT)))
    return found


def test_core_does_not_import_adapters_or_bootstrap():
    assert _violations("core") == []


def test_ports_do_not_import_adapters_or_bootstrap():
    assert _violations("ports") == []
