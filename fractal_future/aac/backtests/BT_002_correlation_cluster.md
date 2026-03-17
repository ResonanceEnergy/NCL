# E3 Backtest — FF_AAC_BT_002: Correlation Cluster Score (Diversification Failure Detector)

## Signal
When cross-asset correlation spikes, reduce gross exposure and cap correlated strategy cells. This is a portfolio posture signal, not an entry signal.

## Universe: Mixed
- Equities: SPY, QQQ, TSLA, NVDA
- Crypto: BTC, ETH, XRP

## Period
- As available per asset class

## Purpose
Measure whether applying throttles when correlation cluster score is high reduces portfolio drawdowns without destroying returns.

## Multi-Scale Tests

### Timeframes Tested
- Daily primary; intraday optional

### Regimes Tested
- Normal (E2)
- Elevated/Unstable (E3)
- Contagion/Shock (E4)

### Parameter Sensitivity (±10–25%)
- Correlation window length
- Cluster threshold

### Out-of-Sample
- Holdout periods around known stress events (define in dataset)

## Comparison
- **Baseline portfolio:** no throttle applied
- **Throttled portfolio:** reduce gross exposure and cap correlated cells when cluster score high

## Results (Fill After Running)
- Drawdown comparison:
- Recovery time comparison:
- Volatility comparison:
- Return impact:
- Win-rate stability:
- PASS / BOUNDED / FAIL:
- Evidence label: target E3

## Output
- PASS if drawdowns reduce materially without destroying returns
- BOUNDED if only helps in E4+ scenarios
- FAIL if no measurable impact

## Entropy Notes
- This directly validates the FF-6 Entropy Gate for market systems
- Correlation = entropy coupling (when it spikes, diversification entropy budget is consumed)
