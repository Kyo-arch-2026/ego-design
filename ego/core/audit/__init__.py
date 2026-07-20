"""Audit Log(F-1): 全操作の記録。Store Port 経由。

追記専用。本モジュールにもストアにも、既存ログを更新・削除する口は存在しない。
"""

from ego.core.domain import AuditEvent, new_id, utc_now
from ego.ports.store_port import StorePort


class AuditLog:
    def __init__(self, store: StorePort):
        self._store = store

    def record(
        self,
        event_type: str,
        target_id: str,
        actor: str,
        detail: dict | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            log_id=new_id(),
            event_type=event_type,
            target_id=target_id,
            actor=actor,
            detail=detail,
            created_at=utc_now(),
        )
        self._store.append_audit(event)
        return event

    def events(self, target_id: str | None = None) -> list[AuditEvent]:
        return self._store.get_audit_events(target_id)
