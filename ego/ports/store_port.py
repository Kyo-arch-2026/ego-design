"""Store Port(G-3): 永続化・検索の抽象境界。

メソッド・引数・戻り値は E.G.O のドメイン概念のみで語る(規約2)。
SQL・接続・カーソル等の技術語彙が登場したら規約違反。
SQLite アダプタはこのシグネチャを SQLite で実装し、PostgreSQL アダプタは
同じシグネチャを PostgreSQL で実装する。Core から見た口は同一。

技術固有の例外はアダプタ内で捕捉し StoreError(E_STORE)に変換する。
書き込み失敗時はトランザクションをロールバックし、正本と履歴の
不整合(中途半端な状態)を残さない。
"""

from abc import ABC, abstractmethod

from ego.core.domain import AuditEvent, Fact, RawText, Revision


class StorePort(ABC):
    # ---- 原文(B-5) ----

    @abstractmethod
    def save_raw_text(self, raw: RawText) -> None:
        """構造化前の原文を保存する。"""
        raise NotImplementedError

    # ---- 候補・正本(C-1, C-2) ----

    @abstractmethod
    def save_candidate(self, fact: Fact) -> None:
        """candidate を履歴に追記する。"""
        raise NotImplementedError

    @abstractmethod
    def find_candidates(self) -> list[Revision]:
        """未処理(承認も却下もされていない)candidate の一覧を返す(D-1)。"""
        raise NotImplementedError

    @abstractmethod
    def promote_to_active(self, fact_id: str) -> Fact:
        """candidate を正本(active)へ昇格する。"""
        raise NotImplementedError

    @abstractmethod
    def mark_rejected(self, fact_id: str, reason: str | None = None) -> None:
        """candidate の却下を履歴に追記する(C-2-7。正本には入れない)。"""
        raise NotImplementedError

    @abstractmethod
    def supersede(self, old_fact_id: str, new_fact: Fact) -> None:
        """旧正本を superseded として履歴へ退避し、新正本を active で登録する。

        退避と登録は不可分(片側だけの状態を残さない)。
        """
        raise NotImplementedError

    # ---- 参照(E-2) ----

    @abstractmethod
    def find_active(self, tag: str | None = None) -> list[Fact]:
        """今有効な active を返す(省略時は全 active、tag 指定で絞り込み)。

        有効期限は valid_until で判定する(NULL は有効扱い)。
        """
        raise NotImplementedError

    @abstractmethod
    def find_active_by_topic(self, topic_tag: str) -> list[Fact]:
        """topic_tag で正本を検索する(📋 C-1-4 実装後の Phase 1.5 用。口だけ定義)。"""
        raise NotImplementedError

    @abstractmethod
    def get_active(self, fact_id: str) -> Fact | None:
        """指定カードが今 active ならその Fact を返す(なければ None)。"""
        raise NotImplementedError

    # ---- 履歴(UC-4) ----

    @abstractmethod
    def get_revisions(self, fact_id: str) -> list[Revision]:
        """カードの改訂履歴を時系列で返す。"""
        raise NotImplementedError

    # ---- 監査(F-1) ----

    @abstractmethod
    def append_audit(self, event: AuditEvent) -> None:
        """監査イベントを追記する(追記専用。更新・削除の口は設けない)。"""
        raise NotImplementedError

    @abstractmethod
    def get_audit_events(self, target_id: str | None = None) -> list[AuditEvent]:
        """監査イベントを記録順で返す(省略時は全件)。"""
        raise NotImplementedError
