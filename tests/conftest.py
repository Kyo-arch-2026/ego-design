"""テスト共通のポート実装。

- MemoryStore: Store Port のインメモリ・モック(呼び出し記録付き)。
  単体テストで Core を実 SQLite に触れさせないために使う。
- FakeLLM: LLM Port の決定的フェイクアダプタ(固定応答・エラー注入可能)。
  結合テストの方針(結合テスト仕様書 1.3)に準拠。
"""

from __future__ import annotations

import pytest

from ego.core.domain import (
    ACTIVE,
    CANDIDATE,
    REJECTED,
    SUPERSEDED,
    AuditEvent,
    Fact,
    RawText,
    Revision,
    StructuredThought,
    is_currently_valid,
    new_id,
    utc_now,
)
from ego.core.errors import LlmError, StoreError
from ego.ports.llm_port import LLMPort
from ego.ports.store_port import StorePort


class MemoryStore(StorePort):
    """Store Port のインメモリ実装(単体テスト用モック)。

    calls に (メソッド名, 主要引数) を記録する。
    """

    def __init__(self):
        self.calls: list[tuple] = []
        self.raw_texts: dict[str, RawText] = {}
        self.revisions: list[Revision] = []
        self.canonical: dict[str, Fact] = {}
        self.audits: list[AuditEvent] = []

    # ---- 原文 ----

    def save_raw_text(self, raw: RawText) -> None:
        self.calls.append(("save_raw_text", raw.id))
        self.raw_texts[raw.id] = raw

    # ---- 候補・正本 ----

    def save_candidate(self, fact: Fact, audit: AuditEvent | None = None) -> None:
        self.calls.append(("save_candidate", fact.id))
        if audit is not None:
            self.audits.append(audit)
        self.revisions.append(
            Revision(
                revision_id=new_id(),
                fact_id=fact.id,
                content=fact.content,
                status=CANDIDATE,
                tags=list(fact.tags),
                raw_text_id=fact.raw_text_id,
                revises_fact_id=fact.revises_fact_id,
                topic_tag=fact.topic_tag,
                valid_from=fact.valid_from,
                valid_until=fact.valid_until,
                created_at=utc_now(),
            )
        )

    def find_candidates(self) -> list[Revision]:
        self.calls.append(("find_candidates",))
        latest: dict[str, Revision] = {}
        for rev in self.revisions:
            latest[rev.fact_id] = rev
        return [
            rev
            for rev in latest.values()
            if rev.status == CANDIDATE and rev.fact_id not in self.canonical
        ]

    def _latest_candidate(self, fact_id: str) -> Revision:
        revs = [r for r in self.revisions if r.fact_id == fact_id]
        if not revs or revs[-1].status != CANDIDATE:
            raise StoreError(f"candidate が見つかりません: {fact_id}")
        return revs[-1]

    def promote_to_active(self, fact_id: str, audit: AuditEvent | None = None) -> Fact:
        self.calls.append(("promote_to_active", fact_id))
        rev = self._latest_candidate(fact_id)
        if audit is not None:
            self.audits.append(audit)
        now = utc_now()
        fact = Fact(
            id=rev.fact_id,
            content=rev.content,
            status=ACTIVE,
            valid_from=rev.valid_from or now,
            valid_until=rev.valid_until,
            topic_tag=rev.topic_tag,
            tags=list(rev.tags),
            raw_text_id=rev.raw_text_id,
            revises_fact_id=rev.revises_fact_id,
            created_at=now,
            updated_at=now,
        )
        self.canonical[fact.id] = fact
        return fact

    def mark_rejected(
        self,
        fact_id: str,
        reason: str | None = None,
        audit: AuditEvent | None = None,
    ) -> None:
        self.calls.append(("mark_rejected", fact_id))
        rev = self._latest_candidate(fact_id)
        if audit is not None:
            self.audits.append(audit)
        self.revisions.append(
            Revision(
                revision_id=new_id(),
                fact_id=fact_id,
                content=rev.content,
                status=REJECTED,
                reason=reason,
                tags=list(rev.tags),
                raw_text_id=rev.raw_text_id,
                revises_fact_id=rev.revises_fact_id,
                created_at=utc_now(),
            )
        )

    def supersede(
        self,
        old_fact_id: str,
        new_fact: Fact,
        audits: list[AuditEvent] | None = None,
    ) -> None:
        self.calls.append(("supersede", old_fact_id, new_fact.id))
        old = self.canonical.get(old_fact_id)
        if old is None:
            raise StoreError(f"置換対象の正本が存在しません: {old_fact_id}")
        self.audits.extend(audits or [])
        self.revisions.append(
            Revision(
                revision_id=new_id(),
                fact_id=old_fact_id,
                content=old.content,
                status=SUPERSEDED,
                reason=f"superseded by {new_fact.id}",
                tags=list(old.tags),
                raw_text_id=old.raw_text_id,
                created_at=utc_now(),
            )
        )
        del self.canonical[old_fact_id]
        self.canonical[new_fact.id] = new_fact

    # ---- 参照 ----

    def find_active(self, tag: str | None = None) -> list[Fact]:
        self.calls.append(("find_active", tag))
        now = utc_now()
        facts = [f for f in self.canonical.values() if is_currently_valid(f, now)]
        if tag is not None:
            facts = [f for f in facts if tag in f.tags]
        return facts

    def find_active_by_topic(self, topic_tag: str) -> list[Fact]:
        self.calls.append(("find_active_by_topic", topic_tag))
        return [f for f in self.find_active() if f.topic_tag == topic_tag]

    def get_active(self, fact_id: str) -> Fact | None:
        return self.canonical.get(fact_id)

    # ---- 履歴 ----

    def get_revisions(self, fact_id: str) -> list[Revision]:
        return [r for r in self.revisions if r.fact_id == fact_id]

    # ---- 監査 ----

    def append_audit(self, event: AuditEvent) -> None:
        self.calls.append(("append_audit", event.event_type, event.target_id))
        self.audits.append(event)

    def get_audit_events(self, target_id: str | None = None) -> list[AuditEvent]:
        if target_id is None:
            return list(self.audits)
        return [e for e in self.audits if e.target_id == target_id]


class FakeLLM(LLMPort):
    """LLM Port の決定的フェイクアダプタ。固定応答・エラー注入可能。"""

    def __init__(self, thought: StructuredThought | None = None, error: Exception | None = None):
        self.thought = thought
        self.error = error
        self.calls: list[str] = []

    def structure(self, text: str) -> StructuredThought:
        self.calls.append(text)
        if self.error is not None:
            raise self.error
        if self.thought is not None:
            return self.thought
        return StructuredThought(
            summary=f"要約: {text}",
            issues=["課題A"],
            options=["選択肢A", "選択肢B"],
            next_actions=["次アクションA"],
        )


@pytest.fixture
def memory_store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def core(memory_store, fake_llm):
    """Core 一式(全ポートをモック/フェイクに差し替え)。"""
    from ego.bootstrap import AppConfig, build_app

    return build_app(config=AppConfig(), store=memory_store, llm=fake_llm)


def make_llm_error() -> LlmError:
    return LlmError("LLM の応答に失敗しました(テスト注入)")
