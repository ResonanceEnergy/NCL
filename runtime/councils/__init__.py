"""
NARTIX Intelligence Councils — YouTube + X (Twitter)

Two parallel intelligence gathering and analysis pipelines:
- YouTube Council: scrape channels → download audio → transcribe → analyze → report
- X Council: full sweep (accounts + keywords + trending) → analyze → report

Output flows into NCL/intelligence-scan/ for the Awarebot-FPC pipeline.

Usage:
    python3 -m runtime.councils.runner --both        # Run both councils
    python3 -m runtime.councils.runner --youtube      # YouTube only
    python3 -m runtime.councils.runner --x            # X only
"""
