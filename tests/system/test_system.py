"""システムテスト仕様書 5(ST)。

- 駆動: CLI コマンド実行(`ego …` 相当をサブプロセスで実行)
- ストレージ: 実 SQLite アダプタ + 本番相当 DB ファイル
- LLM: 実 LLM アダプタ。判定は LLM 生成文言に依存させず、
  状態・件数・ID・監査ログなど決定的要素のみで行う。

実 LLM を要するケース(ST-01〜06・10・11)の構成は次の優先順で選ぶ:
  1. ANTHROPIC_API_KEY があれば実 Claude アダプタ(仕様書 1.3 の本来構成)
  2. なければ Codex CLI 経由の OpenAI 系アダプタ(EGO_LLM_ADAPTER=codex。
     2026-07-20 使用者承認による代替構成。実 Claude 構成での再実施は残課題)
  3. どちらも使えなければ skip
ST-07・08(エラー表示)と ST-09(LLM 障害)は LLM 呼び出し前に完結する、
または障害注入(到達不能エンドポイント)のため、実 LLM なしで実行できる。
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import subprocess
import sys

import pytest

pytestmark = pytest.mark.system

if os.environ.get("ANTHROPIC_API_KEY"):
    _REAL_LLM_ENV: dict | None = {}  # 既定の実 Claude 構成
elif shutil.which("codex"):
    _REAL_LLM_ENV = {"EGO_LLM_ADAPTER": "codex"}  # 承認済みの代替構成
else:
    _REAL_LLM_ENV = None
needs_real_llm = pytest.mark.skipif(
    _REAL_LLM_ENV is None,
    reason="実 LLM 構成(ANTHROPIC_API_KEY または Codex CLI)が必要",
)


def run_ego(db_path: str, *args: str, extra_env: dict | None = None):
    env = dict(os.environ)
    env["EGO_DB_PATH"] = db_path
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "ego.adapters.input.cli.main", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=420,  # Codex CLI 構成では LLM 呼び出しに時間がかかるため余裕を持つ
    )


def extract_id(stdout: str) -> str:
    match = re.search(r"^ID: (\S+)$", stdout, re.MULTILINE)
    assert match, f"出力から ID を取得できない:\n{stdout}"
    return match.group(1)


def query(db_path: str, sql: str, params: tuple = ()) -> list[tuple]:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "ego_system.db")


# ---- 実 Claude 不要のケース --------------------------------------------------


def test_st_07_input_error_display(db_path):
    """ST-07: 空入力・未知コマンドが一貫形式 [E_INPUT] で表示され、終了コード非 0。"""
    result = run_ego(db_path, "record")
    assert result.returncode == 1
    assert "[E_INPUT]" in result.stderr

    result = run_ego(db_path, "fly", "me", "to", "the", "moon")
    assert result.returncode == 1
    assert "[E_INPUT]" in result.stderr


def test_st_08_approval_error_display(db_path):
    """ST-08: 存在しない candidate の承認が [E_APPROVAL] で表示される。"""
    result = run_ego(db_path, "approve", "no-such-id")
    assert result.returncode == 1
    assert "[E_APPROVAL]" in result.stderr


def test_st_09_llm_failure_display_and_raw_preserved(db_path):
    """ST-09: LLM 障害時 [E_LLM] 表示。原文は保存済みで candidate は未生成。"""
    result = run_ego(
        db_path,
        "record",
        "LLM 障害時の記録",
        extra_env={
            "ANTHROPIC_API_KEY": "dummy-key-for-failure-test",
            "EGO_LLM_ENDPOINT": "http://127.0.0.1:9/unreachable",  # 到達不能=障害注入
        },
    )
    assert result.returncode == 1
    assert "[E_LLM]" in result.stderr
    assert query(db_path, "SELECT COUNT(*) FROM raw_text") == [(1,)]
    assert query(db_path, "SELECT COUNT(*) FROM fact_revisions") == [(0,)]


# ---- 実 Claude 構成のフルシナリオ(UC-1〜UC-4 E2E) ---------------------------


@needs_real_llm
def test_st_full_scenario(db_path):
    """ST-01〜06・10・11 を 1 シナリオで実施(API 呼び出し数の節約のため連結)。

    判定は件数・ID・状態・監査ログのみ(LLM 文言には依存しない)。
    """
    # ST-01(UC-1): record → candidate 生成
    result = run_ego(
        db_path, "record", "リレコドス計画の初期方針を A 案とする", extra_env=_REAL_LLM_ENV
    )
    assert result.returncode == 0, result.stderr
    first_id = extract_id(result.stdout)
    assert query(db_path, "SELECT COUNT(*) FROM fact_revisions WHERE status='candidate'") == [(1,)]
    assert query(db_path, "SELECT COUNT(*) FROM canonical_facts") == [(0,)]
    assert query(db_path, "SELECT COUNT(*) FROM raw_text") == [(1,)]

    # ST-02(UC-2): approve → active
    result = run_ego(db_path, "approve", first_id)
    assert result.returncode == 0, result.stderr
    assert query(db_path, "SELECT COUNT(*) FROM canonical_facts WHERE status='active'") == [(1,)]

    # ST-03: reject → 正本化されない
    result = run_ego(db_path, "record", "リレコドス計画を中止する案", extra_env=_REAL_LLM_ENV)
    assert result.returncode == 0, result.stderr
    reject_id = extract_id(result.stdout)
    result = run_ego(db_path, "reject", reject_id)
    assert result.returncode == 0, result.stderr
    assert query(
        db_path,
        "SELECT COUNT(*) FROM fact_revisions WHERE fact_id=? AND status='rejected'",
        (reject_id,),
    ) == [(1,)]
    assert query(db_path, "SELECT COUNT(*) FROM canonical_facts") == [(1,)]

    # ST-04: record --revises → 承認で置換
    result = run_ego(
        db_path,
        "record",
        "リレコドス計画の方針を B 案に変更する",
        "--revises",
        first_id,
        extra_env=_REAL_LLM_ENV,
    )
    assert result.returncode == 0, result.stderr
    second_id = extract_id(result.stdout)
    result = run_ego(db_path, "approve", second_id)
    assert result.returncode == 0, result.stderr
    actives = query(db_path, "SELECT id FROM canonical_facts WHERE status='active'")
    assert actives == [(second_id,)]
    assert query(
        db_path,
        "SELECT COUNT(*) FROM fact_revisions WHERE fact_id=? AND status='superseded'",
        (first_id,),
    ) == [(1,)]

    # ST-05(UC-3): ask は active のみ参照(参照フットプリント ID で判定)
    # キーワードは OR 一致のため複数指定し、判定は ID の有無のみで行う
    result = run_ego(db_path, "ask", "リレコドス", "計画", "方針")
    assert result.returncode == 0, result.stderr
    assert second_id in result.stdout
    assert first_id not in result.stdout
    assert reject_id not in result.stdout

    # ST-06(UC-4): history はカード(fact_id)単位(詳細設計書 0.4)
    result = run_ego(db_path, "history", first_id)
    assert result.returncode == 0, result.stderr
    assert "candidate" in result.stdout
    assert "superseded" in result.stdout

    # ST-10: 再起動(別プロセス)後も永続化されている
    result = run_ego(db_path, "history", second_id)
    assert result.returncode == 0, result.stderr
    assert "active" in result.stdout

    # ST-11(T-7): 監査ログの完全性(発生順・欠落なし)
    rows = query(db_path, "SELECT event_type, target_id FROM audit_log ORDER BY rowid")
    assert rows == [
        ("register", first_id),
        ("approve", first_id),
        ("register", reject_id),
        ("reject", reject_id),
        ("register", second_id),
        ("transition", first_id),
        ("approve", second_id),
    ]
