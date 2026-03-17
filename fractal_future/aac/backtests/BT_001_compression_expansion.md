# E3 Backtest — FF_AAC_BT_001: Compression → Expansion Breakout Trigger

## Signal
When prolonged volatility compression (ATR percentile low + range narrowing) ends with a directional range expansion, enter in the direction of the breakout.

## Universe: Mixed
- Equities: SPY, QQQ, TSLA
- Crypto: BTC, ETH

## Period
- Equities: 5–10 years
- Crypto: 5–8 years (or available)

## Execution Assumptions
- Enter on breakout close or breakout+retest variant
- Exit: fixed R multiple or trailing stop (document both)
- Fees/slippage: conservative estimate per asset class

## Multi-Scale Tests

### Timeframes Tested
- Equities: 15m / 1h / 1d
- Crypto: 1h / 4h / 1d

### Regimes Tested
- Vol compression → expansion transitions
- Trend continuation breakouts
- Range false breakout periods

### Parameter Sensitivity (±10–25%)
- ATR percentile thresholds
- Compression window length
- Breakout expansion threshold

### Out-of-Sample
- Walk-forward by year or rolling 6–12 month holdouts

## Results (Fill After Running)
- Key metrics:
- Failure modes:
- PASS / BOUNDED / FAIL:
- Evidence label: target E3
- Next action: forward test rules + risk packet enforcement

## Entropy Notes
- Best in E1→E2 transitions (compression breaking)
- Degrades in E4+ (liquidity shock causes false breaks)
- Pair with retest confirmation for equities; wick filter for crypto
