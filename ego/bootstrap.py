"""構成ルート(規約5): アダプタの差し込みは起動時にここ一箇所で行う。

どのアダプタを使うかは設定(環境変数)で決める。Core は注入された
ポート実装を使うだけで、どのアダプタかを判定するコードを持たない。
本モジュールは Core の外側にあるため、アダプタを import してよい。

環境変数:
    EGO_DB_PATH        SQLite の DB ファイルパス(既定: ~/.ego/ego.db)
    EGO_STORE_ADAPTER  ストレージアダプタ名(既定: sqlite)
    EGO_LLM_ADAPTER    LLM アダプタ名(既定: claude)
    EGO_LLM_MODEL      LLM モデル名
    EGO_LLM_ENDPOINT   LLM API エンドポイント(試験用の差し替え可)
    ANTHROPIC_API_KEY  Claude API キー(リポジトリに含めず環境変数で注入)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from ego.adapters.llm.claude import ClaudeLLMAdapter
from ego.adapters.store.sqlite import SQLiteStoreAdapter
from ego.core.approval import ApprovalFlow
from ego.core.audit import AuditLog
from ego.core.session import SessionManager
from ego.core.sot import SourceOfTruth
from ego.core.structurer import ThoughtStructurer
from ego.ports.llm_port import LLMPort
from ego.ports.store_port import StorePort

_DEFAULT_DB_PATH = "~/.ego/ego.db"


@dataclass
class AppConfig:
    store_adapter: str = "sqlite"
    db_path: str = _DEFAULT_DB_PATH
    llm_adapter: str = "claude"
    llm_model: str = "claude-sonnet-5"
    llm_endpoint: str | None = None
    api_key: str | None = None

    @classmethod
    def from_env(cls) -> "AppConfig":
        return cls(
            store_adapter=os.environ.get("EGO_STORE_ADAPTER", "sqlite"),
            db_path=os.environ.get("EGO_DB_PATH", _DEFAULT_DB_PATH),
            llm_adapter=os.environ.get("EGO_LLM_ADAPTER", "claude"),
            llm_model=os.environ.get("EGO_LLM_MODEL", "claude-sonnet-5"),
            llm_endpoint=os.environ.get("EGO_LLM_ENDPOINT"),
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
        )


@dataclass
class App:
    store: StorePort
    llm: LLMPort
    audit: AuditLog
    sot: SourceOfTruth
    structurer: ThoughtStructurer
    approval: ApprovalFlow
    session: SessionManager


def build_store(config: AppConfig) -> StorePort:
    if config.store_adapter == "sqlite":
        db_path = str(Path(config.db_path).expanduser())
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        return SQLiteStoreAdapter(db_path)
    raise ValueError(f"未知のストレージアダプタです: {config.store_adapter}")


def build_llm(config: AppConfig) -> LLMPort:
    if config.llm_adapter == "claude":
        kwargs: dict = {"api_key": config.api_key, "model": config.llm_model}
        if config.llm_endpoint:
            kwargs["endpoint"] = config.llm_endpoint
        return ClaudeLLMAdapter(**kwargs)
    raise ValueError(f"未知の LLM アダプタです: {config.llm_adapter}")


def build_app(
    config: AppConfig | None = None,
    store: StorePort | None = None,
    llm: LLMPort | None = None,
) -> App:
    """アプリを組み立てる。store / llm を渡すとそのポート実装を注入する(テスト用)。"""
    config = config or AppConfig.from_env()
    store = store or build_store(config)
    llm = llm or build_llm(config)

    audit = AuditLog(store)
    sot = SourceOfTruth(store, audit)
    return App(
        store=store,
        llm=llm,
        audit=audit,
        sot=sot,
        structurer=ThoughtStructurer(store, llm, sot),
        approval=ApprovalFlow(store, sot),
        session=SessionManager(store),
    )
