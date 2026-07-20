"""単体テスト仕様書 5.1 Thought Structurer(UT-ST-01〜04)。

LLM Port・Store Port はモック。実 LLM・実 SQLite には触れない。
"""

import pytest

from ego.core.domain import CANDIDATE
from ego.core.errors import InputError, LlmError
from tests.conftest import make_llm_error


def test_ut_st_01_record_generates_candidate(core, memory_store, fake_llm):
    """UT-ST-01: 構造化され save_candidate が 1 回呼ばれる(正本には昇格しない)。"""
    fact = core.structurer.record("転職活動の方針を考えたい")

    save_calls = [c for c in memory_store.calls if c[0] == "save_candidate"]
    assert len(save_calls) == 1
    assert fact.status == CANDIDATE
    assert "要約:" in fact.content
    assert "選択肢" in fact.content
    # 正本には昇格していない
    assert memory_store.get_active(fact.id) is None
    assert memory_store.find_active() == []


def test_ut_st_02_raw_text_is_preserved(core, memory_store):
    """UT-ST-02: 原文が保存され、candidate の raw_text_id が原文を指す。"""
    original = "これは構造化前の原文そのもの"
    fact = core.structurer.record(original)

    assert fact.raw_text_id is not None
    assert memory_store.raw_texts[fact.raw_text_id].body == original
    revisions = memory_store.get_revisions(fact.id)
    assert revisions[0].raw_text_id == fact.raw_text_id


@pytest.mark.parametrize("empty", ["", "   ", "\n\t"])
def test_ut_st_03_empty_input_rejected_before_llm(core, memory_store, fake_llm, empty):
    """UT-ST-03: 空入力は E_INPUT。LLM Port は呼ばれない。"""
    with pytest.raises(InputError) as excinfo:
        core.structurer.record(empty)
    assert excinfo.value.code == "E_INPUT"
    assert fake_llm.calls == []
    assert memory_store.raw_texts == {}
    assert memory_store.revisions == []


def test_invalid_revises_rejected_before_llm(core, memory_store, fake_llm):
    """レビュー指摘対応: 無効な --revises は LLM を呼ぶ前に E_INPUT。原文も残さない。"""
    with pytest.raises(InputError) as excinfo:
        core.structurer.record("置換のつもりの記録", revises_fact_id="no-such-active")
    assert excinfo.value.code == "E_INPUT"
    assert fake_llm.calls == []
    assert memory_store.raw_texts == {}


def test_ut_st_04_llm_failure_keeps_raw_text(memory_store):
    """UT-ST-04: LLM が E_LLM を返しても原文は保存済み。candidate は未生成。"""
    from ego.bootstrap import AppConfig, build_app
    from tests.conftest import FakeLLM

    failing_llm = FakeLLM(error=make_llm_error())
    core = build_app(config=AppConfig(), store=memory_store, llm=failing_llm)

    with pytest.raises(LlmError) as excinfo:
        core.structurer.record("LLM が落ちるケース")
    assert excinfo.value.code == "E_LLM"
    assert len(memory_store.raw_texts) == 1  # 原文は残る
    assert memory_store.revisions == []      # candidate は未生成
