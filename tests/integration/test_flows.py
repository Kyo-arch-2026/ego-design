"""結合テスト仕様書 5(IT-01〜11)。

- LLM: 決定的フェイクアダプタ(LLM Port 適合・固定応答・エラー注入可能)
- ストレージ: 実 SQLite アダプタ + テスト用 DB ファイル(ケースごとに初期化)
- 駆動: Input Port を直接駆動する(CLI 表示層は通さない)

DB の中身の検証はテストコードから直接 SQL で行う(検証はテストの責務であり、
Core は一切 SQL を触っていない)。
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta

import pytest

from ego.adapters.input.cli import CliInputAdapter
from ego.bootstrap import App, AppConfig, build_app
from ego.core.domain import (
    AuditEvent,
    Fact,
    InputMessage,
    Revision,
    utc_now,
)
from ego.core.errors import LlmError, StoreError
from tests.conftest import FakeLLM


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "ego_test.db")


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def app(db_path, fake_llm) -> App:
    """規約5: アダプタの注入は構成(AppConfig)経由で一箇所から行う。"""
    return build_app(config=AppConfig(db_path=db_path), llm=fake_llm)


def drive(app: App, argv: list[str]):
    """CLI 表示層を通さず、Input Port(正規化済み InputMessage)で Core を駆動する。"""
    message: InputMessage = CliInputAdapter(argv).receive()
    if message.command == "record":
        return app.structurer.record(
            message.text, revises_fact_id=message.options.get("revises")
        )
    if message.command == "approve":
        return app.approval.approve(message.text)
    if message.command == "reject":
        return app.approval.reject(message.text)
    if message.command == "ask":
        return app.session.ask(message.text)
    if message.command == "history":
        return app.sot.history(message.text)
    raise AssertionError(message.command)


def query(db_path: str, sql: str, params: tuple = ()) -> list[tuple]:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def count(db_path: str, table: str, where: str = "1=1", params: tuple = ()) -> int:
    return query(db_path, f"SELECT COUNT(*) FROM {table} WHERE {where}", params)[0][0]


def test_it_01_record_flow(app, db_path):
    """IT-01(T-1・UC-1): raw_text 1 件・candidate 1 件(原文と紐づく)・正本 0 件。"""
    fact = drive(app, ["record", "会社の方針について判断したい"])

    assert count(db_path, "raw_text") == 1
    assert count(db_path, "fact_revisions", "status='candidate'") == 1
    assert count(db_path, "canonical_facts") == 0

    rows = query(
        db_path,
        "SELECT raw_text_id FROM fact_revisions WHERE fact_id=?",
        (fact.id,),
    )
    raw_ids = query(db_path, "SELECT id FROM raw_text")
    assert rows[0][0] == raw_ids[0][0]  # candidate が原文を指す


def test_it_02_approve_flow(app, db_path):
    """IT-02(T-2・UC-2): 正本 active 1 件。audit_log に approve(actor=human)。"""
    fact = drive(app, ["record", "承認する判断"])
    drive(app, ["approve", fact.id])

    assert count(db_path, "canonical_facts", "status='active'") == 1
    approvals = query(
        db_path,
        "SELECT actor FROM audit_log WHERE event_type='approve' AND target_id=?",
        (fact.id,),
    )
    assert approvals == [("human",)]


def test_it_03_reject_flow(app, db_path):
    """IT-03(T-4): 正本化されず rejected で記録。audit_log に reject。"""
    fact = drive(app, ["record", "却下する判断"])
    drive(app, ["reject", fact.id])

    assert count(db_path, "canonical_facts") == 0
    assert count(db_path, "fact_revisions", "fact_id=? AND status='rejected'", (fact.id,)) == 1
    assert count(db_path, "audit_log", "event_type='reject' AND target_id=?", (fact.id,)) == 1


def test_it_04_supersede_flow(app, db_path):
    """IT-04(T-3・C-2-2): 旧 active → superseded 退避、新正本 active。"""
    old = drive(app, ["record", "旧しい方針"])
    drive(app, ["approve", old.id])

    new = drive(app, ["record", "新しい方針", "--revises", old.id])
    drive(app, ["approve", new.id])

    active_ids = {f.id for f in app.store.find_active()}
    assert active_ids == {new.id}
    assert old.id not in active_ids
    assert (
        count(db_path, "fact_revisions", "fact_id=? AND status='superseded'", (old.id,)) == 1
    )


def test_it_05_reference_flow(app, db_path):
    """IT-05(T-5・UC-3・E-2): 参照結果は今有効な active のみ。"""
    active = drive(app, ["record", "有効な判断 目標キーワード"])
    drive(app, ["approve", active.id])

    superseded = drive(app, ["record", "置換前の判断 目標キーワード"])
    drive(app, ["approve", superseded.id])
    replacement = drive(app, ["record", "置換後の判断 目標キーワード", "--revises", superseded.id])
    drive(app, ["approve", replacement.id])

    rejected = drive(app, ["record", "却下される判断 目標キーワード"])
    drive(app, ["reject", rejected.id])

    expired = drive(app, ["record", "期限切れの判断 目標キーワード"])
    drive(app, ["approve", expired.id])
    past = (utc_now() - timedelta(days=1)).isoformat()
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute("UPDATE canonical_facts SET valid_until=? WHERE id=?", (past, expired.id))
    conn.close()

    results = drive(app, ["ask", "目標キーワード"])
    ids = {f.id for f in results}
    assert ids == {active.id, replacement.id}


def test_it_06_history_flow(app):
    """IT-06(UC-4): candidate→active(→superseded)の改訂が時系列で取得できる。"""
    old = drive(app, ["record", "履歴を追う判断"])
    drive(app, ["approve", old.id])
    new = drive(app, ["record", "更新後の判断", "--revises", old.id])
    drive(app, ["approve", new.id])

    old_revisions, old_current = drive(app, ["history", old.id])
    assert [r.status for r in old_revisions] == ["candidate", "superseded"]
    assert old_current is None  # もう正本ではない

    new_revisions, new_current = drive(app, ["history", new.id])
    assert [r.status for r in new_revisions] == ["candidate"]
    assert new_current is not None and new_current.status == "active"


def test_it_07_audit_consistency(app, db_path):
    """IT-07(T-7・F-1): 一連操作が発生順に欠落なく audit_log に記録される。"""
    a = drive(app, ["record", "承認される判断"])
    drive(app, ["approve", a.id])
    b = drive(app, ["record", "却下される判断"])
    drive(app, ["reject", b.id])
    c = drive(app, ["record", "置換する判断", "--revises", a.id])
    drive(app, ["approve", c.id])
    drive(app, ["ask", "判断"])

    rows = query(db_path, "SELECT event_type, target_id FROM audit_log ORDER BY rowid")
    assert rows == [
        ("register", a.id),
        ("approve", a.id),
        ("register", b.id),
        ("reject", b.id),
        ("register", c.id),
        ("transition", a.id),  # active → superseded
        ("approve", c.id),
    ]


def test_it_08_di_swap(tmp_path, fake_llm):
    """IT-08(規約4・5): ストアアダプタを差し替えても Core 無改修で成立。

    (a) 設定(AppConfig)で SQLite アダプタの実体(DB ファイル)を切り替え
    (b) Store Port の別実装(インメモリの MemoryStore)へ丸ごと差し替え
    のいずれでも、同一の Core コードで記録→承認→参照が成立することを検証。
    """
    from tests.conftest import MemoryStore

    stores = {
        "sqlite_a": None,  # 設定経由で構築(build_store が担う)
        "sqlite_b": None,
        "memory": MemoryStore(),  # Store Port の別実装を直接注入
    }
    for name, injected in stores.items():
        config = AppConfig(db_path=str(tmp_path / f"{name}.db"))
        app = build_app(config=config, store=injected, llm=FakeLLM())
        fact = drive(app, ["record", "差し替えテスト"])
        drive(app, ["approve", fact.id])
        assert {f.id for f in app.store.find_active()} == {fact.id}

    # SQLite の 2 DB は独立している(注入されたアダプタが異なる実体である証拠)
    assert count(str(tmp_path / "sqlite_a.db"), "canonical_facts") == 1
    assert count(str(tmp_path / "sqlite_b.db"), "canonical_facts") == 1
    # MemoryStore 側にも同一フローの結果が残っている(別実装でも Core 無改修)
    assert len(stores["memory"].canonical) == 1


def test_it_09_llm_failure_propagation(db_path):
    """IT-09: E_LLM が抽象化されて伝播。原文は保存済み、candidate 未生成。"""
    failing = FakeLLM(error=LlmError("注入した LLM 障害"))
    app = build_app(config=AppConfig(db_path=db_path), llm=failing)

    with pytest.raises(LlmError) as excinfo:
        drive(app, ["record", "LLM が落ちる記録"])

    assert excinfo.value.code == "E_LLM"
    assert count(db_path, "raw_text") == 1
    assert count(db_path, "fact_revisions") == 0


def test_it_10_store_failure_propagation(app, db_path, fake_llm):
    """IT-10: 書き込み失敗で E_STORE が伝播し、中途半端な状態が残らない。"""
    fact = drive(app, ["record", "承認直前の判断"])
    before_revisions = count(db_path, "fact_revisions")

    from ego.adapters.store.sqlite import SQLiteStoreAdapter

    readonly_store = SQLiteStoreAdapter(db_path, read_only=True)
    readonly_app = build_app(
        config=AppConfig(db_path=db_path), store=readonly_store, llm=fake_llm
    )

    with pytest.raises(StoreError) as excinfo:
        drive(readonly_app, ["approve", fact.id])

    assert excinfo.value.code == "E_STORE"
    assert count(db_path, "canonical_facts") == 0          # 正本は作られていない
    assert count(db_path, "fact_revisions") == before_revisions  # 履歴も不変


def test_it_11_port_boundary_domain_types(app):
    """IT-11(規約2・3): ポート往復は全てドメイン型。技術固有型が Core に漏れない。"""
    fact = drive(app, ["record", "型検査対象の判断"])

    candidates = app.store.find_candidates()
    assert all(isinstance(r, Revision) for r in candidates)

    promoted = app.store.promote_to_active(fact.id)
    assert isinstance(promoted, Fact)

    actives = app.store.find_active()
    assert all(isinstance(f, Fact) for f in actives)

    revisions = app.store.get_revisions(fact.id)
    assert all(isinstance(r, Revision) for r in revisions)

    events = app.store.get_audit_events()
    assert all(isinstance(e, AuditEvent) for e in events)

    assert not any(isinstance(x, sqlite3.Row) for x in candidates + actives + revisions + events)
