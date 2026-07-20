"""Source of Truth(C 層): 正本・履歴の管理と状態遷移。E.G.O の核心。

正本と履歴を分離管理し、状態遷移として履歴を残す。
永続化は Store Port のみに依存し、SQLite・SQL 文字列を直接扱わない(規約1・2)。
"""

from ego.core.domain import (
    ACTIVE,
    CANDIDATE,
    PHASE_1_0_TRANSITIONS,
    Fact,
    Revision,
    new_id,
    utc_now,
)
from ego.core.audit import AuditLog
from ego.core.errors import ApprovalError, InputError, StateError
from ego.ports.store_port import StorePort


class SourceOfTruth:
    def __init__(self, store: StorePort, audit: AuditLog):
        self._store = store
        self._audit = audit

    # ---- 状態の観測 ----

    def current_status(self, fact_id: str) -> str | None:
        """カードの現在状態。正本にあれば active、なければ履歴の最新状態。"""
        if self._store.get_active(fact_id) is not None:
            return ACTIVE
        revisions = self._store.get_revisions(fact_id)
        if not revisions:
            return None
        return revisions[-1].status

    # ---- candidate 登録(C-1-2, B-6) ----

    def register_candidate(
        self,
        content: str,
        raw_text_id: str | None = None,
        revises_fact_id: str | None = None,
        tags: list[str] | None = None,
    ) -> Fact:
        if revises_fact_id is not None:
            if self._store.get_active(revises_fact_id) is None:
                raise InputError(
                    f"--revises で指定されたカードが active に存在しません: {revises_fact_id}",
                    hint="ego ask で現在の正本カードの ID を確認してください",
                )
        now = utc_now()
        fact = Fact(
            id=new_id(),
            content=content,
            status=CANDIDATE,
            valid_from=now,
            tags=tags or [],
            raw_text_id=raw_text_id,
            revises_fact_id=revises_fact_id,
            created_at=now,
            updated_at=now,
        )
        self._store.save_candidate(fact)
        self._audit.record("register", fact.id, actor="system")
        return fact

    # ---- 承認(C-2-1)・置換(C-2-2) ----

    def approve(self, fact_id: str, actor: str = "human") -> Fact:
        candidate = self._require_transition(fact_id, "approve", actor)
        if candidate.revises_fact_id:
            old = self._store.get_active(candidate.revises_fact_id)
            if old is None:
                raise StateError(
                    f"置換対象のカードが active ではありません: {candidate.revises_fact_id}"
                )
            new_fact = self._fact_from_revision(candidate)
            self._store.supersede(old.id, new_fact)
            self._audit.record(
                "transition",
                old.id,
                actor=actor,
                detail={"from": "active", "to": "superseded", "superseded_by": new_fact.id},
            )
            self._audit.record("approve", new_fact.id, actor=actor)
            return new_fact
        fact = self._store.promote_to_active(fact_id)
        self._audit.record("approve", fact.id, actor=actor)
        return fact

    # ---- 却下(C-2-7) ----

    def reject(self, fact_id: str, actor: str = "human", reason: str | None = None) -> None:
        self._require_transition(fact_id, "reject", actor)
        self._store.mark_rejected(fact_id, reason)
        self._audit.record("reject", fact_id, actor=actor)

    # ---- 履歴(UC-4) ----

    def history(self, fact_id: str) -> tuple[list[Revision], Fact | None]:
        """改訂履歴(時系列)と、現在の正本(active なら Fact)を返す。"""
        revisions = self._store.get_revisions(fact_id)
        current = self._store.get_active(fact_id)
        if not revisions and current is None:
            raise InputError(f"カードが見つかりません: {fact_id}")
        return revisions, current

    # ---- 内部 ----

    def _require_transition(self, fact_id: str, event: str, actor: str) -> Revision:
        """遷移表(4.2)にある遷移かを検査し、candidate の最新改訂を返す。

        カードが存在しない場合は E_APPROVAL、遷移表にない遷移は E_STATE で
        拒否し状態は変えない。拒否は監査に記録する(T-6)。
        """
        status = self.current_status(fact_id)
        if status is None:
            raise ApprovalError(f"該当する candidate がありません: {fact_id}")
        if (status, event) not in PHASE_1_0_TRANSITIONS:
            self._audit.record(
                "transition",
                fact_id,
                actor=actor,
                detail={"denied": True, "from": status, "event": event},
            )
            raise StateError(
                f"不正な状態遷移です: {status} に対して {event} は実行できません"
            )
        revisions = self._store.get_revisions(fact_id)
        return revisions[-1]

    @staticmethod
    def _fact_from_revision(revision: Revision) -> Fact:
        now = utc_now()
        return Fact(
            id=revision.fact_id,
            content=revision.content,
            status=ACTIVE,
            valid_from=revision.valid_from or now,
            valid_until=revision.valid_until,
            topic_tag=revision.topic_tag,
            tags=list(revision.tags),
            raw_text_id=revision.raw_text_id,
            revises_fact_id=revision.revises_fact_id,
            created_at=now,
            updated_at=now,
        )
