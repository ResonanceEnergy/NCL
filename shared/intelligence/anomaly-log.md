# NCL Anomaly Log — Unexpected Pattern Registry

**Updated by**: Awarebot-FPC Scanner + Manual NCL entries
**Purpose**: Track anomalies that don't fit normal signal categories
**Authority**: NCL-only write; downstream pillars informed via mandates

---

## Anomaly Schema

```yaml
anomaly_id: ANO-YYYYMMDD-NNN
detected_at: ISO-8601
source: scanner | manual | feedback | convergence
category: data | behavioral | systemic | external
severity: critical | high | medium | low
description: <what was detected>
expected_behavior: <what should have happened>
actual_behavior: <what actually happened>
hypothesis: <best guess at root cause>
resolution: pending | investigating | resolved | dismissed
resolution_notes: <if resolved/dismissed>
related_signals: [SIG-xxx, SIG-yyy]
related_mandates: [MANDATE-xxx]
```

---

## Active Anomalies

### ANO-20260404-001
```yaml
anomaly_id: ANO-20260404-001
detected_at: 2026-04-04T08:00:00Z
source: manual
category: systemic
severity: high
description: "NCL Brain stuck offline — Errno 48 port conflict + pump watcher 403 auth mismatch"
expected_behavior: "Brain binds :8800, watcher forwards pumps with matching token"
actual_behavior: "Stale process held port; token loaded before .env parsed"
hypothesis: "Race condition in STRIKE_TOKEN init + unclean shutdown leaving socket in TIME_WAIT"
resolution: resolved
resolution_notes: "Fixed token loading order (config before env), added graceful SIGTERM handler, boot script now kills port explicitly"
related_signals: []
related_mandates: [MANDATE-2026-008]
```

### ANO-20260404-002
```yaml
anomaly_id: ANO-20260404-002
detected_at: 2026-04-04T09:00:00Z
source: manual
category: systemic
severity: medium
description: "14 pump files stuck in mandate-generation/input/ — zero processed"
expected_behavior: "Pump watcher forwards to brain within 5s of file landing"
actual_behavior: "All POSTs rejected 403, files accumulated over 24h"
hypothesis: "Consequence of ANO-20260404-001 (brain offline + token mismatch)"
resolution: resolved
resolution_notes: "Root cause fixed in ANO-001. Pumps will process on next brain restart."
related_signals: []
related_mandates: [MANDATE-2026-008]
```

---

## Anomaly Categories

| Category | Description | Typical Source |
|----------|-------------|----------------|
| Data | Unexpected data patterns, schema violations, corrupt files | Scanner, feedback |
| Behavioral | Services acting outside expected parameters | Monitoring, logs |
| Systemic | Infrastructure failures, cascade effects | Boot scripts, health checks |
| External | External service changes, API deprecations, market shocks | Scanner, manual |

---

## Escalation Rules

- **Critical**: Auto-spawn council session, notify NATRIX immediately
- **High**: Flag in next mandate review cycle, include in feedback synthesis
- **Medium**: Log and monitor, include in weekly review
- **Low**: Log only, review monthly

---

## Archive

Resolved anomalies older than 30 days are moved to `/NCL/shared/intelligence/archive/anomalies/` with quarterly rollups for pattern analysis.
## 2026-05-15 17:55:51Z — 2 anomalies
- **[market_data/test_anom/bullish]** (93%) SPY whale call sweep $50M
- **[news/test_anom/bearish]** (91%) Major macro event: rate cut

## 2026-05-15 21:10:22Z — 24 anomalies
- **[polymarket/sports/bearish]** (90%) Will Uzbekistan win the 2026 FIFA World Cup?
- **[polymarket/politics/bearish]** (90%) Will Austria win Eurovision 2026?
- **[polymarket/sports/bearish]** (90%) Will Liverpool FC win on 2026-05-17?
- **[polymarket/sports/bearish]** (90%) Counter-Strike: FURIA vs Team Falcons (BO3) - PGL Astana Playoffs
- **[polymarket/politics/bearish]** (90%) US x Iran permanent peace deal by April 22, 2026?
- **[polymarket/sports/bullish]** (90%) Aston Villa FC vs. Liverpool FC: O/U 2.5
- **[polymarket/macro/bearish]** (90%) Will the Fed decrease interest rates by 50+ bps after the June 2026 meeting?
- **[polymarket/politics/bearish]** (90%) Will Byron Donalds win the 2028 Republican presidential nomination?
- **[polymarket/politics/bearish]** (90%) Will LeBron James win the 2028 US Presidential Election?
- **[polymarket/politics/bearish]** (90%) Will Tarcisio de Freitas win the 2026 Brazilian presidential election?
- **[polymarket/crypto/bearish]** (90%) Will Bitcoin reach $150,000 in May?
- **[polymarket/sports/bearish]** (90%) Will Scottie Scheffler win the 2026 PGA Championship?
- **[polymarket/politics/bearish]** (90%) Will Oprah Winfrey win the 2028 Democratic presidential nomination?
- **[polymarket/markets/bearish]** (90%) Will WTI Crude Oil (WTI) hit (HIGH) $150 in May?
- **[options_flow/dark_pool/bullish]** (95%) SNDK dark pool: $254,500,111 across 1 prints
- **[options_flow/dark_pool/bullish]** (95%) AMD dark pool: $93,169,681 across 1 prints
- **[options_flow/dark_pool/bullish]** (95%) MA dark pool: $169,510,600 across 1 prints
- **[options_flow/dark_pool/bullish]** (95%) NVDA dark pool: $477,899,214 across 1 prints
- **[options_flow/dark_pool/bullish]** (95%) EA dark pool: $62,526,848 across 1 prints
- **[options_flow/dark_pool/bearish]** (95%) BE dark pool: $106,692,480 across 1 prints
- **[options_flow/dark_pool/bullish]** (95%) INTC dark pool: $174,178,296 across 1 prints
- **[options_flow/dark_pool/bullish]** (91%) DIA dark pool: $51,015,679 across 1 prints
- **[options_flow/dark_pool/bullish]** (93%) QQQ dark pool: $53,900,657 across 1 prints
- **[options_flow/dark_pool/bullish]** (95%) SPY dark pool: $180,752,936 across 1 prints

## 2026-05-15 21:26:40Z — 21 anomalies
- **[polymarket/sports/bearish]** (90%) Will Uzbekistan win the 2026 FIFA World Cup?
- **[polymarket/politics/bearish]** (90%) Will Austria win Eurovision 2026?
- **[polymarket/sports/bearish]** (90%) Will Liverpool FC win on 2026-05-17?
- **[polymarket/sports/bearish]** (90%) Counter-Strike: FURIA vs Team Falcons (BO3) - PGL Astana Playoffs
- **[polymarket/politics/bearish]** (90%) US x Iran permanent peace deal by April 22, 2026?
- **[polymarket/sports/bullish]** (90%) Aston Villa FC vs. Liverpool FC: O/U 2.5
- **[polymarket/macro/bearish]** (90%) Will the Fed decrease interest rates by 50+ bps after the June 2026 meeting?
- **[polymarket/politics/bearish]** (90%) Will LeBron James win the 2028 US Presidential Election?
- **[polymarket/politics/bearish]** (90%) Will Byron Donalds win the 2028 Republican presidential nomination?
- **[polymarket/politics/bearish]** (90%) Will Tarcisio de Freitas win the 2026 Brazilian presidential election?
- **[polymarket/crypto/bearish]** (90%) Will Bitcoin reach $150,000 in May?
- **[polymarket/sports/bearish]** (90%) Will Scottie Scheffler win the 2026 PGA Championship?
- **[polymarket/politics/bearish]** (90%) Will Oprah Winfrey win the 2028 Democratic presidential nomination?
- **[polymarket/markets/bearish]** (90%) Will WTI Crude Oil (WTI) hit (HIGH) $150 in May?
- **[options_flow/dark_pool/bullish]** (95%) NEM dark pool: $116,083,464 across 2 prints
- **[options_flow/dark_pool/bullish]** (95%) ABBV dark pool: $92,781,990 across 1 prints
- **[options_flow/dark_pool/bearish]** (95%) LYB dark pool: $101,668,770 across 1 prints
- **[options_flow/dark_pool/bullish]** (95%) WAB dark pool: $134,879,290 across 1 prints
- **[options_flow/dark_pool/bullish]** (95%) TEL dark pool: $126,840,024 across 1 prints
- **[options_flow/dark_pool/bullish]** (95%) QQQ dark pool: $60,000,291 across 1 prints
- **[reddit/gme_intel/bearish]** (95%) GME vs. GMEBAY - The funding problem, the dilution math, and what could happen when RC makes a new proposal

## 2026-05-15 21:52:52Z — 16 anomalies
- **[polymarket/sports/bearish]** (90%) Will Uzbekistan win the 2026 FIFA World Cup?
- **[polymarket/politics/bearish]** (90%) Will Austria win Eurovision 2026?
- **[polymarket/sports/bearish]** (90%) Will Liverpool FC win on 2026-05-17?
- **[polymarket/sports/bearish]** (90%) Counter-Strike: FURIA vs Team Falcons (BO3) - PGL Astana Playoffs
- **[polymarket/politics/bearish]** (90%) US x Iran permanent peace deal by April 22, 2026?
- **[polymarket/sports/bullish]** (90%) Aston Villa FC vs. Liverpool FC: O/U 2.5
- **[polymarket/macro/bearish]** (90%) Will the Fed decrease interest rates by 50+ bps after the June 2026 meeting?
- **[polymarket/politics/bearish]** (90%) Will LeBron James win the 2028 US Presidential Election?
- **[polymarket/politics/bearish]** (90%) Will Byron Donalds win the 2028 Republican presidential nomination?
- **[polymarket/politics/bearish]** (90%) Will Tarcisio de Freitas win the 2026 Brazilian presidential election?
- **[polymarket/crypto/bearish]** (90%) Will Bitcoin reach $150,000 in May?
- **[polymarket/sports/bearish]** (90%) Will Scottie Scheffler win the 2026 PGA Championship?
- **[polymarket/politics/bearish]** (90%) Will Elon Musk post 0-19 tweets from May 12 to May 19, 2026?
- **[polymarket/politics/bearish]** (90%) Will Oprah Winfrey win the 2028 Democratic presidential nomination?
- **[polymarket/markets/bearish]** (90%) Will WTI Crude Oil (WTI) hit (HIGH) $150 in May?
- **[reddit/gme_intel/bearish]** (95%) GME vs. GMEBAY - The funding problem, the dilution math, and what could happen when RC makes a new proposal

## 2026-05-15 22:01:47Z — 16 anomalies
- **[polymarket/sports/bearish]** (90%) Will Uzbekistan win the 2026 FIFA World Cup?
- **[polymarket/politics/bearish]** (90%) Will Austria win Eurovision 2026?
- **[polymarket/sports/bearish]** (90%) Will Liverpool FC win on 2026-05-17?
- **[polymarket/sports/bearish]** (90%) Counter-Strike: FURIA vs Team Falcons (BO3) - PGL Astana Playoffs
- **[polymarket/politics/bearish]** (90%) US x Iran permanent peace deal by April 22, 2026?
- **[polymarket/sports/bullish]** (90%) Aston Villa FC vs. Liverpool FC: O/U 2.5
- **[polymarket/macro/bearish]** (90%) Will the Fed decrease interest rates by 50+ bps after the June 2026 meeting?
- **[polymarket/politics/bearish]** (90%) Will LeBron James win the 2028 US Presidential Election?
- **[polymarket/politics/bearish]** (90%) Will Byron Donalds win the 2028 Republican presidential nomination?
- **[polymarket/politics/bearish]** (90%) Will Tarcisio de Freitas win the 2026 Brazilian presidential election?
- **[polymarket/crypto/bearish]** (90%) Will Bitcoin reach $150,000 in May?
- **[polymarket/sports/bearish]** (90%) Will Scottie Scheffler win the 2026 PGA Championship?
- **[polymarket/politics/bearish]** (89%) Will Elon Musk post 0-19 tweets from May 12 to May 19, 2026?
- **[polymarket/politics/bearish]** (90%) Will Oprah Winfrey win the 2028 Democratic presidential nomination?
- **[polymarket/markets/bearish]** (90%) Will WTI Crude Oil (WTI) hit (HIGH) $150 in May?
- **[reddit/gme_intel/bearish]** (95%) GME vs. GMEBAY - The funding problem, the dilution math, and what could happen when RC makes a new proposal

## 2026-05-15 22:10:46Z — 16 anomalies
- **[polymarket/sports/bearish]** (90%) Will Uzbekistan win the 2026 FIFA World Cup?
- **[polymarket/politics/bearish]** (90%) Will Austria win Eurovision 2026?
- **[polymarket/sports/bearish]** (90%) Will Liverpool FC win on 2026-05-17?
- **[polymarket/sports/bearish]** (90%) Counter-Strike: FURIA vs Team Falcons (BO3) - PGL Astana Playoffs
- **[polymarket/politics/bearish]** (90%) US x Iran permanent peace deal by April 22, 2026?
- **[polymarket/sports/bullish]** (90%) Aston Villa FC vs. Liverpool FC: O/U 2.5
- **[polymarket/macro/bearish]** (90%) Will the Fed decrease interest rates by 50+ bps after the June 2026 meeting?
- **[polymarket/politics/bearish]** (90%) Will LeBron James win the 2028 US Presidential Election?
- **[polymarket/politics/bearish]** (90%) Will Byron Donalds win the 2028 Republican presidential nomination?
- **[polymarket/politics/bearish]** (90%) Will Tarcisio de Freitas win the 2026 Brazilian presidential election?
- **[polymarket/sports/bearish]** (90%) Will Scottie Scheffler win the 2026 PGA Championship?
- **[polymarket/crypto/bearish]** (90%) Will Bitcoin reach $150,000 in May?
- **[polymarket/politics/bearish]** (90%) Will Elon Musk post 0-19 tweets from May 12 to May 19, 2026?
- **[polymarket/politics/bearish]** (90%) Will Oprah Winfrey win the 2028 Democratic presidential nomination?
- **[polymarket/markets/bearish]** (90%) Will WTI Crude Oil (WTI) hit (HIGH) $150 in May?
- **[reddit/gme_intel/bearish]** (95%) GME vs. GMEBAY - The funding problem, the dilution math, and what could happen when RC makes a new proposal

## 2026-05-15 22:17:10Z — 17 anomalies
- **[polymarket/sports/bearish]** (90%) Will Uzbekistan win the 2026 FIFA World Cup?
- **[polymarket/politics/bearish]** (90%) Will Austria win Eurovision 2026?
- **[polymarket/sports/bearish]** (90%) Will Liverpool FC win on 2026-05-17?
- **[polymarket/sports/bearish]** (90%) Counter-Strike: FURIA vs Team Falcons (BO3) - PGL Astana Playoffs
- **[polymarket/politics/bearish]** (90%) US x Iran permanent peace deal by April 22, 2026?
- **[polymarket/sports/bullish]** (90%) Aston Villa FC vs. Liverpool FC: O/U 2.5
- **[polymarket/macro/bearish]** (90%) Will the Fed decrease interest rates by 50+ bps after the June 2026 meeting?
- **[polymarket/politics/bearish]** (90%) Will LeBron James win the 2028 US Presidential Election?
- **[polymarket/politics/bearish]** (90%) Will Byron Donalds win the 2028 Republican presidential nomination?
- **[polymarket/politics/bearish]** (90%) Will Tarcisio de Freitas win the 2026 Brazilian presidential election?
- **[polymarket/sports/bearish]** (90%) Will Scottie Scheffler win the 2026 PGA Championship?
- **[polymarket/crypto/bearish]** (90%) Will Bitcoin reach $150,000 in May?
- **[polymarket/politics/bearish]** (90%) Will Elon Musk post 0-19 tweets from May 12 to May 19, 2026?
- **[polymarket/politics/bearish]** (90%) Will Oprah Winfrey win the 2028 Democratic presidential nomination?
- **[polymarket/markets/bearish]** (90%) Will WTI Crude Oil (WTI) hit (HIGH) $150 in May?
- **[options_flow/dark_pool/bullish]** (95%) CIFR dark pool: $75,188,960 across 2 prints
- **[reddit/gme_intel/bearish]** (95%) GME vs. GMEBAY - The funding problem, the dilution math, and what could happen when RC makes a new proposal

## 2026-05-15 22:27:26Z — 16 anomalies
- **[polymarket/sports/bearish]** (90%) Will Uzbekistan win the 2026 FIFA World Cup?
- **[polymarket/politics/bearish]** (90%) Will Austria win Eurovision 2026?
- **[polymarket/sports/bearish]** (90%) Will Liverpool FC win on 2026-05-17?
- **[polymarket/sports/bearish]** (90%) Counter-Strike: FURIA vs Team Falcons (BO3) - PGL Astana Playoffs
- **[polymarket/politics/bearish]** (90%) US x Iran permanent peace deal by April 22, 2026?
- **[polymarket/sports/bullish]** (90%) Aston Villa FC vs. Liverpool FC: O/U 2.5
- **[polymarket/macro/bearish]** (90%) Will the Fed decrease interest rates by 50+ bps after the June 2026 meeting?
- **[polymarket/politics/bearish]** (90%) Will LeBron James win the 2028 US Presidential Election?
- **[polymarket/sports/bearish]** (90%) Will Scottie Scheffler win the 2026 PGA Championship?
- **[polymarket/politics/bearish]** (90%) Will Tarcisio de Freitas win the 2026 Brazilian presidential election?
- **[polymarket/politics/bearish]** (90%) Will Byron Donalds win the 2028 Republican presidential nomination?
- **[polymarket/crypto/bearish]** (90%) Will Bitcoin reach $150,000 in May?
- **[polymarket/politics/bearish]** (90%) Will Elon Musk post 0-19 tweets from May 12 to May 19, 2026?
- **[polymarket/politics/bearish]** (90%) Will Oprah Winfrey win the 2028 Democratic presidential nomination?
- **[polymarket/markets/bearish]** (90%) Will WTI Crude Oil (WTI) hit (HIGH) $150 in May?
- **[reddit/gme_intel/bearish]** (95%) GME vs. GMEBAY - The funding problem, the dilution math, and what could happen when RC makes a new proposal

## 2026-05-15 22:35:54Z — 16 anomalies
- **[polymarket/sports/bearish]** (90%) Will Uzbekistan win the 2026 FIFA World Cup?
- **[polymarket/politics/bearish]** (90%) Will Austria win Eurovision 2026?
- **[polymarket/sports/bearish]** (90%) Will Liverpool FC win on 2026-05-17?
- **[polymarket/sports/bearish]** (90%) Counter-Strike: FURIA vs Team Falcons (BO3) - PGL Astana Playoffs
- **[polymarket/politics/bearish]** (90%) US x Iran permanent peace deal by April 22, 2026?
- **[polymarket/sports/bullish]** (90%) Aston Villa FC vs. Liverpool FC: O/U 2.5
- **[polymarket/macro/bearish]** (90%) Will the Fed decrease interest rates by 50+ bps after the June 2026 meeting?
- **[polymarket/sports/bearish]** (90%) Will Scottie Scheffler win the 2026 PGA Championship?
- **[polymarket/politics/bearish]** (90%) Will LeBron James win the 2028 US Presidential Election?
- **[polymarket/politics/bearish]** (90%) Will Tarcisio de Freitas win the 2026 Brazilian presidential election?
- **[polymarket/politics/bearish]** (90%) Will Byron Donalds win the 2028 Republican presidential nomination?
- **[polymarket/crypto/bearish]** (90%) Will Bitcoin reach $150,000 in May?
- **[polymarket/politics/bearish]** (90%) Will Elon Musk post 0-19 tweets from May 12 to May 19, 2026?
- **[polymarket/politics/bearish]** (90%) Will Oprah Winfrey win the 2028 Democratic presidential nomination?
- **[polymarket/markets/bearish]** (90%) Will WTI Crude Oil (WTI) hit (HIGH) $150 in May?
- **[reddit/gme_intel/bearish]** (95%) GME vs. GMEBAY - The funding problem, the dilution math, and what could happen when RC makes a new proposal

## 2026-05-15 22:43:09Z — 15 anomalies
- **[polymarket/sports/bearish]** (90%) Will Uzbekistan win the 2026 FIFA World Cup?
- **[polymarket/politics/bearish]** (90%) Will Austria win Eurovision 2026?
- **[polymarket/sports/bearish]** (90%) Will Liverpool FC win on 2026-05-17?
- **[polymarket/politics/bearish]** (90%) US x Iran permanent peace deal by April 22, 2026?
- **[polymarket/sports/bullish]** (90%) Aston Villa FC vs. Liverpool FC: O/U 2.5
- **[polymarket/macro/bearish]** (90%) Will the Fed decrease interest rates by 50+ bps after the June 2026 meeting?
- **[polymarket/sports/bearish]** (90%) Will Scottie Scheffler win the 2026 PGA Championship?
- **[polymarket/politics/bearish]** (90%) Will LeBron James win the 2028 US Presidential Election?
- **[polymarket/politics/bearish]** (90%) Will Byron Donalds win the 2028 Republican presidential nomination?
- **[polymarket/politics/bearish]** (90%) Will Tarcisio de Freitas win the 2026 Brazilian presidential election?
- **[polymarket/crypto/bearish]** (90%) Will Bitcoin reach $150,000 in May?
- **[polymarket/politics/bearish]** (90%) Will Elon Musk post 0-19 tweets from May 12 to May 19, 2026?
- **[polymarket/politics/bearish]** (90%) Will Oprah Winfrey win the 2028 Democratic presidential nomination?
- **[polymarket/markets/bearish]** (90%) Will WTI Crude Oil (WTI) hit (HIGH) $150 in May?
- **[reddit/gme_intel/bearish]** (95%) GME vs. GMEBAY - The funding problem, the dilution math, and what could happen when RC makes a new proposal

## 2026-05-15 22:49:25Z — 15 anomalies
- **[polymarket/sports/bearish]** (90%) Will Uzbekistan win the 2026 FIFA World Cup?
- **[polymarket/politics/bearish]** (90%) Will Austria win Eurovision 2026?
- **[polymarket/sports/bearish]** (90%) Will Liverpool FC win on 2026-05-17?
- **[polymarket/politics/bearish]** (90%) US x Iran permanent peace deal by April 22, 2026?
- **[polymarket/sports/bullish]** (90%) Aston Villa FC vs. Liverpool FC: O/U 2.5
- **[polymarket/macro/bearish]** (90%) Will the Fed decrease interest rates by 50+ bps after the June 2026 meeting?
- **[polymarket/politics/bearish]** (90%) Will LeBron James win the 2028 US Presidential Election?
- **[polymarket/politics/bearish]** (90%) Will Byron Donalds win the 2028 Republican presidential nomination?
- **[polymarket/sports/bearish]** (90%) Will Scottie Scheffler win the 2026 PGA Championship?
- **[polymarket/politics/bearish]** (90%) Will Tarcisio de Freitas win the 2026 Brazilian presidential election?
- **[polymarket/crypto/bearish]** (90%) Will Bitcoin reach $150,000 in May?
- **[polymarket/politics/bearish]** (90%) Will Elon Musk post 0-19 tweets from May 12 to May 19, 2026?
- **[polymarket/politics/bearish]** (90%) Will Oprah Winfrey win the 2028 Democratic presidential nomination?
- **[polymarket/markets/bearish]** (90%) Will WTI Crude Oil (WTI) hit (HIGH) $150 in May?
- **[reddit/gme_intel/bearish]** (95%) GME vs. GMEBAY - The funding problem, the dilution math, and what could happen when RC makes a new proposal

## 2026-05-15 22:57:13Z — 15 anomalies
- **[polymarket/sports/bearish]** (90%) Will Uzbekistan win the 2026 FIFA World Cup?
- **[polymarket/politics/bearish]** (90%) Will Austria win Eurovision 2026?
- **[polymarket/sports/bearish]** (90%) Will Liverpool FC win on 2026-05-17?
- **[polymarket/politics/bearish]** (90%) US x Iran permanent peace deal by April 22, 2026?
- **[polymarket/sports/bullish]** (90%) Aston Villa FC vs. Liverpool FC: O/U 2.5
- **[polymarket/macro/bearish]** (90%) Will the Fed decrease interest rates by 50+ bps after the June 2026 meeting?
- **[polymarket/politics/bearish]** (90%) Will LeBron James win the 2028 US Presidential Election?
- **[polymarket/sports/bearish]** (90%) Will Scottie Scheffler win the 2026 PGA Championship?
- **[polymarket/politics/bearish]** (90%) Will Byron Donalds win the 2028 Republican presidential nomination?
- **[polymarket/politics/bearish]** (90%) Will Tarcisio de Freitas win the 2026 Brazilian presidential election?
- **[polymarket/crypto/bearish]** (90%) Will Bitcoin reach $150,000 in May?
- **[polymarket/politics/bearish]** (90%) Will Elon Musk post 0-19 tweets from May 12 to May 19, 2026?
- **[polymarket/politics/bearish]** (90%) Will Oprah Winfrey win the 2028 Democratic presidential nomination?
- **[polymarket/markets/bearish]** (90%) Will WTI Crude Oil (WTI) hit (HIGH) $150 in May?
- **[reddit/gme_intel/bearish]** (95%) GME vs. GMEBAY - The funding problem, the dilution math, and what could happen when RC makes a new proposal

## 2026-05-15 23:18:36Z — 14 anomalies
- **[polymarket/sports/bearish]** (90%) Will Uzbekistan win the 2026 FIFA World Cup?
- **[polymarket/politics/bearish]** (90%) Will Austria win Eurovision 2026?
- **[polymarket/sports/bearish]** (90%) Will Liverpool FC win on 2026-05-17?
- **[polymarket/politics/bearish]** (90%) US x Iran permanent peace deal by April 22, 2026?
- **[polymarket/sports/bullish]** (90%) Aston Villa FC vs. Liverpool FC: O/U 2.5
- **[polymarket/macro/bearish]** (90%) Will the Fed decrease interest rates by 50+ bps after the June 2026 meeting?
- **[polymarket/politics/bearish]** (90%) Will LeBron James win the 2028 US Presidential Election?
- **[polymarket/politics/bearish]** (90%) Will Byron Donalds win the 2028 Republican presidential nomination?
- **[polymarket/sports/bearish]** (90%) Will Scottie Scheffler win the 2026 PGA Championship?
- **[polymarket/crypto/bearish]** (90%) Will Bitcoin reach $150,000 in May?
- **[polymarket/politics/bearish]** (90%) Will Elon Musk post 0-19 tweets from May 12 to May 19, 2026?
- **[polymarket/politics/bearish]** (90%) Will Oprah Winfrey win the 2028 Democratic presidential nomination?
- **[polymarket/markets/bearish]** (90%) Will WTI Crude Oil (WTI) hit (HIGH) $150 in May?
- **[reddit/gme_intel/bearish]** (95%) GME vs. GMEBAY - The funding problem, the dilution math, and what could happen when RC makes a new proposal

## 2026-05-15 23:28:38Z — 14 anomalies
- **[polymarket/sports/bearish]** (90%) Will Uzbekistan win the 2026 FIFA World Cup?
- **[polymarket/politics/bearish]** (90%) Will Austria win Eurovision 2026?
- **[polymarket/sports/bearish]** (90%) Will Liverpool FC win on 2026-05-17?
- **[polymarket/politics/bearish]** (90%) US x Iran permanent peace deal by April 22, 2026?
- **[polymarket/sports/bullish]** (90%) Aston Villa FC vs. Liverpool FC: O/U 2.5
- **[polymarket/macro/bearish]** (90%) Will the Fed decrease interest rates by 50+ bps after the June 2026 meeting?
- **[polymarket/politics/bearish]** (90%) Will LeBron James win the 2028 US Presidential Election?
- **[polymarket/politics/bearish]** (90%) Will Byron Donalds win the 2028 Republican presidential nomination?
- **[polymarket/sports/bearish]** (90%) Will Scottie Scheffler win the 2026 PGA Championship?
- **[polymarket/crypto/bearish]** (90%) Will Bitcoin reach $150,000 in May?
- **[polymarket/politics/bearish]** (90%) Will Elon Musk post 0-19 tweets from May 12 to May 19, 2026?
- **[polymarket/politics/bearish]** (90%) Will Oprah Winfrey win the 2028 Democratic presidential nomination?
- **[polymarket/markets/bearish]** (90%) Will WTI Crude Oil (WTI) hit (HIGH) $150 in May?
- **[reddit/gme_intel/bearish]** (95%) GME vs. GMEBAY - The funding problem, the dilution math, and what could happen when RC makes a new proposal

## 2026-05-15 23:41:16Z — 14 anomalies
- **[polymarket/sports/bearish]** (90%) Will Uzbekistan win the 2026 FIFA World Cup?
- **[polymarket/politics/bearish]** (90%) Will Austria win Eurovision 2026?
- **[polymarket/sports/bearish]** (90%) Will Liverpool FC win on 2026-05-17?
- **[polymarket/politics/bearish]** (90%) US x Iran permanent peace deal by April 22, 2026?
- **[polymarket/sports/bullish]** (90%) Aston Villa FC vs. Liverpool FC: O/U 2.5
- **[polymarket/macro/bearish]** (90%) Will the Fed decrease interest rates by 50+ bps after the June 2026 meeting?
- **[polymarket/politics/bearish]** (90%) Will LeBron James win the 2028 US Presidential Election?
- **[polymarket/politics/bearish]** (90%) Will Byron Donalds win the 2028 Republican presidential nomination?
- **[polymarket/sports/bearish]** (90%) Will Scottie Scheffler win the 2026 PGA Championship?
- **[polymarket/crypto/bearish]** (90%) Will Bitcoin reach $150,000 in May?
- **[polymarket/politics/bearish]** (88%) Will Elon Musk post 0-19 tweets from May 12 to May 19, 2026?
- **[polymarket/politics/bearish]** (90%) Will Oprah Winfrey win the 2028 Democratic presidential nomination?
- **[polymarket/markets/bearish]** (90%) Will WTI Crude Oil (WTI) hit (HIGH) $150 in May?
- **[reddit/gme_intel/bearish]** (95%) GME vs. GMEBAY - The funding problem, the dilution math, and what could happen when RC makes a new proposal

## 2026-05-15 23:49:43Z — 13 anomalies
- **[polymarket/sports/bearish]** (90%) Will Uzbekistan win the 2026 FIFA World Cup?
- **[polymarket/politics/bearish]** (90%) Will Austria win Eurovision 2026?
- **[polymarket/sports/bearish]** (90%) Will Liverpool FC win on 2026-05-17?
- **[polymarket/politics/bearish]** (90%) US x Iran permanent peace deal by April 22, 2026?
- **[polymarket/sports/bullish]** (90%) Aston Villa FC vs. Liverpool FC: O/U 2.5
- **[polymarket/macro/bearish]** (90%) Will the Fed decrease interest rates by 50+ bps after the June 2026 meeting?
- **[polymarket/politics/bearish]** (90%) Will LeBron James win the 2028 US Presidential Election?
- **[polymarket/politics/bearish]** (90%) Will Byron Donalds win the 2028 Republican presidential nomination?
- **[polymarket/sports/bearish]** (90%) Will Scottie Scheffler win the 2026 PGA Championship?
- **[polymarket/crypto/bearish]** (90%) Will Bitcoin reach $150,000 in May?
- **[polymarket/politics/bearish]** (90%) Will Oprah Winfrey win the 2028 Democratic presidential nomination?
- **[polymarket/markets/bearish]** (90%) Will WTI Crude Oil (WTI) hit (HIGH) $150 in May?
- **[reddit/gme_intel/bearish]** (95%) GME vs. GMEBAY - The funding problem, the dilution math, and what could happen when RC makes a new proposal

## 2026-05-16 03:14:21Z — 1 anomalies
- **[reddit/gme_intel/bearish]** (95%) GME vs. GMEBAY - The funding problem, the dilution math, and what could happen when RC makes a new proposal

## 2026-05-20 05:23:40Z — 2 anomalies
- **[market_data/insider_cluster/bearish]** (92%) AAOI insider cluster: 5 insiders, net -5 ($-31,708,486)
- **[market_data/insider_cluster/bearish]** (92%) ARTV insider cluster: 5 insiders, net -5 ($-477,890)

## 2026-05-21 01:54:01Z — 1 anomalies
- **[reddit/retail_yolo/bullish]** (95%) NVDA earnings 600k yolo

## 2026-05-22 13:20:01Z — 1 anomalies
- **[reddit/retail_dd/bullish]** (95%) The top is almost in DD: my harem of women

