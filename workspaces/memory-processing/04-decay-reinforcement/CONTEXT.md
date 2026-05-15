# Stage 04: Decay Reinforcement

Apply time decay to old facts, boost reinforced facts (recited multiple times).

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Stage 03 | `/dev/NCL/memory/index_consolidated.json` | All MemUnits + metadata | Decay/reinforce source |

## Process

1. For each MemUnit: calculate age in days (today - observation_date)
2. Apply decay function: confidence *= exp(-age / half_life) where half_life = 365
3. For reinforced facts (cited in multiple episodes): boost = min(count * 1.1, 100)
4. Update confidence score: final = min(decay * boost, 100)
5. Mark facts approaching zero confidence for archive

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Decayed Index | `/dev/NCL/memory/index_decayed_{date}.json` | JSON (updated confidences) |
| Decay Map | `/dev/NCL/memory/decay_{date}.log` | TSV (unit, old_conf, decay, reinforce, new_conf) |

## Checkpoints

- Decay function applied uniformly
- Reinforcement boost calculations verified
- Archive candidates (confidence < 10) logged

## Audit

- Half-life parameter value (365 days)
- Decay application timestamp
- Reinforcement count distribution
