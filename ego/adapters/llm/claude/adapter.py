"""Claude Adapter(G-6): LLM Port の Phase 1.0 実装。

- API 応答 ↔ StructuredThought(ドメイン型)の変換だけを担う(規約3)。
- HTTP エラー・タイムアウトはリトライ後、LlmError(E_LLM)に変換して返す
  (規約2。技術例外の素通し禁止)。
- API キー等の秘密情報は環境変数で注入する(詳細設計書 8.1)。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from ego.core.domain import StructuredThought
from ego.core.errors import LlmError
from ego.ports.llm_port import LLMPort

_DEFAULT_ENDPOINT = "https://api.anthropic.com/v1/messages"
_DEFAULT_MODEL = "claude-sonnet-5"

_SYSTEM_PROMPT = (
    "あなたは思考の構造化を行うアシスタントです。"
    "与えられた自由記述を読み、次のキーを持つ JSON オブジェクトのみを返してください: "
    '{"summary": "1〜2文の要約", "issues": ["課題", ...], '
    '"options": ["選択肢", ...], "next_actions": ["次のアクション", ...]}。'
    "JSON 以外の文字(前置き・コードフェンス)は一切出力しないでください。"
)


class ClaudeLLMAdapter(LLMPort):
    def __init__(
        self,
        api_key: str | None,
        model: str = _DEFAULT_MODEL,
        endpoint: str = _DEFAULT_ENDPOINT,
        timeout: float = 60.0,
        max_retries: int = 1,
    ):
        self._api_key = api_key
        self._model = model
        self._endpoint = endpoint
        self._timeout = timeout
        self._max_retries = max_retries

    def structure(self, text: str) -> StructuredThought:
        if not self._api_key:
            raise LlmError(
                "LLM の認証情報が設定されていません",
                hint="環境変数 ANTHROPIC_API_KEY を設定してください",
            )
        payload = {
            "model": self._model,
            "max_tokens": 1024,
            "system": _SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": text}],
        }
        last_error: Exception | None = None
        for _attempt in range(self._max_retries + 1):
            try:
                body = self._post(payload)
                return self._to_structured_thought(body)
            except LlmError:
                raise  # 応答形式の異常はリトライしても直らない
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
                last_error = exc
        raise LlmError(
            f"LLM の応答に失敗しました(リトライ上限到達): {last_error}",
            hint="時間を置いて再実行してください。原文は保存済みです",
        )

    # ---- HTTP 層(テストではここをモックする) ----

    def _post(self, payload: dict) -> dict:
        try:
            request = urllib.request.Request(
                self._endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "content-type": "application/json",
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                },
                method="POST",
            )
        except ValueError as exc:
            # 接続先指定の不正も技術例外を素通しさせない(規約2)
            raise LlmError(f"LLM 接続先の指定が不正です: {exc}") from exc
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            raw = response.read()
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            # 200 応答でも本文が壊れているケース。技術例外を素通しさせない(規約2)
            raise LlmError(f"LLM 応答の解析に失敗しました: {exc}") from exc

    # ---- 応答 → ドメイン型変換 ----

    @staticmethod
    def _to_structured_thought(body: dict) -> StructuredThought:
        try:
            text = body["content"][0]["text"]
            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("`")
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
            data = json.loads(cleaned)
            return StructuredThought(
                summary=str(data["summary"]),
                issues=[str(x) for x in data.get("issues", [])],
                options=[str(x) for x in data.get("options", [])],
                next_actions=[str(x) for x in data.get("next_actions", [])],
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LlmError(f"LLM 応答を構造化結果に変換できません: {exc}") from exc
