"""Quick check of signal scorer and edge-tts voices."""
import sys

sys.path.insert(0, ".")

# Check signal scorer
print("=== Signal Scorer ===")
try:
    from ncl_agency_runtime.fpc.signal_scorer import SignalScorer
    s = SignalScorer()
    ranked = s.rank_predictions()
    print(f"Ranked: {len(ranked)} predictions")
    for i, r in enumerate(ranked[:5]):
        topic = r.get("topic", "?")[:60]
        grade = r.get("grade", "?")
        score = r.get("impact_score", 0)
        print(f"  {i+1}. {topic}  grade={grade}  score={score:.2f}")
except Exception as e:
    print(f"Error: {e}")

# Check edge-tts voices
print("\n=== Female English Voices ===")
try:
    import asyncio

    import edge_tts
    voices = asyncio.run(edge_tts.list_voices())
    female_en = [v for v in voices if v["Gender"] == "Female" and v["Locale"].startswith("en-")]
    for v in female_en:
        print(f"  {v['ShortName']:40s}  {v.get('StyleList', [])}")
except Exception as e:
    print(f"Error: {e}")
