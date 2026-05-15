# Stage 05: Distribution

Route insights to relevant NCL, NCC, and BRS modules based on domain and mandate.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Stage 04 | `/dev/NCL/intelligence/insights/{date}.json` | All insights | Routing source |
| Router Config | `/dev/NCL/intelligence/routing.yaml` | Module subscriptions | Recipient mapping |

## Process

1. Parse insight domain (geopolitics, tech, finance, culture)
2. Look up recipients in routing config (NCL, NCC, BRS modules)
3. Format insight for recipient context (exec summary vs detail)
4. Send via appropriate channel (Grok push, email, API webhook)
5. Log delivery and read receipt (if applicable)

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Delivery Log | `/dev/NCL/intelligence/delivery_{date}.log` | TSV (insight, recipient, status) |
| Archive Copy | `/dev/NCL/intelligence/distributed/{date}_insights.json` | JSON (audit trail) |
