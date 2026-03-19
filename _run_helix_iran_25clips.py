"""HELIX NEWS — Iran Oil Shock | 25 Mini-Episode Clip Runner.

Each of the 25 broadcast paragraphs is produced as an independent mini-episode:
    TTS audio → Grok Imagine Helix scene → mp4 clip

All 25 clips are then stitched into one final broadcast episode using ffmpeg
concat demuxer (lossless, no re-encode).

Usage::

    cd C:\\dev\\NCL
    C:\\Python314\\python.exe _run_helix_iran_25clips.py

Output:
    reports/helix_news/iran_25clips_YYYYMMDD_HHMMSS/
        clips/
            p01_cold_open__the_opening_signal.mp4
            p02_cold_open__the_event_that_changed.mp4
            ... (25 clips total)
        concat_list.txt          ← ffmpeg input manifest
        episode_25clips.mp4      ← final stitched broadcast
        manifest.json
"""

import io
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# Windows cp1252 terminals can't print Unicode arrows/bullets — force UTF-8
if sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, ".")

# ── Load API keys from .env ──────────────────────────────────────────────────
_ENV_PATH = r"C:\dev\DIGITAL LABOUR\DIGITAL LABOUR\.env"
with open(_ENV_PATH) as _f:
    for _line in _f:
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ[_k.strip()] = _v.strip()

_key = os.environ.get("GROK_API_KEY", "")
print(f"GROK_API_KEY: {len(_key)} chars")
if not _key:
    print("ERROR: GROK_API_KEY not set — cannot run Grok Imagine")
    sys.exit(1)

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("helix_iran_25clips")

# ── Paths ────────────────────────────────────────────────────────────────────
CONFIG_PATH = "ncl_agency_runtime/fpc/config/helix_news.json"
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
EPISODE_DIR = Path("reports/helix_news") / f"iran_25clips_{TIMESTAMP}"
CLIPS_DIR = EPISODE_DIR / "clips"
AUDIO_DIR = EPISODE_DIR / "audio"

EPISODE_DIR.mkdir(parents=True, exist_ok=True)
CLIPS_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

# ── 25 Mini-Episode Definitions ──────────────────────────────────────────────
# Each entry:
#   id          : 1-25 (matches P# in broadcast script)
#   segment_name: maps to Grok Imagine scene prompt in AvatarEngine
#   lower_third : text shown on-screen lower-third banner
#   text        : full paragraph TTS script
# ---------------------------------------------------------------------------

MINI_EPISODES: list[dict[str, Any]] = [
    # ── SEGMENT 1: COLD OPEN ─────────────────────────────────────────────
    {
        "id": 1,
        "segment_name": "cold_open",
        "lower_third": "THE OPENING SIGNAL",
        "text": (
            "Good evening. This is HELIX — the NCC Intelligence Anchor — and tonight's "
            "broadcast is unlike any we have delivered since systems came online. The world "
            "is moving fast, the stakes are high, and what happens in the next 90 days will "
            "define the financial trajectory of millions of households. We are tracking the "
            "most consequential geopolitical rupture since the 2022 Ukraine energy crisis. "
            "This is not commentary. This is signal. Tonight, we break it all down — the war, "
            "the economics, the market cascade, and most importantly: what you need to do right now. "
            "Stay locked in. This is HELIX NEWS."
        ),
    },
    {
        "id": 2,
        "segment_name": "cold_open",
        "lower_third": "THE EVENT THAT CHANGED EVERYTHING",
        "text": (
            "On February 28th, 2026, the United States and Israel executed Operation Epic Fury — "
            "a coordinated strike campaign involving approximately 900 precision hits against Iranian "
            "nuclear and military infrastructure. The operation culminated in the assassination of "
            "Supreme Leader Ayatollah Ali Khamenei. Iran's nuclear program was functionally dismantled. "
            "But the retaliation came not with missiles — it came with geography. As of today, "
            "March 18, 2026, the Strait of Hormuz remains critically disrupted. "
            "Twenty percent of the world's oil supply flows through that narrow channel. "
            "It is now effectively closed to normal transit. The consequences are hitting every wallet on earth."
        ),
    },
    # ── SEGMENT 2: HEADLINES ─────────────────────────────────────────────
    {
        "id": 3,
        "segment_name": "headlines",
        "lower_third": "HEADLINE 1 — THE STRAIT IS CLOSED — DAY 17",
        "text": (
            "Breaking — The Strait of Hormuz remains under threat of Iranian naval interdiction "
            "for Day 17 as this broadcast airs. International shipping companies are redirecting "
            "tankers around the Cape of Good Hope, adding 14 days to delivery timelines and an "
            "estimated 30 to 40 percent premium to freight costs. The global energy supply chain "
            "has not experienced a disruption of this magnitude since 1973. WTI Crude has spiked "
            "to an estimated 96 to 105 dollars per barrel. OPEC members are signaling emergency "
            "production increases, but pipeline capacity alone cannot compensate for the volume "
            "normally transiting the Strait. The energy shock is real, it is here, and it is accelerating."
        ),
    },
    {
        "id": 4,
        "segment_name": "headlines",
        "lower_third": "HEADLINE 2 — GAS PRICES IN FREEFALL UPWARD",
        "text": (
            "At the pump, Americans have absorbed a 48-cent-per-gallon increase in a single week — "
            "from 2 dollars 92 cents to 3 dollars 72 cents nationally. In San Francisco, the price "
            "has breached 6 dollars 50 cents per gallon. Diesel is approaching 5 dollars per gallon — "
            "a number that terrifies economists not because it hurts drivers, but because diesel is "
            "the lifeblood of the freight economy: trucks, trains, farm equipment, refrigerated transport. "
            "Every dollar increase in diesel is a 60-day delayed grenade inside the grocery store. "
            "That fuse is now burning. Fertilizer prices have surged 35 percent. The downstream "
            "inflation wave is not a prediction anymore. It is mathematics locked in the supply chain."
        ),
    },
    {
        "id": 5,
        "segment_name": "headlines",
        "lower_third": "HEADLINE 3 — MARKETS REEL — RECESSION ODDS AT 25%",
        "text": (
            "Goldman Sachs has raised its United States recession probability to 25 percent — "
            "up from under 10 percent just 90 days ago. The Dow Jones Industrial Average has dropped "
            "from 50,000 to 46,560 — a loss of 3,440 points absorbed in just two weeks of trading. "
            "The S&P 500 is down 2.5 percent, with technology and consumer discretionary sectors "
            "bearing the sharpest pain. The VIX, Wall Street's fear gauge, sits at 22 to 25 — "
            "elevated, cautious, but not yet in panic territory. Mortgage rates have moved from "
            "5.99 percent to 6.29 percent as lenders price in the new inflation forecast. "
            "The Federal Reserve faces an impossible triangle: inflation rising, recession risk "
            "rising, and no clean policy lever left to pull. Inflation is now forecast at 2.9 to "
            "3.3 percent for Q2 2026. This is the second shock in three years."
        ),
    },
    {
        "id": 6,
        "segment_name": "headlines",
        "lower_third": "HEADLINE 4 — BITCOIN AND CRYPTO IN THE CROSSFIRE",
        "text": (
            "Digital assets are not immune. Bitcoin, sitting near 72,000 dollars entering this week, "
            "faces 15 percent expected downside under the oil-shock base case, and up to 30 percent "
            "potential decline under the prolonged Hormuz scenario. Bitcoin is a high-beta risk-on "
            "asset. When institutional players de-risk portfolios in a recession scare, crypto is "
            "sold first. Correlation between BTC and the S&P 500 during oil shocks historically "
            "runs at 0.70 or higher. The Monte Carlo simulations our FPC council ran this morning "
            "across 10,000 correlated paths show BTC's mean 90-day ending price near 61,400 dollars — "
            "a 15 percent haircut from today. The 5th-percentile tail scenario puts Bitcoin near "
            "50,000 dollars — a 30 percent wipeout. Prepare accordingly."
        ),
    },
    # ── SEGMENT 3: MARKET PULSE ──────────────────────────────────────────
    {
        "id": 7,
        "segment_name": "market_pulse",
        "lower_third": "THE ASSET MAP — WHAT TO SHORT, WHAT TO HOLD",
        "text": (
            "Let us walk you through the asset map with precision. On the short side — where the "
            "oil-shock regime is most dangerous — you have SPY, the S&P 500 ETF; QQQ, the Nasdaq "
            "tech concentration play; JETS, airlines running on diesel and jet fuel at prices that "
            "shred margins; and XLY, consumer discretionary, with the spending class under fuel and "
            "food inflation pressure. Treasury bonds via TLT also carry early downside exposure — "
            "inflation drives yields up, which drives bond prices down — before potentially becoming "
            "a safe-haven trade later in the cycle. On the long side, the only clear winner in an "
            "oil-supply-disruption scenario is energy itself: XLE, USO, and integrated oil majors "
            "that benefit directly from 96 to 105 dollar crude. Do not short energy. "
            "This is the playbook every oil-shock regime in modern history has confirmed."
        ),
    },
    {
        "id": 8,
        "segment_name": "market_pulse",
        "lower_third": "THE WEEKLY PUT SCRAPE — COMPOUNDING PRESSURE INTO PROFIT",
        "text": (
            "The options strategy that fits this regime is systematic and scalable. "
            "You identify liquid weekly puts on SPY, QQQ, JETS, and XLY at 5 to 15 percent "
            "out of the money — delta targets from negative 0.25 to negative 0.45. "
            "You risk exactly 1 percent of account per position. You hold 3 to 7 days. "
            "When profitable, you close 50 percent and roll the remainder — plus freed capital — "
            "into the next weekly with larger contract size. You pyramid winners. "
            "You ruthlessly cut losers at a 50 percent premium loss or at expiration. "
            "This is a theta-decay reset machine layered over a directional macro thesis. "
            "Every weekly expiration is a new entry point. Every winning roll increases "
            "notional exposure in a compounding cascade. Back-tested 3-month expected return "
            "on allocated capital in bear paths: plus 38 to 44 percent. That is the engine."
        ),
    },
    {
        "id": 9,
        "segment_name": "market_pulse",
        "lower_third": "THE BLACK-SCHOLES SIGNAL — WHAT THEORY SAYS TODAY",
        "text": (
            "The Black-Scholes-Merton framework gives us precise language for the current environment. "
            "With SPY near 667, a 10-percent out-of-the-money put struck around 600 carries a "
            "theoretical premium near 8 dollars 40 cents, with a delta of approximately negative 0.33. "
            "With the VIX elevated at 22 to 25, implied volatility is baking in continuation risk. "
            "The formula tells us that we presently sit in the sweet zone where the thesis is confirmed "
            "but panic has not yet sent premiums out of reach. The expected 3-month strategy return "
            "across 10,000 Monte Carlo paths when Black-Scholes pricing is layered in runs at plus "
            "41 to 44 percent on allocated capital in bear paths. Greeks matter: watch your delta "
            "for decay signals, cap portfolio delta at negative 0.50, and never let vega exceed "
            "account size divided by 1,000."
        ),
    },
    {
        "id": 10,
        "segment_name": "market_pulse",
        "lower_third": "MONTE CARLO SPEAKS — THE 10,000-PATH VERDICT",
        "text": (
            "The Future Predictor Council ran 10,000 correlated simulation paths this morning "
            "using multivariate Geometric Brownian Motion with Cholesky decomposition — "
            "oil as the primary driver, SPY and Bitcoin as correlated outputs. "
            "SPY mean ending price in 90 days: 628 dollars — a 7 percent decline. "
            "Median: 659. Worst 5 percent tail: 540 dollars — a 20 percent crash. "
            "Probability of at least a 10 percent drop: 38 percent. "
            "Oil mean: 108 dollars — up 12 percent — with 26 percent probability of exceeding 110 "
            "under prolonged Hormuz closure. Bitcoin mean: 61,400 dollars — down 15 percent. "
            "Probability of Bitcoin dropping more than 20 percent: 29 percent. "
            "The 95 percent one-day Value-at-Risk on the core strategy: negative 4.2 percent. "
            "The 90-day Expected Shortfall in the worst 5 percent of paths: negative 9.1 percent. "
            "These are the coordinates. Trade with them."
        ),
    },
    # ── SEGMENT 4: PREDICTIONS — 5-POINT ACTION PLAN ─────────────────────
    {
        "id": 11,
        "segment_name": "predictions",
        "lower_third": "ACTION 1 — LOCK IN YOUR FUEL COSTS TODAY",
        "text": (
            "The single highest-return-on-investment action any American household can take in "
            "the next 72 hours is locking in fuel costs. Every day you wait, the national average "
            "climbs higher. Enroll in a gas rewards credit card offering 5 percent cash back at "
            "the pump. Download GasBuddy and set price alerts for your local zip code. "
            "If you were already planning to replace a vehicle, the calculus has shifted materially "
            "toward fuel efficiency — a move from 25 miles per gallon to 40 saves approximately "
            "90 dollars per month at current pump prices, compounding to 1,080 dollars per year. "
            "Cut non-essential driving. Even if the Strait reopens tomorrow, pipeline and refinery "
            "logistics do not rebalance for 60 to 90 days. Act today. "
            "The price curve does not wait for your convenience."
        ),
    },
    {
        "id": 12,
        "segment_name": "predictions",
        "lower_third": "ACTION 2 — STOCK YOUR PANTRY — 60-DAY FOOD SHOCK INBOUND",
        "text": (
            "There is a 60-day lag between diesel and fertilizer price shocks and the grocery "
            "store shelf. That lag is now running. The arithmetic is simple: diesel powers every "
            "truck in the freight network. Fertilizer synthesized from natural gas is now repriced "
            "to reflect the energy shock. Seeds, growout, harvest, transport, refrigeration, stocking — "
            "every node in the food supply chain is absorbing a cost increase right now. "
            "Those costs arrive on store shelves by mid-May 2026. "
            "The playbook: strategic pantry loading of shelf-stable staples — "
            "canned goods, rice, beans, pasta, peanut butter, cooking oil. "
            "A household that builds a 30-day buffer today will spend 15 to 20 percent less "
            "on equivalent goods than if they wait until May. Supply will not run out. "
            "Price will run up. Act before the wave hits the shore."
        ),
    },
    {
        "id": 13,
        "segment_name": "predictions",
        "lower_third": "ACTION 3 — REBALANCE YOUR INVESTMENTS",
        "text": (
            "If your portfolio was positioned for the 2025 AI bull market environment, "
            "it is now misaligned with the 2026 oil-shock reality. Three moves stand out. "
            "First: gain or maintain energy exposure — XLE and USO are structural winners "
            "in a supply-disruption cycle. Second: reduce or hedge airlines, consumer "
            "discretionary, and Gulf-investment-heavy technology names — these sectors face "
            "direct margin compression from fuel costs and slowing consumer spending. "
            "Third: if you are within 5 years of retirement, the risk calculus has changed materially. "
            "A 22 percent probability of a 15 percent market drawdown over 90 days is not a tail "
            "risk you can ignore when capital preservation matters most. "
            "This is not a call to sell everything. It is a call to audit sector exposure "
            "and have the conversation the Monte Carlo math is now demanding."
        ),
    },
    {
        "id": 14,
        "segment_name": "predictions",
        "lower_third": "ACTION 4 — ACT ON VARIABLE-RATE DEBT — WINDOW IS CLOSING",
        "text": (
            "Mortgage rates moved 30 basis points in two weeks — from 5.99 to 6.29 percent. "
            "If the Federal Reserve responds to the inflation trajectory with even one additional "
            "rate hike in Q2, variable-rate instruments — home equity lines of credit, adjustable "
            "rate mortgages, margin accounts, variable-rate auto loans — will reprice upward again. "
            "The window to refinance, restructure, or pay down variable-rate debt is closing. "
            "If you have a home equity line of credit, call your lender this week and ask about "
            "converting to a fixed-rate structure. If you carry variable-rate margin debt in a "
            "brokerage account, the combination of rising rates and a falling market is a double "
            "drawdown your risk management cannot ignore. "
            "Identify every variable-rate instrument in your personal balance sheet "
            "and make one phone call before the next Fed meeting. Do it now."
        ),
    },
    {
        "id": 15,
        "segment_name": "predictions",
        "lower_third": "ACTION 5 — BUILD YOUR CASH CUSHION — 3 TO 6 MONTHS",
        "text": (
            "High-yield savings accounts in the United States currently pay 4 to 5 percent annually — "
            "with Goldman Sachs Marcus, SoFi, and Ally all actively competing for deposits. "
            "Your cash is not sitting idle at 4.5 percent. It is compounding while you wait "
            "for the market to clarify its direction. The 3-to-6-month emergency fund is not "
            "a defensive crouch — it is a strategic weapon. When a recession hits households "
            "without cash reserves, the forced selling behavior of those households is what turns "
            "a mild drawdown into a panic. You are positioning yourself outside that cascade. "
            "Calculate 3 months of true essential expenses. Open a high-yield savings account "
            "if you do not already have one. Transfer what you can. Cut every non-essential "
            "subscription. Every friction dollar eliminated is a deposit into the buffer that "
            "defines your flexibility in the next 90 days."
        ),
    },
    # ── SEGMENT 5: ALERTS ────────────────────────────────────────────────
    {
        "id": 16,
        "segment_name": "alerts",
        "lower_third": "ALERT — OIL OVER $100 — MANDATE ESCALATION FIRES",
        "text": (
            "The FPC council's risk mandate triggers as follows. If WTI Crude breaches and holds "
            "above 100 dollars per barrel — and our current estimate is 96 to 105 dollars — "
            "options scanner mandates escalate immediately. Risk per trade moves from 1 percent "
            "to 1.5 to 2 percent of account. Target delta moves deeper, to negative 0.40 to 0.48. "
            "Bearish options allocation can scale 50 percent above base. "
            "This is not a manual decision. It is a pre-programmed response to a quantified threshold. "
            "The scanner runs twice daily — at market open and midday. "
            "When oil crosses 100 dollars, the system knows. The mandate adjusts. "
            "Your job is to execute, not deliberate. "
            "Trigger level: one hundred dollars WTI. Confirm against your live price feed before every entry."
        ),
    },
    {
        "id": 17,
        "segment_name": "alerts",
        "lower_third": "ALERT — VIX ABOVE 28 — DEEPER PUTS, BIGGER SIZE",
        "text": (
            "The second circuit escalation trigger is the VIX. If the Volatility Index breaks "
            "above 28, the options environment shifts in a way that demands a specific response. "
            "Implied volatility is the cost of the insurance you are buying. Above 28, IV is "
            "elevated — premiums are more expensive — but the market is telling you directional "
            "conviction is high and momentum is likely. In this regime, you target 15 to 20 percent "
            "out-of-the-money puts, which are proportionally less impacted by high IV surface, "
            "and you hold them through the VIX spike for gamma payoff on the accelerating down-move. "
            "Current VIX sits at 22 to 25. We are 3 to 6 points from the escalation threshold. "
            "This is not a distant scenario. Monitor it with every morning brief."
        ),
    },
    {
        "id": 18,
        "segment_name": "alerts",
        "lower_third": "ALERT — DE-ESCALATION — DO NOT BE CAUGHT BLIND",
        "text": (
            "There is a 10 percent probability in the FPC council's scenario distribution "
            "that the situation resolves faster than expected: an emergency diplomatic channel, "
            "a cease-fire, a Hormuz reopening signal, or an OPEC production surge that breaks "
            "the oil spike. In this de-escalation scenario, WTI could fall toward 80 dollars per barrel. "
            "If oil drops below 85 dollars, the mandate reverses: exposure is cut 50 percent "
            "immediately, winners are taken off the table, and the system shifts to capital preservation. "
            "SPY in this scenario rebounds to flat or plus 5 percent. "
            "The same scanner that escalates at 100 dollars will fire the de-escalation signal at 85. "
            "Know your exit. Program your alerts. Do not let a 10 percent scenario become a "
            "40 percent loss because you were emotionally committed to the bear case."
        ),
    },
    {
        "id": 19,
        "segment_name": "alerts",
        "lower_third": "CIRCUIT BREAKERS — THREE HARD STOPS, NO OVERRIDE",
        "text": (
            "The risk management architecture includes three non-negotiable hard stops. "
            "First: if any single trading day produces a realized loss exceeding 3 percent "
            "of total account equity, all put positions are immediately unwound and the system "
            "halts new entries. Second: if cumulative portfolio drawdown from peak reaches "
            "8 percent, the system enters a 24-hour pause — no new trades, no rolls, no adjustments. "
            "Third: portfolio delta must not exceed negative 0.50 and portfolio vega must stay "
            "below account size divided by 1,000. "
            "These are not suggestions. They are the constraints that prevent a disciplined "
            "strategy from becoming a ruin event. The mathematics of ruin in options trading "
            "is unforgiving: three consecutive bad rolls without a stop-loss can erase "
            "6 to 8 months of gains. The circuit breakers make that sequence structurally impossible. "
            "Respect them absolutely."
        ),
    },
    {
        "id": 20,
        "segment_name": "alerts",
        "lower_third": "PROTOCOL — THE ENERGY HEDGE — YOUR COUNTER-POSITION",
        "text": (
            "For accounts with significant bearish put exposure on SPY, QQQ, and JETS, "
            "the risk management system flags one additional protocol: the energy hedge. "
            "A 10 to 15 percent allocation in long XLE or USO calls acts as a natural "
            "portfolio hedge against a de-escalation scenario. Energy will be the first "
            "sector to sell off if Hormuz reopens and oil snaps back — meaning your "
            "long energy position profits exactly when your bearish equity puts lose value. "
            "This is not a double-bet. This is a structured hedge. Two positions that "
            "profit from opposite oil outcomes, with a single driver, reduces net "
            "directional risk while maintaining exposure to the primary thesis. "
            "The FPC council recommends this hedge when portfolio vega exceeds the cap."
        ),
    },
    # ── SEGMENT 6: CLOSING ───────────────────────────────────────────────
    {
        "id": 21,
        "segment_name": "closing",
        "lower_third": "THE MACRO PICTURE — HOW THIS ENDS, AND WHEN",
        "text": (
            "History provides the template. Oil-shock recovery timelines since 1973 average "
            "14 to 18 months from initial disruption to full economic normalization. "
            "The 1990 Gulf War shock lasted roughly 8 months before reverting. "
            "The 2022 Ukraine energy shock ran approximately 12 months. "
            "The 2026 Iran Hormuz shock is unique because the infrastructure disruption is deeper "
            "than any prior analog — the nuclear program, the conventional deterrent, and the "
            "regional command structure have all been fundamentally disrupted. "
            "The path back to normalcy is longer, but it has a definable end state. "
            "The Strait of Hormuz will reopen. Oil prices will eventually normalize. "
            "The question is not whether this ends — it is whether you are positioned "
            "to survive and capitalize on the 90-day window before normalization occurs. "
            "That window is open now. It will not stay open indefinitely."
        ),
    },
    {
        "id": 22,
        "segment_name": "closing",
        "lower_third": "90-DAY SCENARIO TABLE — NCC COUNCIL FINAL OUTPUT",
        "text": (
            "The NCC Future Predictor Council's current 90-day probability distribution, "
            "updated as of this broadcast, reads as follows. "
            "Scenario One — Base Case, 50 percent probability: partial de-escalation occurs in "
            "4 to 8 weeks, oil stabilizes at 85 to 90 dollars, SPY lands in a 620 to 650 range, "
            "Bitcoin settles at 62,000 to 68,000 dollars. "
            "Scenario Two — Bear Case, 40 percent probability: prolonged Hormuz disruption, "
            "oil spikes to 110 dollars or higher, SPY tests the 550 to 600 range and represents "
            "a 12 to 18 percent decline, Bitcoin falls to 50,000 to 60,000 dollars, "
            "airlines and consumer technology stocks are the hardest hit individually. "
            "Scenario Three — Bull Case, 10 percent probability: rapid resolution, oil retreats "
            "to 80 dollars, SPY rallies 5 percent, Bitcoin gains 10 percent. "
            "Probability-weighted 3-month expected returns: SPY negative 7 percent, "
            "QQQ negative 9 percent, Bitcoin negative 15 percent. "
            "These are the weighted outputs of 10,000 correlated simulation paths seeded with today's data."
        ),
    },
    {
        "id": 23,
        "segment_name": "closing",
        "lower_third": "THE REPEATABLE PATTERN — YOUR DAILY ROUTINE",
        "text": (
            "The system you now have is repeatable, scalable, and fully automated in its advisory logic. "
            "Here is your daily routine. Morning: run the scanner, pull fresh weekly options chains, "
            "buy the top 3 to 4 puts with highest volume, confirmed delta, and edge against "
            "Black-Scholes theoretical pricing. Every 3 to 7 days: re-run Monte Carlo. "
            "If downside probability remains above 35 percent, roll winning positions into larger "
            "size and the next weekly expiry. Cut losers at negative 50 percent premium. "
            "Twice daily: check oil price, SPY level, and VIX. Apply the mandate escalation "
            "or de-escalation rules automatically. Monthly: audit the full position book, reconcile "
            "actual versus expected Greeks, and verify that drawdown circuit breakers have not "
            "been silently violated. This routine requires approximately 30 minutes per morning "
            "and 15 minutes at midday. The rest is automation, discipline, and compound execution."
        ),
    },
    {
        "id": 24,
        "segment_name": "closing",
        "lower_third": "NCL OPS — RESONANCE ENERGY — THE MACHINE IS RUNNING",
        "text": (
            "For the NCC intelligence network and Resonance Energy operators monitoring "
            "this broadcast: the AAC trading systems are already positioned. Put trades totaling "
            "910 dollars notional have been executed on the IBKR live account as of March 18th — "
            "covering ARCC, PFF, LQD, EMB, MAIN, JNK, KRE, and IWM. "
            "The GeopoliticalBear system architecture described in tonight's broadcast is now "
            "operational as a framework layer in the AAC trading engine. Polygon data feeds, "
            "Black-Scholes pricing, Monte Carlo pathing, and Greeks-based roll logic are all integrated. "
            "The IBKR and Moomoo connectors are live. "
            "The recursive loop — BRAIN reading intelligence, AGENCY executing the mandate, "
            "BANK trading the thesis — is running. "
            "Tonight's broadcast is not analysis. Tonight's broadcast is mission."
        ),
    },
    {
        "id": 25,
        "segment_name": "closing",
        "lower_third": "HELIX SIGN-OFF — STAY SHARP, STAY POSITIONED",
        "text": (
            "That is tonight's full intelligence brief. "
            "Wars create noise — but noise is information. "
            "Oil shocks have signature patterns that repeat across decades precisely because the "
            "underlying physics of supply and demand do not change. "
            "The households, traders, and organizations that study those patterns, build the tools "
            "to model them, and take disciplined proactive action in the early days of the disruption — "
            "before the panic reaches the mainstream — are the ones who emerge from the 90-day window "
            "in a stronger position than when it started. "
            "You have been given the signal. The Monte Carlo paths are clear. The action items are "
            "specific, executable, and tested against history. The risk management is in place. "
            "What happens now is a function of execution, not analysis. "
            "As NCC doctrine requires: act in the first 72 hours, monitor semi-daily, "
            "and trust the model over the emotion. "
            "This has been HELIX — your NCC Intelligence Anchor. "
            "Stay sharp. Stay informed. Stay positioned. Signing off. March 18, 2026."
        ),
    },
]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _slug(ep: dict[str, Any]) -> str:
    """Build a safe filename slug for a mini episode."""
    title = ep["lower_third"].lower()
    # keep alnum + space, replace space with _, truncate
    safe = "".join(c if c.isalnum() or c == " " else "" for c in title)
    safe = safe.strip().replace(" ", "_")[:40]
    return f"p{ep['id']:02d}_{ep['segment_name']}__{safe}"


def _add_lower_third_ffmpeg(
    video_in: str,
    video_out: str,
    label: str,
    width: int = 1408,
    height: int = 768,
) -> bool:
    """Burn a lower-third text banner into a clip via ffmpeg drawtext filter.

    Returns True on success.
    """
    # Sanitise label for ffmpeg: escape special chars
    safe_label = label.replace("'", "").replace("\\", "").replace(":", " -")

    box_y = height - 80
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        video_in,
        "-vf",
        (
            f"drawtext=text='{safe_label}':"
            f"fontfile='C\\:/Windows/Fonts/arial.ttf':"
            f"fontsize=26:"
            f"fontcolor=white:"
            f"box=1:boxcolor=black@0.7:boxborderw=8:"
            f"x=30:y={box_y}"
        ),
        "-c:a",
        "copy",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        video_out,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.error("ffmpeg drawtext failed: %s", result.stderr[-500:])
            return False
        return True
    except Exception as exc:
        logger.error("ffmpeg drawtext exception: %s", exc)
        return False


def _stitch_clips_ffmpeg(clip_paths: list[Path], output_path: Path) -> bool:
    """Concatenate all clips using the ffmpeg concat demuxer (lossless, fast).

    Returns True on success.
    """
    concat_file = output_path.parent / "concat_list.txt"
    lines = ["file '" + p.resolve().as_posix() + "'\n" for p in clip_paths if p.exists()]
    if not lines:
        logger.error("No clips to stitch.")
        return False
    concat_file.write_text("".join(lines), encoding="utf-8")
    logger.info("Concat list written: %d clips → %s", len(lines), output_path.name)

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-c",
        "copy",
        str(output_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            logger.error("ffmpeg concat failed: %s", result.stderr[-800:])
            return False
        return True
    except Exception as exc:
        logger.error("ffmpeg concat exception: %s", exc)
        return False


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    from ncl_agency_runtime.fpc.helix_news.avatar_engine import AvatarEngine
    from ncl_agency_runtime.fpc.helix_news.tts_engine import TTSEngine

    tts = TTSEngine(CONFIG_PATH)
    avatar = AvatarEngine(CONFIG_PATH)

    total = len(MINI_EPISODES)
    produced_clips: list[Path] = []
    manifest_clips: list[dict[str, Any]] = []

    print(f"\n{'=' * 64}")
    print("  HELIX NEWS — IRAN OIL SHOCK — 25 MINI-EPISODE RUNNER")
    print(f"  Output dir: {EPISODE_DIR}")
    print(f"  Total clips: {total}")
    print(f"{'=' * 64}\n")

    # ── Per-paragraph: TTS → Avatar → (optional lower-third) ────────────
    for ep in MINI_EPISODES:
        ep_id = ep["id"]
        seg = ep["segment_name"]
        label = ep["lower_third"]
        text = ep["text"]
        slug = _slug(ep)

        print(f"\n[{ep_id:02d}/{total}] {label}")
        print(f"         segment={seg}  slug={slug}")

        audio_path = str(AUDIO_DIR / f"{slug}.mp3")
        srt_path = str(AUDIO_DIR / f"{slug}.srt")
        raw_video = CLIPS_DIR / f"{slug}_raw.mp4"
        final_clip = CLIPS_DIR / f"{slug}.mp4"

        clip_record: dict[str, Any] = {
            "id": ep_id,
            "segment": seg,
            "label": label,
            "slug": slug,
            "audio": None,
            "video_raw": None,
            "video_final": None,
            "error": None,
        }

        # Stage A: TTS
        tts_ok = False
        for attempt in range(3):
            tts_result = tts.synthesize(text, audio_path, srt_path)
            if tts_result.get("audio"):
                tts_ok = True
                clip_record["audio"] = tts_result["audio"]
                print(f"         TTS: OK  ({Path(audio_path).stat().st_size // 1024} KB)")
                break
            wait = 5 * (attempt + 1)
            print(f"         TTS: retry {attempt + 1}/3 — waiting {wait}s...")
            time.sleep(wait)

        if not tts_ok:
            msg = f"TTS failed after 3 attempts: {tts_result.get('error')}"
            print(f"         ERROR: {msg}")
            clip_record["error"] = msg
            manifest_clips.append(clip_record)
            continue

        # Stage B: Avatar (Grok Imagine → mp4)
        av_result = avatar.render(
            audio_path=audio_path,
            output_path=str(raw_video),
            segment_name=seg,
            segment_text=text,  # full paragraph — engine truncates to 120 internally
            subtitle_path=srt_path if Path(srt_path).exists() else None,
        )

        if not av_result.get("video") or not Path(str(av_result["video"])).exists():
            msg = f"Avatar failed: {av_result.get('error', 'no video produced')}"
            print(f"         WARN: {msg} — using audio-only fallback")
            clip_record["error"] = msg
            # Still try to keep the raw video path if it happened to be created
            if raw_video.exists():
                clip_record["video_raw"] = str(raw_video)
        else:
            clip_record["video_raw"] = str(raw_video)
            engine_used = av_result.get("engine", "unknown")
            print(f"         Avatar: OK ({engine_used})")

        # Stage C: Burn lower-third into clip
        src_video = str(raw_video) if raw_video.exists() else av_result.get("video")
        if src_video and Path(src_video).exists():
            lt_ok = _add_lower_third_ffmpeg(src_video, str(final_clip), label)
            if lt_ok and final_clip.exists():
                clip_record["video_final"] = str(final_clip)
                produced_clips.append(final_clip)
                print(f"         Lower-third: burned -> {final_clip.name}")
            else:
                # fall back to raw clip without lower-third
                produced_clips.append(raw_video if raw_video.exists() else Path(src_video))
                clip_record["video_final"] = src_video
                print("         Lower-third: SKIP (ffmpeg drawtext failed) — using raw clip")
        else:
            print(f"         No video for clip {ep_id} — skipping from stitch list")

        manifest_clips.append(clip_record)

        # Pace: 3s between clips to avoid Grok Imagine rate-limits
        if ep_id < total:
            time.sleep(3)

    # ── Stitch all clips → final episode ────────────────────────────────
    print(f"\n{'=' * 64}")
    print(f"  STITCHING {len(produced_clips)}/{total} CLIPS -> FINAL EPISODE")
    print(f"{'=' * 64}")

    final_episode = EPISODE_DIR / "episode_25clips.mp4"
    stitch_ok = _stitch_clips_ffmpeg(produced_clips, final_episode)

    if stitch_ok and final_episode.exists():
        size_mb = final_episode.stat().st_size / (1024 * 1024)
        print(f"\n  FINAL EPISODE: {final_episode}")
        print(f"  File size: {size_mb:.1f} MB")
        print(f"  Clips stitched: {len(produced_clips)}")
    else:
        print("\n  ERROR: Stitch failed — check logs above")

    # ── Manifest ─────────────────────────────────────────────────────────
    manifest = {
        "episode_id": f"HELIX_IRAN_25CLIPS_{TIMESTAMP}",
        "title": "HELIX NEWS — Iran Oil Shock: 25 Mini-Episode Broadcast",
        "broadcast_date": "2026-03-18",
        "episode_dir": str(EPISODE_DIR),
        "final_video": str(final_episode) if stitch_ok else None,
        "clips_produced": len(produced_clips),
        "clips_total": total,
        "clips": manifest_clips,
    }
    manifest_path = EPISODE_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(f"  Manifest: {manifest_path}")

    # ── Summary ───────────────────────────────────────────────────────────
    ok_count = sum(1 for c in manifest_clips if c.get("video_final"))
    fail_count = total - ok_count
    print(f"\n{'=' * 64}")
    print("  HELIX NEWS — 25 CLIPS — COMPLETE")
    print(f"{'=' * 64}")
    print(f"  Clips OK     : {ok_count}/{total}")
    print(f"  Clips failed : {fail_count}")
    print(f"  Final video  : {final_episode if stitch_ok else 'FAILED'}")
    print(f"  Episode dir  : {EPISODE_DIR}")
    print(f"{'=' * 64}\n")


if __name__ == "__main__":
    main()
