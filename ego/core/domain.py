"""E.G.O のドメイン型(規約3: ドメイン型はポートの内側=Core 側で定義する)。

ポート・アダプタはこれらの型を介してやり取りする。アダプタは
「外部技術の型 ↔ ドメイン型」の変換だけを担う(例: SQLite の row → Fact)。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

# ---- 状態(詳細設計書 4.2) -------------------------------------------------

CANDIDATE = "candidate"
ACTIVE = "active"
REJECTED = "rejected"
SUPERSEDED = "superseded"
INVALID = "invalid"      # 📋 Phase 1.5(遷移は未実装。要求されたら E_STATE)
ARCHIVED = "archived"    # 📋 Phase 1.5(同上)

ALL_STATUSES = {CANDIDATE, ACTIVE, REJECTED, SUPERSEDED, INVALID, ARCHIVED}

# Phase 1.0 で実装する遷移(現在状態, イベント)→次状態。詳細設計書 4.2 の表に準拠。
# invalid / archived / superseded→active(復元)は Phase 1.5 のため含めない。
PHASE_1_0_TRANSITIONS: dict[tuple[str | None, str], str] = {
    (None, "register"): CANDIDATE,
    (CANDIDATE, "approve"): ACTIVE,
    (CANDIDATE, "reject"): REJECTED,
    (ACTIVE, "supersede"): SUPERSEDED,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def new_id() -> str:
    return str(uuid.uuid4())


# ---- ドメイン型 -------------------------------------------------------------


@dataclass
class RawText:
    """構造化前の原文(B-5: 原文保持)。"""

    id: str
    body: str
    created_at: datetime


@dataclass
class StructuredThought:
    """LLM Port の構造化結果(B-1〜B-4)。"""

    summary: str
    issues: list[str] = field(default_factory=list)
    options: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    def render(self) -> str:
        """カード本文としての表現。"""
        lines = [f"要約: {self.summary}"]
        if self.issues:
            lines.append("課題: " + " / ".join(self.issues))
        if self.options:
            lines.append("選択肢: " + " / ".join(self.options))
        if self.next_actions:
            lines.append("次のアクション: " + " / ".join(self.next_actions))
        return "\n".join(lines)


@dataclass
class Fact:
    """事実カード(C-1-3: 1 判断 = 1 カード)。"""

    id: str
    content: str
    status: str
    valid_from: datetime
    valid_until: datetime | None = None
    topic_tag: str | None = None          # 📋 C-1-4 は Phase 1.5(カラムのみ保持)
    tags: list[str] = field(default_factory=list)
    raw_text_id: str | None = None
    revises_fact_id: str | None = None    # `ego record --revises <id>` で指定
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class Revision:
    """改訂履歴の 1 行(fact_revisions・追記専用)。"""

    revision_id: str
    fact_id: str
    content: str
    status: str
    reason: str | None = None
    topic_tag: str | None = None
    tags: list[str] = field(default_factory=list)
    raw_text_id: str | None = None
    revises_fact_id: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class AuditEvent:
    """監査ログの 1 イベント(F-1)。"""

    log_id: str
    event_type: str          # register / approve / reject / transition
    target_id: str
    actor: str               # human / system
    detail: dict | None = None
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class InputMessage:
    """正規化済みの入力(A-5)。アダプタが技術差(CLI/Discord)を吸収して生成する。"""

    command: str
    text: str = ""
    options: dict = field(default_factory=dict)


# ---- ドメイン判定 -----------------------------------------------------------


def is_currently_valid(fact: Fact, now: datetime | None = None) -> bool:
    """「今有効な正本」判定(詳細設計書 2.2 追記)。

    status='active' かつ (valid_until IS NULL または valid_until > now)。
    期限切れ active の物理退避は行わず、参照時に除外する。
    """
    if fact.status != ACTIVE:
        return False
    if fact.valid_until is None:
        return True
    now = now or utc_now()
    valid_until = fact.valid_until
    if valid_until.tzinfo is None:
        valid_until = valid_until.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return valid_until > now
