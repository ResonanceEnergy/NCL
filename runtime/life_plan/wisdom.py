"""Daily Wisdom rotation.

Reads a static-ish corpus (data/life_plan/wisdom.jsonl), serves one per
day deterministically (date-keyed hash mod count), updates seen state
in wisdom-state.json so the iOS surface can show "shown N times" /
"last shown YYYY-MM-DD" without re-rolling on every fetch.

Categories: stoic, operational, financial, personal, creative.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import DailyWisdom

log = logging.getLogger("ncl.life_plan.wisdom")


def _root() -> Path:
    base = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
    return base / "data" / "life_plan"


def _wisdom_file() -> Path:
    return _root() / "wisdom.jsonl"


def _state_file() -> Path:
    return _root() / "wisdom-state.json"


# ── Seed corpus (50 entries across 5 categories) ─────────────────────────

_DEFAULT_WISDOM: list[dict] = [
    # ── STOIC (15) ────────────────────────────────────────────────────
    {"id": "stoic-001", "category": "stoic", "text": "First tell yourself what kind of person you want to be, then do what you have to do.", "source": "Epictetus, Discourses 3.23"},
    {"id": "stoic-002", "category": "stoic", "text": "You have power over your mind, not outside events. Realize this, and you will find strength.", "source": "Marcus Aurelius, Meditations"},
    {"id": "stoic-003", "category": "stoic", "text": "Waste no more time arguing what a good man should be. Be one.", "source": "Marcus Aurelius, Meditations 10.16"},
    {"id": "stoic-004", "category": "stoic", "text": "We suffer more often in imagination than in reality.", "source": "Seneca, Letters 13.4"},
    {"id": "stoic-005", "category": "stoic", "text": "The obstacle is the way.", "source": "Marcus Aurelius (paraphrased) / Ryan Holiday"},
    {"id": "stoic-006", "category": "stoic", "text": "If it is not right, do not do it. If it is not true, do not say it.", "source": "Marcus Aurelius, Meditations 12.17"},
    {"id": "stoic-007", "category": "stoic", "text": "Every new beginning comes from some other beginning's end.", "source": "Seneca"},
    {"id": "stoic-008", "category": "stoic", "text": "Difficulties strengthen the mind, as labor does the body.", "source": "Seneca"},
    {"id": "stoic-009", "category": "stoic", "text": "Don't explain your philosophy. Embody it.", "source": "Epictetus"},
    {"id": "stoic-010", "category": "stoic", "text": "Begin at once to live, and count each separate day as a separate life.", "source": "Seneca, Letters 101.10"},
    {"id": "stoic-011", "category": "stoic", "text": "It is not death that a man should fear, but he should fear never beginning to live.", "source": "Marcus Aurelius"},
    {"id": "stoic-012", "category": "stoic", "text": "Choose not to be harmed and you won't feel harmed. Don't feel harmed and you haven't been.", "source": "Marcus Aurelius, Meditations 4.7"},
    {"id": "stoic-013", "category": "stoic", "text": "Wealth consists not in having great possessions, but in having few wants.", "source": "Epictetus"},
    {"id": "stoic-014", "category": "stoic", "text": "Luck is what happens when preparation meets opportunity.", "source": "Seneca"},
    {"id": "stoic-015", "category": "stoic", "text": "He who fears death will never do anything worthy of a living man.", "source": "Seneca"},

    # ── OPERATIONAL / SYSTEMS (10) ────────────────────────────────────
    {"id": "ops-001", "category": "operational", "text": "Make it work, make it right, make it fast — in that order.", "source": "Kent Beck"},
    {"id": "ops-002", "category": "operational", "text": "Slow is smooth. Smooth is fast.", "source": "Navy SEALs"},
    {"id": "ops-003", "category": "operational", "text": "If you can't measure it, you can't improve it.", "source": "Peter Drucker (commonly attributed)"},
    {"id": "ops-004", "category": "operational", "text": "Plans are worthless, but planning is everything.", "source": "Dwight D. Eisenhower"},
    {"id": "ops-005", "category": "operational", "text": "Premature optimization is the root of all evil.", "source": "Donald Knuth"},
    {"id": "ops-006", "category": "operational", "text": "Don't break the chain.", "source": "Jerry Seinfeld (daily-discipline maxim)"},
    {"id": "ops-007", "category": "operational", "text": "The best way to predict the future is to invent it.", "source": "Alan Kay"},
    {"id": "ops-008", "category": "operational", "text": "Discipline equals freedom.", "source": "Jocko Willink"},
    {"id": "ops-009", "category": "operational", "text": "Compound interest is the eighth wonder of the world. He who understands it, earns it; he who doesn't, pays it.", "source": "Albert Einstein (attributed)"},
    {"id": "ops-010", "category": "operational", "text": "Two things you should never wait for: a good idea and clean code.", "source": "Anon, dev folklore"},

    # ── FINANCIAL / TRADING (10) ──────────────────────────────────────
    {"id": "fin-001", "category": "financial", "text": "The first rule is never lose money. The second rule is never forget rule number one.", "source": "Warren Buffett"},
    {"id": "fin-002", "category": "financial", "text": "Risk comes from not knowing what you're doing.", "source": "Warren Buffett"},
    {"id": "fin-003", "category": "financial", "text": "Be fearful when others are greedy, and greedy when others are fearful.", "source": "Warren Buffett"},
    {"id": "fin-004", "category": "financial", "text": "Markets can remain irrational longer than you can remain solvent.", "source": "John Maynard Keynes"},
    {"id": "fin-005", "category": "financial", "text": "The four most dangerous words in investing are: 'This time it's different.'", "source": "Sir John Templeton"},
    {"id": "fin-006", "category": "financial", "text": "Plan the trade and trade the plan.", "source": "Trading folklore"},
    {"id": "fin-007", "category": "financial", "text": "The trend is your friend until the end when it bends.", "source": "Ed Seykota"},
    {"id": "fin-008", "category": "financial", "text": "It is not the strongest of the species that survives, but the one most adaptable to change.", "source": "Charles Darwin (commonly applied to markets)"},
    {"id": "fin-009", "category": "financial", "text": "Time in the market beats timing the market.", "source": "Investment maxim"},
    {"id": "fin-010", "category": "financial", "text": "The stock market is a device for transferring money from the impatient to the patient.", "source": "Warren Buffett"},

    # ── PERSONAL / HEALTH (10) ────────────────────────────────────────
    {"id": "personal-001", "category": "personal", "text": "Take care of your body. It's the only place you have to live.", "source": "Jim Rohn"},
    {"id": "personal-002", "category": "personal", "text": "What you do every day matters more than what you do once in a while.", "source": "Gretchen Rubin"},
    {"id": "personal-003", "category": "personal", "text": "The cave you fear to enter holds the treasure you seek.", "source": "Joseph Campbell"},
    {"id": "personal-004", "category": "personal", "text": "You are the average of the five people you spend the most time with.", "source": "Jim Rohn"},
    {"id": "personal-005", "category": "personal", "text": "The best time to plant a tree was 20 years ago. The second best time is now.", "source": "Chinese proverb"},
    {"id": "personal-006", "category": "personal", "text": "You don't have to see the whole staircase, just take the first step.", "source": "Martin Luther King Jr."},
    {"id": "personal-007", "category": "personal", "text": "Comparison is the thief of joy.", "source": "Theodore Roosevelt"},
    {"id": "personal-008", "category": "personal", "text": "Sleep is the best meditation.", "source": "Dalai Lama"},
    {"id": "personal-009", "category": "personal", "text": "Health is not valued till sickness comes.", "source": "Thomas Fuller"},
    {"id": "personal-010", "category": "personal", "text": "If you don't make time for your wellness, you'll be forced to make time for your illness.", "source": "Anon (modern)"},

    # ── CREATIVE / BUILD (5) ──────────────────────────────────────────
    {"id": "creative-001", "category": "creative", "text": "Done is better than perfect.", "source": "Sheryl Sandberg / startup folklore"},
    {"id": "creative-002", "category": "creative", "text": "The way to get started is to quit talking and begin doing.", "source": "Walt Disney"},
    {"id": "creative-003", "category": "creative", "text": "Creativity is intelligence having fun.", "source": "Albert Einstein (attributed)"},
    {"id": "creative-004", "category": "creative", "text": "If you're not embarrassed by the first version of your product, you've launched too late.", "source": "Reid Hoffman"},
    {"id": "creative-005", "category": "creative", "text": "The goal isn't to be perfect by the end. The goal is to be better today.", "source": "Simon Sinek"},
]


def seed_default_wisdom() -> int:
    """Write the default corpus if wisdom.jsonl is empty/missing. Idempotent.

    Returns the number of entries written (0 if file already had data).

    Wave 14AL (2026-05-30): also appends ~180 public-domain Stoic +
    CBT + growth entries from stoic_corpus.extend_wisdom_corpus() on
    every call. That helper is idempotent — it only appends ids not
    already present.
    """
    f = _wisdom_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    if not (f.exists() and f.stat().st_size > 0):
        with f.open("w", encoding="utf-8") as fh:
            for w in _DEFAULT_WISDOM:
                fh.write(json.dumps(w) + "\n")
        written = len(_DEFAULT_WISDOM)
        log.info("[WISDOM] seeded %d default wisdom entries", written)

    # Wave 14AL — Stoic + CBT + growth extension (idempotent append).
    try:
        from .stoic_corpus import extend_wisdom_corpus

        added = extend_wisdom_corpus(f)
        if added:
            log.info("[WISDOM] Wave 14AL appended %d extension entries", added)
        written += added
    except Exception as e:  # noqa: BLE001
        log.debug("[WISDOM] extension append failed: %s", e)

    # Wave 14AT — second extension pass (~280 more entries).
    try:
        from .wisdom_corpus_v2 import extend_wisdom_corpus as _v2

        added = _v2(f)
        if added:
            log.info("[WISDOM] Wave 14AT appended %d more entries", added)
        written += added
    except Exception as e:  # noqa: BLE001
        log.debug("[WISDOM] v2 extension append failed: %s", e)

    return written


# ── Rotator ──────────────────────────────────────────────────────────────


class WisdomRotator:
    """Date-keyed deterministic wisdom rotation."""

    def __init__(self):
        seed_default_wisdom()

    def _load_corpus(self) -> list[DailyWisdom]:
        out: list[DailyWisdom] = []
        f = _wisdom_file()
        if not f.exists():
            return out
        with f.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(DailyWisdom.model_validate_json(line))
                except Exception:
                    continue
        return out

    def _load_state(self) -> dict:
        f = _state_file()
        if not f.exists():
            return {}
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_state(self, state: dict) -> None:
        _state_file().write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")

    def today(self, date_str: Optional[str] = None, category: Optional[str] = None) -> Optional[DailyWisdom]:
        """Return today's wisdom. Deterministic per date (and optional category)."""
        date_str = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        corpus = self._load_corpus()
        if category:
            corpus = [w for w in corpus if w.category == category]
        if not corpus:
            return None
        # Deterministic index — same wisdom across reloads on same day
        key = f"{date_str}|{category or 'all'}"
        idx = int(hashlib.sha256(key.encode()).hexdigest(), 16) % len(corpus)
        wisdom = corpus[idx]

        # Update state (seen count + last_seen)
        state = self._load_state()
        s = state.setdefault(wisdom.id, {"seen_count": 0, "last_seen": None})
        # Only bump if today's date isn't already recorded
        if s.get("last_seen") != date_str:
            s["seen_count"] = int(s.get("seen_count", 0)) + 1
            s["last_seen"] = date_str
            self._save_state(state)

        wisdom.seen_count = s["seen_count"]
        try:
            wisdom.last_seen = datetime.fromisoformat(s["last_seen"])
        except Exception:
            pass
        return wisdom

    def list_category(self, category: str) -> list[DailyWisdom]:
        corpus = self._load_corpus()
        return [w for w in corpus if w.category == category]

    def list_categories(self) -> list[str]:
        corpus = self._load_corpus()
        return sorted({w.category for w in corpus})

    def random(self) -> Optional[DailyWisdom]:
        corpus = self._load_corpus()
        return random.choice(corpus) if corpus else None
