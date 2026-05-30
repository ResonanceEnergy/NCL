"""Wave 14BL smoke test — situational + BERTopic theme overlap."""
import os
os.environ["NCL_CROSS_REF_BERTOPIC_ENABLED"] = "true"
import sys
sys.path.insert(0, "/Users/natrix/dev/NCL")

from runtime.awarebot.agent import compute_situational_relevance, compute_composite_score
from runtime.cross_reference import _extract_themes
print("env flag:", os.environ.get("NCL_CROSS_REF_BERTOPIC_ENABLED"))
print("reddit pump text -> themes:", _extract_themes("Bitcoin pump short squeeze coming, float about to explode", source="reddit"))

# diagnostic
from runtime.cross_reference.bertopic_themes import load_source_stratified_bertopic, classify_themes_for_source
by_src = load_source_stratified_bertopic()
print("loaded sources:", list(by_src.keys()))
print("classify_for_source(reddit):", classify_themes_for_source("Bitcoin pump short squeeze coming, float about to explode", "reddit", by_src))

probes = [
    {
        "name": "Reddit crypto bitcoin w/ active 'crypto bitcoin market' theme",
        "text": "Bitcoin market dump today, crypto in freefall after Fed",
        "source": "reddit",
        "themes_active": {"bt:crypto bitcoin market"},
        "morning_quiz_focus": "watch crypto pumps today",
    },
    {
        "name": "Options flow AAPL w/ AAPL in journal",
        "text": "AAPL 200 calls heavy flow today",
        "source": "options_flow",
        "tickers_in_journal_today": {"AAPL"},
        "themes_active": set(),
    },
    {
        "name": "News CPI w/ no overlap",
        "text": "AMZN AWS revenue grew 15%",
        "source": "news",
        "themes_active": {"bt:prediction lt gt"},
    },
    {
        "name": "Baseline — empty context",
        "text": "Bitcoin pump short squeeze",
        "source": "reddit",
    },
]

for p in probes:
    score = compute_situational_relevance(
        p["text"],
        tickers_in_journal_today=p.get("tickers_in_journal_today"),
        tickers_with_calendar_event_today=p.get("tickers_with_calendar_event_today"),
        morning_quiz_focus=p.get("morning_quiz_focus"),
        themes_active=p.get("themes_active"),
        source=p.get("source"),
    )
    composite_with = compute_composite_score(0.5, 0.5, 0.5, 0.5, 0.5, situational=score)
    composite_without = compute_composite_score(0.5, 0.5, 0.5, 0.5, 0.5, situational=0.0)
    print(f"{p['name']!r}")
    print(f"  situational={score:.3f}  composite_with={composite_with:.4f}  composite_without={composite_without:.4f}  delta={composite_with-composite_without:+.4f}")
