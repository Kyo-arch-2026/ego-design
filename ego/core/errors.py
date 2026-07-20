"""E.G.O のドメインエラー(詳細設計書 6.1)。

技術固有の例外(SQLite 例外・HTTP エラー等)はアダプタ内で捕捉し、
これらのドメインエラーに変換してから Core へ返す(規約2)。
"""


class EgoError(Exception):
    """全ドメインエラーの基底。code はエラー分類(E_INPUT 等)。"""

    code = "E_UNKNOWN"

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.message = message
        self.hint = hint

    def display(self) -> str:
        """CLI 向けの一貫形式(詳細設計書 6.2): [E_XXX] メッセージ"""
        text = f"[{self.code}] {self.message}"
        if self.hint:
            text += f"\n  → {self.hint}"
        return text


class InputError(EgoError):
    """入力エラー(空入力・未知コマンド等)。"""

    code = "E_INPUT"


class ApprovalError(EgoError):
    """承認エラー(存在しない candidate の承認等)。"""

    code = "E_APPROVAL"


class StateError(EgoError):
    """状態遷移エラー(遷移表にない遷移の要求)。"""

    code = "E_STATE"


class LlmError(EgoError):
    """LLM エラー(応答失敗・タイムアウト)。"""

    code = "E_LLM"


class StoreError(EgoError):
    """永続化エラー(書き込み失敗等)。"""

    code = "E_STORE"
