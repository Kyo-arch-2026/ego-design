"""単体テスト仕様書 5.3 Audit Log(UT-AL-01〜02)。Store Port はモック。"""

import pytest


def test_ut_al_01_all_event_types_recorded(core, memory_store):
    """UT-AL-01: 各イベントが event_type・target_id・actor 付きで append_audit される。"""
    cases = [
        ("register", "fact-1", "system"),
        ("approve", "fact-1", "human"),
        ("reject", "fact-2", "human"),
        ("transition", "fact-3", "human"),
    ]
    for event_type, target_id, actor in cases:
        core.audit.record(event_type, target_id, actor=actor)

    recorded = [(e.event_type, e.target_id, e.actor) for e in memory_store.audits]
    assert recorded == cases
    append_calls = [c for c in memory_store.calls if c[0] == "append_audit"]
    assert len(append_calls) == len(cases)


def test_ut_al_02_append_only_no_update_or_delete(core, memory_store):
    """UT-AL-02: 既存ログを更新・削除する手段が存在しない(追記専用)。"""
    from ego.ports.store_port import StorePort

    forbidden = ("update", "delete", "remove", "clear", "modify", "overwrite")
    for target in (core.audit, StorePort):
        for name in dir(target):
            lowered = name.lower()
            assert not any(
                lowered.startswith(word) or f"{word}_audit" in lowered or f"audit_{word}" in lowered
                for word in forbidden
            ), f"追記専用に反する口が存在する: {target}.{name}"
