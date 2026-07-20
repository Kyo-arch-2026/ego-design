"""LLM Port(G-2): LLM 呼び出しの抽象境界。

メソッドは用途で語る(structure)。プロバイダー名や API の細部を
漏らしてはならない(規約2)。失敗はアダプタ内で E_LLM に変換して返す。
"""

from abc import ABC, abstractmethod

from ego.core.domain import StructuredThought


class LLMPort(ABC):
    @abstractmethod
    def structure(self, text: str) -> StructuredThought:
        """自由記述を構造化する。プロバイダーは問わない。

        失敗時は LlmError(E_LLM)を送出する(技術例外の素通し禁止)。
        """
        raise NotImplementedError
