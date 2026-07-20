"""CLI エントリポイント(表示層)。

入力正規化(parser)で得た InputMessage を Core に渡し、結果を表示する。
エラーは一貫形式(詳細設計書 6.2): [E_XXX] メッセージ。
"""

from __future__ import annotations

import sys

from ego.bootstrap import App, AppConfig, build_app, build_input
from ego.core.domain import Fact, InputMessage
from ego.core.errors import EgoError


def _first_line(text: str) -> str:
    return text.splitlines()[0] if text else ""


def _print_fact(fact: Fact) -> None:
    print(f"ID: {fact.id}")
    for line in fact.content.splitlines():
        print(f"  {line}")


def _dispatch(app: App, message: InputMessage) -> None:
    if message.command == "record":
        fact = app.structurer.record(
            message.text, revises_fact_id=message.options.get("revises")
        )
        print("candidate を登録しました(まだ正本ではありません)。")
        _print_fact(fact)
        if fact.revises_fact_id:
            print(f"置換対象: {fact.revises_fact_id}(承認時に superseded へ退避)")
        print(f"承認: ego approve {fact.id} / 却下: ego reject {fact.id}")
        return

    if message.command == "approve":
        fact = app.approval.approve(message.text)
        print("承認しました。正本(active)になりました。")
        _print_fact(fact)
        return

    if message.command == "reject":
        app.approval.reject(message.text)
        print(f"却下しました: {message.text}(正本化されません。履歴には残ります)")
        return

    if message.command == "ask":
        facts = app.session.ask(message.text)
        if not facts:
            print("該当する正本はありません。")
            return
        print(f"今有効な正本 {len(facts)} 件:")
        for fact in facts:
            _print_fact(fact)
        print("参照した正本ID: " + ", ".join(f.id for f in facts))
        return

    if message.command == "history":
        revisions, current = app.sot.history(message.text)
        print(f"カード {message.text} の履歴:")
        for rev in revisions:
            stamp = rev.created_at.strftime("%Y-%m-%d %H:%M:%S") if rev.created_at else "-"
            line = f"  {stamp}  {rev.status:<10}  {_first_line(rev.content)}"
            if rev.reason:
                line += f"  ({rev.reason})"
            print(line)
        if current is not None:
            print(f"現在の状態: active({_first_line(current.content)})")
        else:
            print(f"現在の状態: {revisions[-1].status}(正本ではありません)")
        return

    raise AssertionError(f"unreachable: {message.command}")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        config = AppConfig.from_env()
        message = build_input(config, argv).receive()  # 注入は構成ルート経由(規約5)
        app = build_app(config)
        _dispatch(app, message)
        return 0
    except EgoError as exc:
        print(exc.display(), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
