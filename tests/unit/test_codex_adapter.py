"""Codex CLI アダプタ(LLM Port 代替実装)の単体テスト(仕様書外の追加分)。

サブプロセスはモックし、実 CLI は起動しない。
"""

import json
import subprocess

import pytest

from ego.adapters.llm.codex_cli import CodexCliLLMAdapter
from ego.core.domain import StructuredThought
from ego.core.errors import LlmError


def _fake_run_success(payload: dict):
    def fake_run(cmd, capture_output=None, text=None, timeout=None):
        out_path = cmd[cmd.index("--output-last-message") + 1]
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    return fake_run


def test_codex_adapter_converts_to_domain_type(monkeypatch):
    """成功時: CLI の最終応答が StructuredThought(ドメイン型)に変換される。"""
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run_success(
            {
                "summary": "方針の整理",
                "issues": ["論点A"],
                "options": ["案1", "案2"],
                "next_actions": ["次の一手"],
            }
        ),
    )
    result = CodexCliLLMAdapter().structure("方針について考える")
    assert isinstance(result, StructuredThought)
    assert result.summary == "方針の整理"
    assert result.options == ["案1", "案2"]


def test_codex_adapter_nonzero_exit_is_e_llm(monkeypatch):
    """CLI が非 0 終了なら E_LLM(技術詳細の素通しなし)。"""
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="auth error"),
    )
    with pytest.raises(LlmError) as excinfo:
        CodexCliLLMAdapter().structure("失敗するケース")
    assert excinfo.value.code == "E_LLM"


def test_codex_adapter_timeout_is_e_llm(monkeypatch):
    """タイムアウトも E_LLM に変換される。"""

    def raise_timeout(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    with pytest.raises(LlmError) as excinfo:
        CodexCliLLMAdapter(timeout=1).structure("タイムアウトするケース")
    assert excinfo.value.code == "E_LLM"


def test_codex_adapter_missing_command_is_e_llm(monkeypatch):
    """CLI 自体が存在しない環境でも E_LLM(OSError の素通しなし)。"""
    adapter = CodexCliLLMAdapter(command="/nonexistent/codex-cli")
    with pytest.raises(LlmError) as excinfo:
        adapter.structure("CLI が無いケース")
    assert excinfo.value.code == "E_LLM"
