"""council_pack.store — relocated from council_runner (W5-06, 2026-05-23).

Persistence layer for Council Runner records. Stores runs to disk
(JSONL + individual JSON files) and provides query interface.

The pack now owns this storage path: every council surface that wants
durable session storage with the legacy ``CouncilRunRecord`` shape
goes through ``CouncilRunStore`` (mounted at
``runtime.api.routes._council_store``).

Originally lived at ``runtime/council_runner/store.py``.
"""

from __future__ import annotations  # noqa: I001

import asyncio
import json
import logging
from datetime import datetime, timezone  # noqa: F401
from pathlib import Path
from typing import Optional  # noqa: F401

from .models import CouncilRunRecord

log = logging.getLogger("ncl.council_pack.store")


class CouncilRunStore:
    """Persistence and query interface for council runs."""

    def __init__(self, data_dir: str = "./data"):
        """Initialize store with data directory."""
        self.data_dir = Path(data_dir)
        self.store_dir = self.data_dir / "council_runner"
        self.store_dir.mkdir(parents=True, exist_ok=True)

        self.runs_file = self.store_dir / "runs.jsonl"
        self.runs_detail_dir = self.store_dir / "runs"
        self.runs_detail_dir.mkdir(exist_ok=True)
        # Serialize concurrent save_run() calls so the JSONL index cannot
        # interleave partial lines and the per-run JSON write is atomic.
        self._write_lock: asyncio.Lock = asyncio.Lock()

    async def save_run(self, record: CouncilRunRecord) -> None:
        """
        Save a council run.

        Appends to runs.jsonl (lightweight index, lock-serialized) and writes
        the full record to runs/{run_id}.json via temp-file + atomic rename.
        """
        record_dict = record.model_dump(mode="json")
        line = json.dumps(record_dict, default=str) + "\n"
        run_detail_file = self.runs_detail_dir / f"{record.run_id}.json"
        tmp_detail = run_detail_file.with_suffix(".json.tmp")

        async with self._write_lock:
            # JSONL append (single open, single write — atomic per POSIX for <PIPE_BUF)
            with open(self.runs_file, "a") as f:
                f.write(line)
                f.flush()
            # Atomic JSON write: temp file + os.replace()
            with open(tmp_detail, "w") as f:
                json.dump(record_dict, f, indent=2, default=str)
                f.flush()
            tmp_detail.replace(run_detail_file)

        log.info(f"Saved run {record.run_id} to store")

    async def get_run(self, run_id: str) -> CouncilRunRecord:
        """Retrieve a saved run by ID."""
        run_file = self.runs_detail_dir / f"{run_id}.json"

        if not run_file.exists():
            raise FileNotFoundError(f"Run {run_id} not found")

        with open(run_file) as f:
            data = json.load(f)

        return CouncilRunRecord(**data)

    async def list_runs(
        self, limit: int = 50, offset: int = 0
    ) -> list[CouncilRunRecord]:
        """List saved runs with pagination."""
        runs = []

        if not self.runs_file.exists():
            return runs

        with open(self.runs_file) as f:
            for i, line in enumerate(f):
                if i < offset:
                    continue
                if len(runs) >= limit:
                    break

                try:
                    data = json.loads(line)
                    runs.append(CouncilRunRecord(**data))
                except (json.JSONDecodeError, ValueError) as e:
                    log.warning(f"Could not parse run from JSONL: {e}")

        return runs

    async def search_runs(
        self, topic_query: str, limit: int = 20
    ) -> list[CouncilRunRecord]:
        """Simple text search on topic and prompt."""
        matches = []
        query_lower = topic_query.lower()

        if not self.runs_file.exists():
            return matches

        with open(self.runs_file) as f:
            for line in f:
                if len(matches) >= limit:
                    break

                try:
                    data = json.loads(line)
                    if (
                        query_lower in data.get("topic", "").lower()
                        or query_lower in data.get("prompt", "").lower()
                    ):
                        matches.append(CouncilRunRecord(**data))
                except (json.JSONDecodeError, ValueError):
                    pass

        return matches

    async def get_stats(self) -> dict:
        """Get aggregate statistics about stored runs."""
        if not self.runs_file.exists():
            return {
                "total_runs": 0,
                "avg_consensus_score": 0,
                "avg_duration_ms": 0,
                "risk_flag_distribution": {},
            }

        total_runs = 0
        consensus_scores = []
        durations = []
        risk_flag_counts = {}

        with open(self.runs_file) as f:
            for line in f:
                try:
                    data = json.loads(line)
                    total_runs += 1

                    consensus = data.get("consensus", {})
                    if consensus:
                        consensus_scores.append(consensus.get("consensus_score", 50))

                    durations.append(data.get("total_duration_ms", 0))

                    risk_flags = consensus.get("risk_flags", [])
                    for flag in risk_flags:
                        risk_flag_counts[flag] = risk_flag_counts.get(flag, 0) + 1

                except (json.JSONDecodeError, ValueError):
                    pass

        avg_consensus = (
            sum(consensus_scores) / len(consensus_scores)
            if consensus_scores
            else 0
        )
        avg_duration = sum(durations) / len(durations) if durations else 0

        return {
            "total_runs": total_runs,
            "avg_consensus_score": round(avg_consensus, 1),
            "avg_duration_ms": round(avg_duration, 0),
            "risk_flag_distribution": risk_flag_counts,
        }

    async def get_provenance(self, run_id: str) -> dict:
        """Get full provenance chain for a run."""
        try:
            record = await self.get_run(run_id)
            return {
                "run_id": record.run_id,
                "topic": record.topic,
                "timestamp": record.timestamp,
                "agents": [
                    {
                        "role": output.role.value,
                        "model": output.model_used,
                        "confidence": output.confidence,
                        "duration_ms": output.duration_ms,
                        "token_count": output.token_count,
                    }
                    for output in record.agent_outputs
                ],
                "consensus_score": (
                    record.consensus.consensus_score
                    if record.consensus
                    else None
                ),
                "provenance": record.provenance,
                "replay_seed": record.replay_seed,
            }
        except FileNotFoundError:
            return {}
