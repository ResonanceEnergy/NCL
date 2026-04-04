# Intelligence Scan Configuration

## Source Configuration

### X (Twitter) Scanner
- **Interval**: 5 minutes
- **Accounts monitored**: See `intelligence-scan/sources.md`
- **Keyword alerts**: geopolitical, tariff, sanctions, AI, semiconductor, prediction market
- **Engagement threshold**: 1000+ likes or 100+ retweets for auto-alert

### YouTube Scanner
- **Interval**: 10 minutes
- **Channels**: Configured per UNI research topic
- **Trigger**: New video from tracked channels, or trending video matching keywords

### Reddit Scanner
- **Interval**: 10 minutes
- **Subreddits**: r/wallstreetbets, r/geopolitics, r/singularity, r/gamedev
- **Trigger**: Posts reaching 500+ upvotes with matching keywords

### Polymarket Scanner
- **Interval**: 5 minutes
- **Trigger**: Probability drift > 5% in 1 hour on tracked events
- **Integration**: Feeds directly into AAC War Room scenario intake

## Importance Scoring Algorithm

```
importance = base_weight(source) * engagement_multiplier * recency_factor * keyword_match_count
```

Where:
- base_weight: X=1.0, YouTube=0.8, Reddit=0.7, Polymarket=1.2, RSS=0.5
- engagement_multiplier: log10(engagement_metric) / 3
- recency_factor: 1.0 if <1h, 0.8 if <6h, 0.5 if <24h, 0.3 if <48h
- keyword_match_count: number of tracked keywords matched (1-5, capped)

Alerts are generated when importance >= 50.
