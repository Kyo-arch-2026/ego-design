"""単体テスト仕様書 5.3 Approval Flow(UT-AF-01〜02)。Store Port はモック。"""

import pytest

from ego.core.errors import ApprovalError


def test_ut_af_01_pending_lists_only_unprocessed_candidates(core, memory_store):
    """UT-AF-01: 提示一覧は未処理 candidate のみ(rejected・active は含まない)。"""
    c1 = core.sot.register_candidate("未処理その1")
    c2 = core.sot.register_candidate("未処理その2")
    rejected = core.sot.register_candidate("却下済み")
    core.sot.reject(rejected.id)
    approved = core.sot.register_candidate("承認済み")
    core.sot.approve(approved.id)

    pending_ids = {rev.fact_id for rev in core.approval.pending()}
    assert pending_ids == {c1.id, c2.id}


@pytest.mark.parametrize("operation", ["approve", "reject"])
def test_ut_af_02_missing_id_is_approval_error(core, memory_store, operation):
    """UT-AF-02: 存在しない ID の承認/却下は E_APPROVAL。状態変化なし。"""
    before_canonical = dict(memory_store.canonical)
    before_revisions = list(memory_store.revisions)

    with pytest.raises(ApprovalError) as excinfo:
        getattr(core.approval, operation)("no-such-id")

    assert excinfo.value.code == "E_APPROVAL"
    assert memory_store.canonical == before_canonical
    assert memory_store.revisions == before_revisions
