# Day 1 — Scope

> **Goal**: Define the decision, ontology objects, and success criteria.

---

## Morning (9:00–12:00)

### 1. Mission Briefing (9:00–9:30)
- Welcome and introductions
- Overview of the Future Predictor Council architecture
- Review compute profile and constraints (Ryzen 5, 16GB local / cloud burst)
- Executive sponsor sets business context

### 2. Problem Definition (9:30–10:30)
- **Exercise**: Define the core forecasting question
  - What are we predicting? (demand, revenue, traffic, inventory)
  - What is the forecast horizon? (7d, 14d, 28d, 90d)
  - What is the decision this forecast supports?
  - Who consumes the forecast and how?
- **Output**: One-page problem statement

### 3. Data Discovery (10:30–12:00)
- **Exercise**: Identify available data sources
  - Historical target variable (panel format: unique_id, ds, y)
  - Candidate exogenous features (promo, price, weather, events)
  - Data quality assessment (missing values, frequency gaps, anomalies)
- **Output**: Data contract draft

## Afternoon (13:00–17:00)

### 4. Ontology Design (13:00–14:30)
- **Exercise**: Define object types for your domain
  - Series objects (what entities are we forecasting?)
  - Feature objects (what drives the forecast?)
  - Intervention objects (what levers can we pull?)
- **Output**: Object relationship diagram

### 5. Success Criteria (14:30–15:30)
- **Exercise**: Define measurable KPIs
  - Primary metric: MASE target (e.g., < 0.85)
  - Secondary metric: sMAPE target (e.g., < 15%)
  - Business metric: What improvement does MASE < 1 translate to in dollars?
- **Output**: Success criteria document

### 6. Steering Knobs Configuration (15:30–16:30)
- **Exercise**: Configure the 5% human steering inputs
  - Metric gate: MASE or sMAPE?
  - Causal interventions: Which levers matter? (promo, price, marketing?)
  - Cloud burst: On or off? Budget cap?
  - Series priorities: Which series matter most?
- **Output**: Updated `config/steering.json`

### 7. Day 1 Retrospective (16:30–17:00)
- Review deliverables
- Identify blockers for Day 2
- Assign homework: prepare clean dataset in panel format

---

## Day 1 Deliverables Checklist
- [ ] Problem statement (1 page)
- [ ] Data contract draft
- [ ] Object relationship diagram
- [ ] Success criteria document (MASE target, business metric)
- [ ] Configured `steering.json`
- [ ] Clean dataset in panel format (unique_id, ds, y)
