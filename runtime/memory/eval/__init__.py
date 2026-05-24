"""Memory evaluation harness (Loop 2)."""

from __future__ import annotations

from typing import Any

from .runner import MemoryEvalRunner


async def run_weekly_eval(brain: Any) -> dict:
    """Convenience entrypoint — run the eval against a live ``NCLBrain`` instance.

    Returns the eval result dict with an additional ``"baseline_diff"`` key.
    Safe to call directly from notebooks or one-off scripts.
    """
    memory_store = getattr(brain, "memory_store", None)
    working_context = getattr(brain, "working_context", None) or getattr(
        brain, "context_window", None
    )
    if memory_store is None:
        raise RuntimeError("brain has no memory_store attribute")

    runner = MemoryEvalRunner(memory_store=memory_store, working_context=working_context)
    result = await runner.run_eval()
    result["baseline_diff"] = await runner.compare_to_baseline(current=result)
    return result


__all__ = ["MemoryEvalRunner", "run_weekly_eval"]
