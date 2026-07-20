"""Codex CLI Adapter: LLM Port の代替実装(テスト用途で追加)。

OpenAI 系モデルを Codex CLI(`codex exec`)のサブプロセス実行で呼び出す。
認証(OAuth トークン)は Codex CLI 自身が保持・更新するため、本アダプタは
資格情報に一切触れない。

- 本番既定は Claude アダプタのまま。本アダプタは EGO_LLM_ADAPTER=codex を
  明示した場合のみ注入される(規約5)。
- LLM Port のシグネチャは不変(規約2)。CLI サブプロセスという技術詳細は
  本アダプタに閉じており、Core は差し替えを知らない(規約1〜4 の実証)。
- 失敗(起動不可・非 0 終了・タイムアウト・不正応答)は LlmError(E_LLM)に
  変換して返す(技術例外の素通し禁止)。
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from ego.core.domain import StructuredThought
from ego.core.errors import LlmError
from ego.ports.llm_port import LLMPort

_PROMPT_TEMPLATE = (
    "次の自由記述を読み、思考の構造化を行ってください。"
    "出力は次のキーを持つ JSON オブジェクトのみとします: "
    '{{"summary": "1〜2文の要約", "issues": ["課題", ...], '
    '"options": ["選択肢", ...], "next_actions": ["次のアクション", ...]}}。'
    "JSON 以外の文字は一切出力しないでください。\n\n"
    "自由記述:\n{text}"
)

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "issues": {"type": "array", "items": {"type": "string"}},
        "options": {"type": "array", "items": {"type": "string"}},
        "next_actions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "issues", "options", "next_actions"],
    "additionalProperties": False,
}


class CodexCliLLMAdapter(LLMPort):
    def __init__(
        self,
        model: str | None = None,
        command: str = "codex",
        timeout: float = 300.0,
    ):
        self._model = model
        self._command = command
        self._timeout = timeout

    def structure(self, text: str) -> StructuredThought:
        with tempfile.TemporaryDirectory(prefix="ego-codex-") as workdir:
            out_path = Path(workdir) / "last_message.txt"
            schema_path = Path(workdir) / "output_schema.json"
            schema_path.write_text(json.dumps(_OUTPUT_SCHEMA), encoding="utf-8")

            # --cd で空の作業ディレクトリを指定し、リポジトリ走査をさせない
            cmd = [
                self._command,
                "exec",
                "--sandbox", "read-only",
                "--skip-git-repo-check",
                "--cd", workdir,
                "--output-last-message", str(out_path),
                "--output-schema", str(schema_path),
            ]
            if self._model:
                cmd += ["--model", self._model]
            cmd.append(_PROMPT_TEMPLATE.format(text=text))

            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=self._timeout
                )
            except subprocess.TimeoutExpired as exc:
                raise LlmError(
                    f"LLM の応答がタイムアウトしました({self._timeout}秒)",
                    hint="時間を置いて再実行してください。原文は保存済みです",
                ) from exc
            except OSError as exc:
                raise LlmError(f"LLM 実行環境を起動できません: {exc}") from exc

            if proc.returncode != 0:
                tail = (proc.stderr or proc.stdout or "").strip()[-300:]
                raise LlmError(f"LLM の応答に失敗しました: {tail}")

            try:
                raw = out_path.read_text(encoding="utf-8")
            except OSError as exc:
                raise LlmError(f"LLM 応答を取得できません: {exc}") from exc

        return self._to_structured_thought(raw)

    @staticmethod
    def _to_structured_thought(raw: str) -> StructuredThought:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise LlmError("LLM 応答に構造化結果が含まれていません")
        try:
            data = json.loads(cleaned[start : end + 1])
            return StructuredThought(
                summary=str(data["summary"]),
                issues=[str(x) for x in data.get("issues", [])],
                options=[str(x) for x in data.get("options", [])],
                next_actions=[str(x) for x in data.get("next_actions", [])],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise LlmError(f"LLM 応答を構造化結果に変換できません: {exc}") from exc
