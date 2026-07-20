"""単体テスト仕様書 5.5 Claude Adapter(UT-LLM-01〜02)。API 応答は HTTP レベルでモック。"""

import io
import json
import urllib.error
import urllib.request
from contextlib import contextmanager

import pytest

from ego.adapters.llm.claude import ClaudeLLMAdapter
from ego.core.domain import StructuredThought
from ego.core.errors import LlmError


def _fake_api_response(payload: dict):
    body = json.dumps({"content": [{"text": json.dumps(payload, ensure_ascii=False)}]})

    @contextmanager
    def fake_urlopen(request, timeout=None):
        yield io.BytesIO(body.encode("utf-8"))

    return fake_urlopen


def test_ut_llm_01_api_response_converted_to_domain_type(monkeypatch):
    """UT-LLM-01: API 応答が StructuredThought(ドメイン型)に変換される。"""
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        _fake_api_response(
            {
                "summary": "転職方針の整理",
                "issues": ["スキル棚卸しが未了"],
                "options": ["現職継続", "転職活動"],
                "next_actions": ["職務経歴書を書く"],
            }
        ),
    )
    adapter = ClaudeLLMAdapter(api_key="test-key")
    result = adapter.structure("転職について考えている")

    assert isinstance(result, StructuredThought)
    assert result.summary == "転職方針の整理"
    assert result.issues == ["スキル棚卸しが未了"]
    assert result.options == ["現職継続", "転職活動"]
    assert result.next_actions == ["職務経歴書を書く"]


def test_ut_llm_02_timeout_retried_then_e_llm(monkeypatch):
    """UT-LLM-02: タイムアウト・応答失敗はリトライ後 E_LLM に変換(素通しなし)。"""
    attempts = []

    def failing_urlopen(request, timeout=None):
        attempts.append(1)
        raise urllib.error.URLError("connection timed out")

    monkeypatch.setattr(urllib.request, "urlopen", failing_urlopen)
    adapter = ClaudeLLMAdapter(api_key="test-key", max_retries=1)

    with pytest.raises(LlmError) as excinfo:
        adapter.structure("失敗するケース")

    assert excinfo.value.code == "E_LLM"
    assert len(attempts) == 2  # 初回 + リトライ 1 回
    assert not isinstance(excinfo.value, urllib.error.URLError)


def test_ut_llm_02c_http_200_with_broken_body_is_e_llm(monkeypatch):
    """レビュー指摘対応: 200 応答でも本文が JSON でない場合は E_LLM(素通しなし)。"""

    @contextmanager
    def broken_urlopen(request, timeout=None):
        yield io.BytesIO(b"<html>Service temporarily broken</html>")

    monkeypatch.setattr(urllib.request, "urlopen", broken_urlopen)
    adapter = ClaudeLLMAdapter(api_key="test-key")

    with pytest.raises(LlmError) as excinfo:
        adapter.structure("壊れた応答のケース")
    assert excinfo.value.code == "E_LLM"


def test_ut_llm_02b_missing_api_key_is_e_llm():
    """API キー未設定も技術詳細を漏らさず E_LLM。"""
    adapter = ClaudeLLMAdapter(api_key=None)
    with pytest.raises(LlmError) as excinfo:
        adapter.structure("キーなし")
    assert excinfo.value.code == "E_LLM"
