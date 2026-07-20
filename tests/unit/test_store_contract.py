"""単体テスト仕様書 5.4 Store Port 契約テスト(UT-SP-01〜07 = T-8)。

アダプタ非依存の契約テストとして書く。store フィクスチャの params に
アダプタを追加するだけで、Phase 1.5 の PostgreSQL アダプタにも
同一テストをそのまま適用できる(詳細設計書 9.1)。
"""

from datetime import timedelta

import pytest

from ego.core.domain import (
    ACTIVE,
    CANDIDATE,
    SUPERSEDED,
    AuditEvent,
    Fact,
    RawText,
    new_id,
    utc_now,
)
from ego.core.errors import StoreError


@pytest.fixture(params=["sqlite"])
def store(request):
    """契約テスト対象のアダプタ。PostgreSQL アダプタ追加時は params に足す。"""
    if request.param == "sqlite":
        from ego.adapters.store.sqlite import SQLiteStoreAdapter

        adapter = SQLiteStoreAdapter(":memory:")
        yield adapter
        adapter.close()
    else:  # pragma: no cover
        raise ValueError(request.param)


def make_candidate(
    content: str = "判断の内容",
    raw_text_id: str | None = None,
    revises_fact_id: str | None = None,
    valid_until=None,
    tags: list[str] | None = None,
) -> Fact:
    now = utc_now()
    return Fact(
        id=new_id(),
        content=content,
        status=CANDIDATE,
        valid_from=now,
        valid_until=valid_until,
        tags=tags or [],
        raw_text_id=raw_text_id,
        revises_fact_id=revises_fact_id,
        created_at=now,
        updated_at=now,
    )


def test_ut_sp_01_save_candidate_then_get_revisions(store):
    """UT-SP-01: save_candidate 後に get_revisions で取得できる(raw_text_id 含む)。"""
    raw = RawText(id=new_id(), body="原文", created_at=utc_now())
    store.save_raw_text(raw)
    fact = make_candidate(raw_text_id=raw.id)
    store.save_candidate(fact)

    revisions = store.get_revisions(fact.id)
    assert len(revisions) == 1
    assert revisions[0].status == CANDIDATE
    assert revisions[0].content == fact.content
    assert revisions[0].raw_text_id == raw.id


def test_ut_sp_02_promote_then_find_active(store):
    """UT-SP-02: promote_to_active 後に find_active で取得できる。"""
    fact = make_candidate()
    store.save_candidate(fact)
    promoted = store.promote_to_active(fact.id)

    assert promoted.status == ACTIVE
    actives = store.find_active()
    assert [f.id for f in actives] == [fact.id]
    assert store.get_active(fact.id) is not None


def test_ut_sp_03_supersede_hides_old_and_keeps_history(store):
    """UT-SP-03: supersede 後、旧カードは find_active に現れず superseded で履歴に残る。"""
    old = make_candidate("旧判断")
    store.save_candidate(old)
    store.promote_to_active(old.id)

    new = make_candidate("新判断")
    new.status = ACTIVE
    store.supersede(old.id, new)

    active_ids = {f.id for f in store.find_active()}
    assert old.id not in active_ids
    assert new.id in active_ids
    assert store.get_revisions(old.id)[-1].status == SUPERSEDED


def test_ut_sp_04_find_active_expiry_judgment(store):
    """UT-SP-04: valid_until 超過分を返さない(NULL は有効扱い)。"""
    now = utc_now()
    expired = make_candidate("期限切れ", valid_until=now - timedelta(seconds=1))
    store.save_candidate(expired)
    store.promote_to_active(expired.id)

    endless = make_candidate("無期限")
    store.save_candidate(endless)
    store.promote_to_active(endless.id)

    future = make_candidate("期限内", valid_until=now + timedelta(days=1))
    store.save_candidate(future)
    store.promote_to_active(future.id)

    active_ids = {f.id for f in store.find_active()}
    assert active_ids == {endless.id, future.id}


def test_ut_sp_05_audit_append_and_chronological_read(store):
    """UT-SP-05: 監査イベントが追記され、時系列(記録順)で取得できる。"""
    events = [
        AuditEvent(log_id=new_id(), event_type=t, target_id="fact-1", actor="human")
        for t in ("register", "approve", "transition")
    ]
    for event in events:
        store.append_audit(event)

    read = store.get_audit_events()
    assert [e.event_type for e in read] == ["register", "approve", "transition"]
    assert [e.log_id for e in read] == [e.log_id for e in events]


def test_ut_sp_06_technology_exception_converted_to_e_store(store):
    """UT-SP-06(規約2): 技術固有例外は E_STORE に変換される。素通しなし。"""
    import sqlite3

    raw = RawText(id="dup", body="原文", created_at=utc_now())
    store.save_raw_text(raw)
    try:
        store.save_raw_text(raw)  # PK 重複
        raise AssertionError("重複保存が成功してはならない")
    except StoreError as exc:
        assert exc.code == "E_STORE"
        assert not isinstance(exc, sqlite3.Error)
    except sqlite3.Error:  # pragma: no cover
        raise AssertionError("技術固有例外(sqlite3.Error)が素通しされた")


def test_ut_sp_07_rollback_leaves_no_partial_state(store):
    """UT-SP-07: 書き込み失敗時に正本と履歴の不整合(中途半端な状態)を残さない。"""
    old = make_candidate("旧判断")
    store.save_candidate(old)
    store.promote_to_active(old.id)

    other = make_candidate("別の正本")
    store.save_candidate(other)
    store.promote_to_active(other.id)

    # 新正本の ID を既存正本と衝突させ、supersede の途中(登録)で失敗させる
    conflicting = make_candidate("衝突する新判断")
    conflicting.id = other.id
    conflicting.status = ACTIVE

    with pytest.raises(StoreError):
        store.supersede(old.id, conflicting)

    # ロールバックにより旧正本は active のまま、superseded 履歴も残っていない
    assert store.get_active(old.id) is not None
    assert all(r.status != SUPERSEDED for r in store.get_revisions(old.id))
