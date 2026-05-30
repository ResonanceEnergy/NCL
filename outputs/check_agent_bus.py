"""Wave 14W-E smoke test — exercise the dispatcher with a no-brain call."""

import asyncio
import sys


sys.path.insert(0, "/Users/natrix/dev/NCL")

from runtime.agent_bus import RequestKind, intel_request, list_recent_requests


async def main():
    print("=== Direct kind lookup ===")
    for k in RequestKind:
        print(f"  {k.value}")

    print("\n=== Fire bad-kind request (no handler) ===")
    r = await intel_request(kind="not.a.real.kind", caller="smoke_test")
    print(f"  ok={r.ok} error={r.error[:80]}")

    print("\n=== Fire kind without brain (should fail gracefully) ===")
    r = await intel_request(
        kind=RequestKind.MEMORY_FUSED_SEARCH,
        caller="smoke_test",
        query="capital rotation late cycle",
        max_results=3,
    )
    print(f"  ok={r.ok} elapsed_ms={r.elapsed_ms} error={r.error[:120]}")

    print("\n=== Fire scheduler.queue (calendar-only path, no brain needed) ===")
    r = await intel_request(
        kind=RequestKind.SCHEDULER_QUEUE,
        caller="smoke_test",
        action="smoke_test_action",
        run_at="2026-05-29T12:00:00Z",
        payload={"source": "smoke_test"},
    )
    print(f"  ok={r.ok} elapsed_ms={r.elapsed_ms}")
    if r.ok:
        print(f"  result={r.result}")
    else:
        print(f"  error={r.error[:120]}")

    print("\n=== Trail tail (last 5) ===")
    for row in list_recent_requests(limit=5):
        print(
            f"  - {row.get('kind')} caller={row.get('caller')} "
            f"ok={row.get('ok')} elapsed={row.get('elapsed_ms')}ms"
        )


asyncio.run(main())
