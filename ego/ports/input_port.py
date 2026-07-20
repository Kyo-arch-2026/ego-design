"""Input Port(G-1): 入力の抽象境界。

アダプタ(CLI/Discord/Hermes…)が技術差を吸収し、正規化済みの
InputMessage(ドメイン型)を Core に渡す。Discord の Message オブジェクトや
CLI の argv をそのまま Core へ渡してはならない(規約2)。
"""

from abc import ABC, abstractmethod

from ego.core.domain import InputMessage


class InputPort(ABC):
    @abstractmethod
    def receive(self) -> InputMessage:
        """正規化済みの入力を 1 件返す。"""
        raise NotImplementedError
