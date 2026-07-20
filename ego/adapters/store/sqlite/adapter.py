"""SQLite Adapter(G-4): Store Port の Phase 1.0 実装。

- SQLite の row ↔ ドメイン型(Fact/Revision/AuditEvent)の変換だけを担う(規約3)。
- 技術固有の例外(SQLite 例外・値変換の失敗)は StoreError(E_STORE)に変換して
  返す(規約2。素通し禁止)。
- 変更系メソッドは 1 メソッド = 1 トランザクション。監査イベントを渡された
  場合は状態変更と同一トランザクションで記録し、失敗時はまとめてロール
  バックする(正本・履歴・監査の不整合を残さない。詳細設計書 6.1)。
"""

from __future__ import annotations

import functools
import json
import sqlite3
from datetime import datetime, timezone

from ego.core.domain import (
    ACTIVE,
    CANDIDATE,
    REJECTED,
    SUPERSEDED,
    AuditEvent,
    Fact,
    RawText,
    Revision,
    new_id,
    utc_now,
)
from ego.core.errors import StoreError
from ego.ports.store_port import StorePort

# 外部キーは宣言のみで強制しない(SQLite 既定)。fact_revisions は追記専用で
# superseded 後も旧正本の ID を参照し続けるが、正本テーブル側は active のみ
# 保持(C-1-1)のため置換時に行が消える。履歴からの参照を守るには強制できない。
_SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_text (
    id         TEXT PRIMARY KEY,
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS canonical_facts (
    id              TEXT PRIMARY KEY,
    content         TEXT NOT NULL,
    topic_tag       TEXT,
    status          TEXT NOT NULL CHECK (status = 'active'),
    valid_from      TEXT NOT NULL,
    valid_until     TEXT,
    tags            TEXT,
    raw_text_id     TEXT REFERENCES raw_text(id),
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fact_revisions (
    revision_id     TEXT PRIMARY KEY,
    fact_id         TEXT NOT NULL,
    raw_text_id     TEXT REFERENCES raw_text(id),
    revises_fact_id TEXT,
    content         TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (
        status IN ('candidate','rejected','superseded','invalid','archived')
    ),
    reason          TEXT,
    topic_tag       TEXT,
    tags            TEXT,
    valid_from      TEXT,
    valid_until     TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fact_revisions_fact_id ON fact_revisions(fact_id);
CREATE TABLE IF NOT EXISTS audit_log (
    log_id     TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    target_id  TEXT NOT NULL,
    actor      TEXT NOT NULL,
    detail     TEXT,
    created_at TEXT NOT NULL
);
"""


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _dump_tags(tags: list[str]) -> str:
    return json.dumps(tags or [], ensure_ascii=False)


def _load_tags(value: str | None) -> list[str]:
    return json.loads(value) if value else []


def _store_op(operation: str):
    """技術例外(SQLite・値変換)を E_STORE に変換するデコレータ(規約2)。"""

    def decorate(fn):
        @functools.wraps(fn)
        def wrapper(self, *args, **kwargs):
            try:
                return fn(self, *args, **kwargs)
            except StoreError:
                raise
            except (sqlite3.Error, ValueError, TypeError, KeyError, IndexError) as exc:
                raise StoreError(f"{operation}に失敗しました: {exc}") from exc

        return wrapper

    return decorate


class SQLiteStoreAdapter(StorePort):
    def __init__(self, db_path: str = ":memory:", read_only: bool = False):
        try:
            if read_only:
                self._conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            else:
                self._conn = sqlite3.connect(db_path)
                self._conn.executescript(_SCHEMA)
                self._conn.commit()
            self._conn.row_factory = sqlite3.Row
        except sqlite3.Error as exc:
            raise StoreError(f"ストレージを開けません: {exc}") from exc

    def close(self) -> None:
        self._conn.close()

    # ---- 原文 ----

    @_store_op("原文の保存")
    def save_raw_text(self, raw: RawText) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO raw_text (id, body, created_at) VALUES (?, ?, ?)",
                (raw.id, raw.body, _iso(raw.created_at)),
            )

    # ---- 候補・正本 ----

    @_store_op("candidate の保存")
    def save_candidate(self, fact: Fact, audit: AuditEvent | None = None) -> None:
        with self._conn:
            self._insert_revision(
                fact_id=fact.id,
                content=fact.content,
                status=CANDIDATE,
                raw_text_id=fact.raw_text_id,
                revises_fact_id=fact.revises_fact_id,
                topic_tag=fact.topic_tag,
                tags=fact.tags,
                valid_from=fact.valid_from,
                valid_until=fact.valid_until,
            )
            if audit is not None:
                self._insert_audit(audit)

    @_store_op("candidate の検索")
    def find_candidates(self) -> list[Revision]:
        rows = self._conn.execute(
            """
            SELECT r.* FROM fact_revisions r
            WHERE r.status = 'candidate'
              AND r.fact_id NOT IN (SELECT id FROM canonical_facts)
              AND NOT EXISTS (
                  SELECT 1 FROM fact_revisions later
                  WHERE later.fact_id = r.fact_id AND later.rowid > r.rowid
              )
            ORDER BY r.rowid
            """
        ).fetchall()
        return [self._row_to_revision(row) for row in rows]

    @_store_op("正本化")
    def promote_to_active(self, fact_id: str, audit: AuditEvent | None = None) -> Fact:
        with self._conn:
            revision = self._latest_candidate(fact_id)
            now = utc_now()
            fact = Fact(
                id=revision.fact_id,
                content=revision.content,
                status=ACTIVE,
                valid_from=revision.valid_from or now,
                valid_until=revision.valid_until,
                topic_tag=revision.topic_tag,
                tags=list(revision.tags),
                raw_text_id=revision.raw_text_id,
                revises_fact_id=revision.revises_fact_id,
                created_at=now,
                updated_at=now,
            )
            self._insert_canonical(fact)
            if audit is not None:
                self._insert_audit(audit)
            return fact

    @_store_op("却下の記録")
    def mark_rejected(
        self,
        fact_id: str,
        reason: str | None = None,
        audit: AuditEvent | None = None,
    ) -> None:
        with self._conn:
            revision = self._latest_candidate(fact_id)
            self._insert_revision(
                fact_id=fact_id,
                content=revision.content,
                status=REJECTED,
                reason=reason,
                raw_text_id=revision.raw_text_id,
                revises_fact_id=revision.revises_fact_id,
                topic_tag=revision.topic_tag,
                tags=list(revision.tags),
                valid_from=revision.valid_from,
                valid_until=revision.valid_until,
            )
            if audit is not None:
                self._insert_audit(audit)

    @_store_op("置換")
    def supersede(
        self,
        old_fact_id: str,
        new_fact: Fact,
        audits: list[AuditEvent] | None = None,
    ) -> None:
        with self._conn:
            row = self._conn.execute(
                "SELECT * FROM canonical_facts WHERE id = ?", (old_fact_id,)
            ).fetchone()
            if row is None:
                raise StoreError(f"置換対象の正本が存在しません: {old_fact_id}")
            # 旧正本を superseded として履歴へ退避
            self._insert_revision(
                fact_id=old_fact_id,
                content=row["content"],
                status=SUPERSEDED,
                reason=f"superseded by {new_fact.id}",
                raw_text_id=row["raw_text_id"],
                topic_tag=row["topic_tag"],
                tags=_load_tags(row["tags"]),
                valid_from=_dt(row["valid_from"]),
                valid_until=_dt(row["valid_until"]),
            )
            # 正本テーブルは active のみ保持(C-1-1)
            self._conn.execute(
                "DELETE FROM canonical_facts WHERE id = ?", (old_fact_id,)
            )
            self._insert_canonical(new_fact)
            for event in audits or []:
                self._insert_audit(event)

    # ---- 参照 ----

    @_store_op("正本の検索")
    def find_active(self, tag: str | None = None) -> list[Fact]:
        rows = self._conn.execute(
            """
            SELECT * FROM canonical_facts
            WHERE status = 'active'
              AND (valid_until IS NULL OR valid_until > ?)
            ORDER BY rowid
            """,
            (_iso(utc_now()),),
        ).fetchall()
        facts = [self._row_to_fact(row) for row in rows]
        if tag is not None:
            facts = [f for f in facts if tag in f.tags]
        return facts

    @_store_op("トピック検索")
    def find_active_by_topic(self, topic_tag: str) -> list[Fact]:
        rows = self._conn.execute(
            """
            SELECT * FROM canonical_facts
            WHERE status = 'active' AND topic_tag = ?
              AND (valid_until IS NULL OR valid_until > ?)
            ORDER BY rowid
            """,
            (topic_tag, _iso(utc_now())),
        ).fetchall()
        return [self._row_to_fact(row) for row in rows]

    @_store_op("正本の取得")
    def get_active(self, fact_id: str) -> Fact | None:
        # 有効期限は判定しない(置換・履歴用の契約。Store Port の docstring 参照)
        row = self._conn.execute(
            "SELECT * FROM canonical_facts WHERE id = ? AND status = 'active'",
            (fact_id,),
        ).fetchone()
        return self._row_to_fact(row) if row else None

    # ---- 履歴 ----

    @_store_op("履歴の取得")
    def get_revisions(self, fact_id: str) -> list[Revision]:
        rows = self._conn.execute(
            "SELECT * FROM fact_revisions WHERE fact_id = ? ORDER BY rowid",
            (fact_id,),
        ).fetchall()
        return [self._row_to_revision(row) for row in rows]

    # ---- 監査 ----

    @_store_op("監査ログの記録")
    def append_audit(self, event: AuditEvent) -> None:
        with self._conn:
            self._insert_audit(event)

    @_store_op("監査ログの取得")
    def get_audit_events(self, target_id: str | None = None) -> list[AuditEvent]:
        if target_id is None:
            rows = self._conn.execute("SELECT * FROM audit_log ORDER BY rowid").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM audit_log WHERE target_id = ? ORDER BY rowid",
                (target_id,),
            ).fetchall()
        return [
            AuditEvent(
                log_id=row["log_id"],
                event_type=row["event_type"],
                target_id=row["target_id"],
                actor=row["actor"],
                detail=json.loads(row["detail"]) if row["detail"] else None,
                created_at=_dt(row["created_at"]),
            )
            for row in rows
        ]

    # ---- row ↔ ドメイン型変換(規約3) ----

    def _latest_candidate(self, fact_id: str) -> Revision:
        row = self._conn.execute(
            """
            SELECT * FROM fact_revisions
            WHERE fact_id = ? ORDER BY rowid DESC LIMIT 1
            """,
            (fact_id,),
        ).fetchone()
        if row is None or row["status"] != CANDIDATE:
            raise StoreError(f"candidate が見つかりません: {fact_id}")
        return self._row_to_revision(row)

    def _insert_revision(
        self,
        fact_id: str,
        content: str,
        status: str,
        reason: str | None = None,
        raw_text_id: str | None = None,
        revises_fact_id: str | None = None,
        topic_tag: str | None = None,
        tags: list[str] | None = None,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO fact_revisions (
                revision_id, fact_id, raw_text_id, revises_fact_id, content,
                status, reason, topic_tag, tags, valid_from, valid_until, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id(),
                fact_id,
                raw_text_id,
                revises_fact_id,
                content,
                status,
                reason,
                topic_tag,
                _dump_tags(tags or []),
                _iso(valid_from),
                _iso(valid_until),
                _iso(utc_now()),
            ),
        )

    def _insert_canonical(self, fact: Fact) -> None:
        self._conn.execute(
            """
            INSERT INTO canonical_facts (
                id, content, topic_tag, status, valid_from, valid_until,
                tags, raw_text_id, created_at, updated_at
            ) VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
            """,
            (
                fact.id,
                fact.content,
                fact.topic_tag,
                _iso(fact.valid_from),
                _iso(fact.valid_until),
                _dump_tags(fact.tags),
                fact.raw_text_id,
                _iso(fact.created_at),
                _iso(fact.updated_at),
            ),
        )

    def _insert_audit(self, event: AuditEvent) -> None:
        self._conn.execute(
            """
            INSERT INTO audit_log (log_id, event_type, target_id, actor, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.log_id,
                event.event_type,
                event.target_id,
                event.actor,
                json.dumps(event.detail, ensure_ascii=False) if event.detail else None,
                _iso(event.created_at),
            ),
        )

    @staticmethod
    def _row_to_fact(row: sqlite3.Row) -> Fact:
        return Fact(
            id=row["id"],
            content=row["content"],
            status=row["status"],
            valid_from=_dt(row["valid_from"]),
            valid_until=_dt(row["valid_until"]),
            topic_tag=row["topic_tag"],
            tags=_load_tags(row["tags"]),
            raw_text_id=row["raw_text_id"],
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
        )

    @staticmethod
    def _row_to_revision(row: sqlite3.Row) -> Revision:
        return Revision(
            revision_id=row["revision_id"],
            fact_id=row["fact_id"],
            content=row["content"],
            status=row["status"],
            reason=row["reason"],
            topic_tag=row["topic_tag"],
            tags=_load_tags(row["tags"]),
            raw_text_id=row["raw_text_id"],
            revises_fact_id=row["revises_fact_id"],
            valid_from=_dt(row["valid_from"]),
            valid_until=_dt(row["valid_until"]),
            created_at=_dt(row["created_at"]),
        )
