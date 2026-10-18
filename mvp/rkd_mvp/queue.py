from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from .models import EventEnvelope, TenantContext
from .store import AccessDenied, InMemoryStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class QueueWorker:
    """Reference Outbox/Inbox consumer with retry and dead-letter behavior."""

    def __init__(self, store: InMemoryStore) -> None:
        self.store = store

    def drain_outbox(self, context: TenantContext, handler: Callable[[EventEnvelope], None],
                     max_messages: int = 100, max_attempts: int = 3) -> dict[str, int]:
        self.store.require_project(context)
        counts = {"published": 0, "retryable": 0, "dead_letter": 0}
        for event in self.store.outbox:
            if counts["published"] + counts["retryable"] + counts["dead_letter"] >= max_messages:
                break
            if (event.context.organization_id, event.context.project_id) != (
                context.organization_id, context.project_id
            ):
                continue
            meta = self.store.outbox_status.get(event.event_id)
            if not meta or meta["status"] not in {"pending", "retryable"}:
                continue
            meta["attempts"] += 1
            try:
                handler(event)
            except Exception as error:
                meta["last_error"] = str(error)
                if meta["attempts"] >= max_attempts:
                    meta["status"] = "dead-letter"
                    self.store.dead_letters.append({
                        "event_id": event.event_id,
                        "organization_id": context.organization_id,
                        "project_id": context.project_id,
                        "attempts": meta["attempts"],
                        "error": str(error),
                    })
                    counts["dead_letter"] += 1
                else:
                    meta["status"] = "retryable"
                    counts["retryable"] += 1
            else:
                meta["status"] = "published"
                meta["published_at"] = _now()
                counts["published"] += 1
            self.store.append_audit(
                context,
                f"outbox.{meta['status']}",
                "OutboxMessage",
                event.event_id,
                meta["status"],
                {"attempts": meta["attempts"], "last_error": meta.get("last_error", "")},
            )
            self.store.persist()
        return counts

    def consume_inbox(self, context: TenantContext, event: EventEnvelope,
                      consumer_name: str, handler: Callable[[EventEnvelope], None]) -> str:
        if event.context.organization_id != context.organization_id or event.context.project_id != context.project_id:
            raise AccessDenied("resource not found")
        key = (context.organization_id, context.project_id, event.event_id, consumer_name)
        state = self.store.inbox_status.get(key, {}).get("status")
        if key in self.store.inbox or state == "processed":
            return "duplicate"
        if state == "processing":
            return "in-flight"
        self.store.inbox_status[key] = {"status": "processing", "attempts": 1}
        self.store.persist()
        try:
            handler(event)
        except Exception as error:
            self.store.inbox_status[key] = {"status": "retryable", "attempts": 1, "last_error": str(error)}
            self.store.persist()
            raise
        self.store.inbox.add(key)
        self.store.inbox_status[key] = {"status": "processed", "attempts": 1}
        self.store.persist()
        return "processed"
