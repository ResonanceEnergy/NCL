# Day 4 — Deploy

> **Goal**: CI green, container ready, release policy configured.

---

## Morning (9:00–12:00)

### 1. CI Pipeline Setup (9:00–10:30)
- **Exercise**: Configure GitHub Actions for micro-backtest
  - Trigger on PR to `main`
  - Run: lint (ruff), type check (mypy), smoke test, micro-backtest
  - Gate: fail if MASE regresses > 5% from baseline
  - Store artifacts: backtest report CSV
- **Output**: `.github/workflows/micro_backtest.yml` passing

### 2. Security Pipeline (10:30–12:00)
- **Exercise**: Add SBOM and vulnerability scanning
  - Generate SBOM with Syft: `syft dir:. -o spdx-json > sbom.json`
  - Scan with Trivy: `trivy fs --severity HIGH,CRITICAL .`
  - Gate: block deployment on critical CVEs
- **Output**: `.github/workflows/security.yml` passing

## Afternoon (13:00–17:00)

### 3. Containerization (13:00–14:00)
- **Exercise**: Create Dockerfile for the API server
  ```dockerfile
  FROM python:3.11-slim
  COPY . /app
  WORKDIR /app
  RUN pip install -e ".[dev]"
  EXPOSE 8000
  CMD ["uvicorn", "src.serve:app", "--host", "0.0.0.0", "--port", "8000"]
  ```
- Build and test locally
- **Output**: Working container serving `/health` endpoint

### 4. Release Policy Configuration (14:00–15:00)
- **Exercise**: Configure Apollo-lite release channels
  - Review `ops/ReleasePolicy.yaml`
  - Set soak times appropriate for your deployment cadence
  - Define rollback triggers (MASE regression, error rate, latency)
- **Output**: Customized release policy

### 5. Staging Deployment (15:00–16:00)
- **Exercise**: Deploy to alpha channel
  - Push to staging environment
  - Run health checks
  - Verify forecast endpoint returns valid predictions
  - Check that XAI and what-if stubs return gracefully
- **Output**: Alpha deployment verified

### 6. Monitoring Setup (16:00–16:45)
- **Exercise**: Set up basic monitoring
  - Health endpoint polling (every 60s)
  - Log aggregation (structured JSON logs)
  - Alert on: health check failure, forecast latency > 5s, error rate > 1%
- **Output**: Monitoring configuration document

### 7. Day 4 Retrospective (16:45–17:00)
- CI green? SBOM clean? Container working?
- Alpha deployment healthy?
- Plan Day 5: documentation, handoff, Day-2 ops

---

## Day 4 Deliverables Checklist
- [ ] CI pipeline: lint + type check + micro-backtest (green)
- [ ] Security pipeline: SBOM + vuln scan (green)
- [ ] Dockerfile built and tested locally
- [ ] Release policy customized for your cadence
- [ ] Alpha channel deployment verified
- [ ] Monitoring configuration documented
