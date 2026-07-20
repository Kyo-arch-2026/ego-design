"""単体テスト仕様書 5.3 Session Manager(UT-SM-01〜03)。Store Port はモック。"""

from datetime import timedelta

from ego.core.domain import ACTIVE, Fact, new_id, utc_now


def test_ut_sm_01_reference_converges_to_valid_active_only(core, memory_store):
    """UT-SM-01: 混在状態から参照結果は「今有効な active」のみ。"""
    active = core.sot.register_candidate("有効な正本")
    core.sot.approve(active.id)

    superseded = core.sot.register_candidate("置換される判断")
    core.sot.approve(superseded.id)
    replacement = core.sot.register_candidate("置換後の判断", revises_fact_id=superseded.id)
    core.sot.approve(replacement.id)

    rejected = core.sot.register_candidate("却下される判断")
    core.sot.reject(rejected.id)

    candidate = core.sot.register_candidate("未承認の候補")

    now = utc_now()
    expired = Fact(
        id=new_id(),
        content="期限切れ active",
        status=ACTIVE,
        valid_from=now - timedelta(days=10),
        valid_until=now - timedelta(days=1),
    )
    memory_store.canonical[expired.id] = expired

    ids = {f.id for f in core.session.reference_facts()}
    assert ids == {active.id, replacement.id}
    assert superseded.id not in ids
    assert rejected.id not in ids
    assert candidate.id not in ids
    assert expired.id not in ids


def test_ut_sm_02_tag_filter(core):
    """UT-SM-02: tag 指定で該当 tag の active のみ返る。"""
    work = core.sot.register_candidate("仕事の判断", tags=["work"])
    core.sot.approve(work.id)
    home = core.sot.register_candidate("家の判断", tags=["home"])
    core.sot.approve(home.id)

    ids = {f.id for f in core.session.reference_facts(tag="work")}
    assert ids == {work.id}


def test_ut_sm_03_reference_scope_control(core):
    """UT-SM-03: 参照許可範囲を指定すると LLM へ渡す集合が限定される。"""
    facts = []
    for i in range(10):
        fact = core.sot.register_candidate(f"正本 {i}")
        core.sot.approve(fact.id)
        facts.append(fact)

    allowed = {facts[0].id, facts[3].id, facts[7].id}
    result = core.session.reference_facts(allowed_ids=allowed)
    assert {f.id for f in result} == allowed
