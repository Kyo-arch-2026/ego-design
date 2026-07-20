"""Approval Flow(D 層): 候補の提示・承認・却下・記録。

AI の解釈(candidate)は人間の承認を経て初めて正本(active)になる(原則2)。
"""

from ego.core.domain import Fact, Revision
from ego.core.sot import SourceOfTruth
from ego.ports.store_port import StorePort


class ApprovalFlow:
    def __init__(self, store: StorePort, sot: SourceOfTruth):
        self._store = store
        self._sot = sot

    def pending(self) -> list[Revision]:
        """未処理 candidate の一覧(D-1)。rejected・active は含まない。"""
        return self._store.find_candidates()

    def approve(self, fact_id: str) -> Fact:
        """承認による active 昇格(D-2)。監査記録は Source of Truth 経由(D-5)。"""
        return self._sot.approve(fact_id, actor="human")

    def reject(self, fact_id: str, reason: str | None = None) -> None:
        """却下(D-3)。正本化しない。"""
        self._sot.reject(fact_id, actor="human", reason=reason)
