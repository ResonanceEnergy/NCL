"""NCL notification utilities — centralized alert dispatch with rate limit + dedup."""

from .alert_dispatch import (
    AlertDispatcher,
    enqueue_alert,
    get_alert_dispatcher,
)


__all__ = ["AlertDispatcher", "get_alert_dispatcher", "enqueue_alert"]
