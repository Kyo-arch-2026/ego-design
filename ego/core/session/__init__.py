"""Session Manager(E 層): 参照範囲制御・絞り込み。Store Port 経由。

Phase 1.0 は E-2(機械的な収束)のみ:参照結果は「今有効な active」に限る。
ベクトル検索(E-1)は Phase 1.5。
"""

from ego.core.domain import Fact, is_currently_valid, utc_now
from ego.core.errors import InputError
from ego.ports.store_port import StorePort


class SessionManager:
    def __init__(self, store: StorePort):
        self._store = store

    def reference_facts(
        self,
        tag: str | None = None,
        allowed_ids: set[str] | None = None,
    ) -> list[Fact]:
        """AI に渡してよい正本の集合を返す(E-4・E-5: 参照範囲制御)。

        Store Port の find_active が期限判定を担うが、Core 側でも
        is_currently_valid で二重に収束させ、active 以外を決して通さない。
        """
        now = utc_now()
        facts = [f for f in self._store.find_active(tag) if is_currently_valid(f, now)]
        if allowed_ids is not None:
            facts = [f for f in facts if f.id in allowed_ids]
        return facts

    def ask(self, query: str, tag: str | None = None) -> list[Fact]:
        """正本を参照して問い合わせる(UC-3)。

        Phase 1.0 はキーワード一致による絞り込み(E-2)。対象は常に
        「今有効な active」のみで、superseded・rejected・candidate・
        期限切れ active は参照されない(T-5)。
        """
        if query is None or not query.strip():
            raise InputError("問い合わせ内容が空です", hint="ego ask <キーワード> の形式で入力してください")
        terms = [t.lower() for t in query.split() if t.strip()]
        results = []
        for fact in self.reference_facts(tag=tag):
            haystack = (fact.content + " " + " ".join(fact.tags)).lower()
            if any(term in haystack for term in terms):
                results.append(fact)
        return results
