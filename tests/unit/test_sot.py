"""単体テスト仕様書 5.2 Source of Truth(UT-SOT-01〜06)。Store Port はモック。"""

from datetime import timedelta

import pytest

from ego.core.domain import (
    ACTIVE,
    CANDIDATE,
    REJECTED,
    SUPERSEDED,
    Fact,
    is_currently_valid,
    new_id,
    utc_now,
)
from ego.core.errors import StateError


def test_ut_sot_01_register_candidate(core, memory_store):
    """UT-SOT-01: status='candidate' で履歴への追記が Store Port に要求される。"""
    fact = core.sot.register_candidate("判断の内容")

    assert ("save_candidate", fact.id) in memory_store.calls
    revisions = memory_store.get_revisions(fact.id)
    assert len(revisions) == 1
    assert revisions[0].status == CANDIDATE


def test_ut_sot_02_approve_promotes_and_audits(core, memory_store):
    """UT-SOT-02: promote_to_active が呼ばれ active 化。監査 approve が記録される。"""
    fact = core.sot.register_candidate("承認される判断")
    approved = core.sot.approve(fact.id)

    assert ("promote_to_active", fact.id) in memory_store.calls
    assert approved.status == ACTIVE
    assert memory_store.get_active(fact.id) is not None
    events = [e.event_type for e in memory_store.get_audit_events(fact.id)]
    assert "approve" in events


def test_ut_sot_03_reject_records_history_not_canonical(core, memory_store):
    """UT-SOT-03: rejected で履歴に記録。正本には入らない。監査 reject 記録。"""
    fact = core.sot.register_candidate("却下される判断")
    core.sot.reject(fact.id)

    revisions = memory_store.get_revisions(fact.id)
    assert revisions[-1].status == REJECTED
    assert memory_store.get_active(fact.id) is None
    assert memory_store.find_active() == []
    events = [e.event_type for e in memory_store.get_audit_events(fact.id)]
    assert "reject" in events


def test_ut_sot_04_approve_with_revises_supersedes(core, memory_store):
    """UT-SOT-04: revises 指定 candidate の承認で supersede。旧 active → superseded。"""
    old = core.sot.register_candidate("旧しい判断")
    core.sot.approve(old.id)

    new = core.sot.register_candidate("新しい判断", revises_fact_id=old.id)
    approved = core.sot.approve(new.id)

    assert ("supersede", old.id, new.id) in memory_store.calls
    assert memory_store.get_active(old.id) is None
    assert memory_store.get_revisions(old.id)[-1].status == SUPERSEDED
    assert approved.status == ACTIVE
    assert memory_store.get_active(new.id) is not None


@pytest.mark.parametrize("setup_state", ["rejected", "superseded", "active"])
def test_ut_sot_05_invalid_transition_rejected(core, memory_store, setup_state):
    """UT-SOT-05(T-6): 遷移表にない遷移は E_STATE で拒否。状態不変。監査に拒否を記録。"""
    fact = core.sot.register_candidate("遷移テスト対象")
    if setup_state == "rejected":
        core.sot.reject(fact.id)
    elif setup_state == "active":
        core.sot.approve(fact.id)
    else:  # superseded
        core.sot.approve(fact.id)
        newer = core.sot.register_candidate("置換する判断", revises_fact_id=fact.id)
        core.sot.approve(newer.id)

    before_status = core.sot.current_status(fact.id)
    before_revision_count = len(memory_store.get_revisions(fact.id))

    with pytest.raises(StateError) as excinfo:
        core.sot.approve(fact.id)

    assert excinfo.value.code == "E_STATE"
    # 状態不変
    assert core.sot.current_status(fact.id) == before_status
    assert len(memory_store.get_revisions(fact.id)) == before_revision_count
    # 監査に拒否が記録される
    denials = [
        e
        for e in memory_store.get_audit_events(fact.id)
        if e.event_type == "transition" and (e.detail or {}).get("denied")
    ]
    assert len(denials) == 1


def test_ut_sot_06_expired_active_excluded(core, memory_store):
    """UT-SOT-06: valid_until が過去の active は「今有効な正本」から除外(参照時判定)。"""
    now = utc_now()
    expired = Fact(
        id=new_id(),
        content="期限切れの判断",
        status=ACTIVE,
        valid_from=now - timedelta(days=30),
        valid_until=now - timedelta(days=1),
    )
    endless = Fact(
        id=new_id(), content="無期限の判断", status=ACTIVE, valid_from=now
    )
    future = Fact(
        id=new_id(),
        content="期限内の判断",
        status=ACTIVE,
        valid_from=now,
        valid_until=now + timedelta(days=1),
    )

    assert is_currently_valid(expired, now) is False
    assert is_currently_valid(endless, now) is True
    assert is_currently_valid(future, now) is True

    # 期限切れは物理退避されず参照時に除外される(Session Manager 側の収束)
    memory_store.canonical[expired.id] = expired
    memory_store.canonical[endless.id] = endless
    ids = {f.id for f in core.session.reference_facts()}
    assert ids == {endless.id}
    assert memory_store.canonical.get(expired.id) is not None  # 物理退避しない
