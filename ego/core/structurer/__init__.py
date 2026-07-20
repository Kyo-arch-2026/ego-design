"""Thought Structurer(B 層): 自由記述の構造化・候補登録。

原文を保持(B-5)し、LLM Port 経由で構造化(B-1〜B-4)、結果を candidate と
して登録する(B-6)。出力はまだ正本ではない(原則2)。
具体アダプタには依存しない。
"""

from ego.core.domain import Fact, RawText, new_id, utc_now
from ego.core.errors import InputError
from ego.core.sot import SourceOfTruth
from ego.ports.llm_port import LLMPort
from ego.ports.store_port import StorePort


class ThoughtStructurer:
    def __init__(self, store: StorePort, llm: LLMPort, sot: SourceOfTruth):
        self._store = store
        self._llm = llm
        self._sot = sot

    def record(
        self,
        text: str,
        revises_fact_id: str | None = None,
        tags: list[str] | None = None,
    ) -> Fact:
        """自由記述を構造化して candidate として登録し、candidate の Fact を返す。

        1. 空入力は LLM を呼ばずに E_INPUT(UT-ST-03)。
        2. 原文を先に保存する。LLM が失敗(E_LLM)しても原文は残る(UT-ST-04)。
        """
        if text is None or not text.strip():
            raise InputError("入力が空です", hint="ego record <自由記述> の形式で入力してください")

        raw = RawText(id=new_id(), body=text, created_at=utc_now())
        self._store.save_raw_text(raw)

        structured = self._llm.structure(text)  # 失敗時は E_LLM がそのまま伝播

        return self._sot.register_candidate(
            content=structured.render(),
            raw_text_id=raw.id,
            revises_fact_id=revises_fact_id,
            tags=tags,
        )
