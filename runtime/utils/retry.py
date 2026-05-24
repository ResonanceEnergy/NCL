"""Shared async retry utility for NCL runtime."""

import asyncio
import logging


async def retry_async(
    coro_func,
    *args,
    max_retries: int = 3,
    backoff: float = 1.0,
    logger: logging.Logger | None = None,
    **kwargs,
):
    """
    Call an async function with exponential backoff retry.

    Attempts: 1s → 2s → 4s delays (with backoff=1.0).

    Args:
        coro_func: Async callable to invoke.
        *args: Positional arguments forwarded to coro_func.
        max_retries: Total attempts before re-raising the last exception.
        backoff: Base delay in seconds; doubles each attempt (1s/2s/4s).
        logger: Optional logger for per-attempt warnings.
        **kwargs: Keyword arguments forwarded to coro_func.

    Returns:
        The return value of coro_func on success.

    Raises:
        The last exception if all attempts are exhausted.
    """
    for attempt in range(max_retries):
        try:
            return await coro_func(*args, **kwargs)
        except Exception as e:
            if logger:
                logger.warning(
                    "Attempt %d/%d failed: %s",
                    attempt + 1,
                    max_retries,
                    e,
                )
            if attempt < max_retries - 1:
                await asyncio.sleep(backoff * (2**attempt))
            else:
                raise
