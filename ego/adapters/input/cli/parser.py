"""CLI Adapter・入力正規化部(A-1, A-5): Input Port の Phase 1.0 実装。

argv(CLI 固有の型)をここで InputMessage(ドメイン型)へ変換する。
argv をそのまま Core へ渡してはならない(規約2)。
"""

from __future__ import annotations

from ego.core.domain import InputMessage
from ego.core.errors import InputError
from ego.ports.input_port import InputPort

_USAGE = (
    "使い方: ego record <自由記述> [--revises <fact_id>] / ego approve <id> / "
    "ego reject <id> / ego ask <キーワード> / ego history <fact_id>"
)

_KNOWN_COMMANDS = {"record", "approve", "reject", "ask", "history"}


def normalize(argv: list[str]) -> InputMessage:
    """argv を正規化済み InputMessage に変換する。未知コマンドは E_INPUT。"""
    if not argv:
        raise InputError("コマンドが指定されていません", hint=_USAGE)

    command = argv[0]
    if command not in _KNOWN_COMMANDS:
        raise InputError(f"未知のコマンドです: {command}", hint=_USAGE)

    rest = argv[1:]
    options: dict = {}

    if command == "record":
        text_parts: list[str] = []
        i = 0
        while i < len(rest):
            if rest[i] == "--revises":
                if i + 1 >= len(rest):
                    raise InputError("--revises に fact_id が指定されていません", hint=_USAGE)
                options["revises"] = rest[i + 1]
                i += 2
            else:
                text_parts.append(rest[i])
                i += 1
        return InputMessage(command="record", text=" ".join(text_parts), options=options)

    if command in ("approve", "reject", "history"):
        if len(rest) != 1:
            raise InputError(f"{command} には ID を 1 つ指定してください", hint=_USAGE)
        return InputMessage(command=command, text=rest[0])

    # ask
    query = " ".join(rest)
    return InputMessage(command="ask", text=query)


class CliInputAdapter(InputPort):
    """Input Port 適合の CLI アダプタ。"""

    def __init__(self, argv: list[str]):
        self._argv = argv

    def receive(self) -> InputMessage:
        return normalize(self._argv)
