# Foundation Model Remote Execution Guide

## Overview

Foundation models (TimesFM 2.5, Chronos-2) require compute resources beyond the
local machine (Ryzen 5, 16 GB RAM). This guide covers cloud burst configurations.

## TimesFM 2.5 (Google)

### Requirements
- **RAM**: ≥32 GB to load model (≥64 GB recommended)
- **GPU**: Optional (CPU inference supported, but slower)
- **Storage**: ~5 GB for model weights

### AWS Recipe
```bash
# Launch high-memory instance
aws ec2 run-instances \
  --instance-type r6i.2xlarge \
  --image-id ami-0abcdef1234567890 \
  --key-name your-key \
  --security-group-ids sg-xxx \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=timesfm-burst}]'

# SSH in and run
pip install timesfm
python -m src.cli --data data.csv --freq D --h 28 --foundation on
```

### Cost Profile
| Instance | vCPU | RAM | Hourly | Daily (1h burst) |
|---|---|---|---|---|
| r6i.2xlarge | 8 | 64 GB | $0.504 | $0.504 |
| r6i.4xlarge | 16 | 128 GB | $1.008 | $1.008 |

### Budget Impact
At $0.504/hr with 30min daily burst: ~$0.25/day = ~$1.75/week (within $50/week cap).

## Chronos-2 (Amazon)

### Requirements
- **GPU**: NVIDIA A10G (24 GB VRAM) minimum
- **RAM**: ≥16 GB system RAM
- **Storage**: ~3 GB for model weights

### AWS Recipe
```bash
# Launch GPU instance
aws ec2 run-instances \
  --instance-type g5.xlarge \
  --image-id ami-0abcdef1234567890 \
  --key-name your-key \
  --security-group-ids sg-xxx \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=chronos-burst}]'

# SSH in and run
pip install chronos-forecasting
python -c "
from chronos import Chronos2Pipeline
pipe = Chronos2Pipeline.from_pretrained('amazon/chronos-2-base', device_map='cuda')
# ... run inference
"
```

### Cost Profile
| Instance | GPU | VRAM | Hourly | Daily (30min burst) |
|---|---|---|---|---|
| g5.xlarge | 1x A10G | 24 GB | $1.006 | $0.503 |
| g5.2xlarge | 1x A10G | 24 GB | $1.212 | $0.606 |

### Budget Impact
At $1.006/hr with 30min daily burst: ~$0.50/day = ~$3.50/week (within $50/week cap).

## Cost Caps (from steering.json)

| Parameter | Value | Description |
|---|---|---|
| `budget_weekly_usd` | $50 | Hard weekly spending cap |
| `gpu_max_hourly` | $1.20 | Max hourly rate for GPU instances |
| `gpu_max_daily_min` | 60 | Max daily GPU minutes |
| `ram_max_hourly` | $0.80 | Max hourly rate for RAM instances |

## Burst Helper

Use the built-in burst cost checker:

```python
from src.agents.burst import can_burst, start_burst

# Check if burst is within budget
ok, msg = can_burst("chronos2", duration_min=30)
print(msg)  # "Approved: chronos2 on g5.xlarge for 30min (~$0.50)"

# Start burst session
session = start_burst("chronos2", duration_min=30)
```

## Offline Caching

After cloud burst inference, cache results locally:
- Save predictions to `data/artifacts/`
- Include metadata: model version, timestamp, input hash
- Replay cached results when offline
