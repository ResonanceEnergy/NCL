"""Seed the FPC prediction store with diverse council sessions across all 26 domains.

Usage:
    python _seed_council.py              # Run all 26 domains (2 topics each = 52 sessions)
    python _seed_council.py --domains 5  # Run first N domains only (for testing)

Each session produces 4 predictions (one per council member), so 52 sessions = 208 predictions.
"""

import sys
import time

sys.path.insert(0, ".")

from ncl_agency_runtime.fpc.heuristic_council import (
    FuturePredictorCouncil,
    PredictionHorizon,
)
from ncl_agency_runtime.fpc.persistence import PredictionStore

# ── Seed topics: 2 per domain, varied horizons ──────────────────────────────

# Map topics_registry domains → scorer's 14 domains
_REGISTRY_TO_SCORER = {
    "ai_technology": "06_technology",
    "finance_markets": "02_financial_markets",
    "geopolitics": "04_geopolitics",
    "science_research": "06_technology",
    "entrepreneurship": "02_financial_markets",
    "security_intelligence": "06_technology",
    "health_longevity": "08_health_disease",
    "philosophy_wisdom": "14_governance",
    "personal_brand": "06_technology",
    "operations_productivity": "06_technology",
    "creative_media": "06_technology",
    "energy_climate": "05_energy_resources",
    "data_engineering": "06_technology",
    "blockchain_web3": "01_crypto_defi",
    "mobile_development": "06_technology",
    "agent_frameworks": "06_technology",
    "open_source_models": "06_technology",
    "multimodal_ai": "06_technology",
    "systems_infrastructure": "06_technology",
    "web_frameworks": "06_technology",
    "education_learning": "10_demographics",
    "entertainment_culture": "13_alt_fringe",
    "sports": "13_alt_fringe",
    "politics": "14_governance",
    "lifestyle": "10_demographics",
    "forecasting": "03_macroeconomics",
}

DOMAIN_SEEDS: list[dict] = [
    # 1. AI Technology
    {"domain": "ai_technology", "topic": "Will autonomous AI agents replace most software engineering tasks by 2028?",
     "horizon": PredictionHorizon.MEDIUM_TERM},
    {"domain": "ai_technology", "topic": "How will open-source LLMs compete with proprietary models in enterprise adoption?",
     "horizon": PredictionHorizon.SHORT_TERM},

    # 2. Finance & Markets
    {"domain": "finance_markets", "topic": "Will the Federal Reserve cut interest rates below 3% by year-end 2026?",
     "horizon": PredictionHorizon.SHORT_TERM},
    {"domain": "finance_markets", "topic": "How will AI-driven algorithmic trading reshape equity market volatility?",
     "horizon": PredictionHorizon.MEDIUM_TERM},

    # 3. Geopolitics
    {"domain": "geopolitics", "topic": "Will US-China tech decoupling accelerate semiconductor reshoring to North America?",
     "horizon": PredictionHorizon.MEDIUM_TERM},
    {"domain": "geopolitics", "topic": "How will the Russia-Ukraine conflict affect European energy security posture?",
     "horizon": PredictionHorizon.SHORT_TERM},

    # 4. Science & Research
    {"domain": "science_research", "topic": "Will commercial fusion power achieve net energy gain demonstration by 2030?",
     "horizon": PredictionHorizon.LONG_TERM},
    {"domain": "science_research", "topic": "How will CRISPR gene therapy transform treatment of genetic diseases?",
     "horizon": PredictionHorizon.MEDIUM_TERM},

    # 5. Entrepreneurship
    {"domain": "entrepreneurship", "topic": "Will AI-native startups outperform traditional SaaS in venture returns?",
     "horizon": PredictionHorizon.MEDIUM_TERM},
    {"domain": "entrepreneurship", "topic": "How will solo founders leveraging AI agents change the startup landscape?",
     "horizon": PredictionHorizon.SHORT_TERM},

    # 6. Cybersecurity & Intelligence
    {"domain": "security_intelligence", "topic": "Will AI-powered cyber attacks outpace defensive capabilities by 2027?",
     "horizon": PredictionHorizon.MEDIUM_TERM},
    {"domain": "security_intelligence", "topic": "How will quantum computing threaten current encryption standards?",
     "horizon": PredictionHorizon.LONG_TERM},

    # 7. Health & Longevity
    {"domain": "health_longevity", "topic": "Will GLP-1 receptor agonists become the most prescribed drug class globally?",
     "horizon": PredictionHorizon.SHORT_TERM},
    {"domain": "health_longevity", "topic": "How will AI-driven drug discovery shorten development timelines below 5 years?",
     "horizon": PredictionHorizon.MEDIUM_TERM},

    # 8. Philosophy & Wisdom
    {"domain": "philosophy_wisdom", "topic": "Will AI alignment research produce a consensus framework for safe AGI development?",
     "horizon": PredictionHorizon.LONG_TERM},
    {"domain": "philosophy_wisdom", "topic": "How will cognitive augmentation tools change human decision-making quality?",
     "horizon": PredictionHorizon.MEDIUM_TERM},

    # 9. Personal Brand
    {"domain": "personal_brand", "topic": "Will AI-generated content dominate social media by 2027?",
     "horizon": PredictionHorizon.MEDIUM_TERM},
    {"domain": "personal_brand", "topic": "How will creator economy monetization shift with AI tools and automation?",
     "horizon": PredictionHorizon.SHORT_TERM},

    # 10. Operations & Productivity
    {"domain": "operations_productivity", "topic": "Will no-code and AI agent platforms eliminate most DevOps roles?",
     "horizon": PredictionHorizon.LONG_TERM},
    {"domain": "operations_productivity", "topic": "How will agentic workflow automation transform enterprise operations?",
     "horizon": PredictionHorizon.SHORT_TERM},

    # 11. Creative & Media
    {"domain": "creative_media", "topic": "Will AI-generated films win major awards within 5 years?",
     "horizon": PredictionHorizon.LONG_TERM},
    {"domain": "creative_media", "topic": "How will text-to-video models like Sora disrupt traditional content production?",
     "horizon": PredictionHorizon.SHORT_TERM},

    # 12. Energy & Climate
    {"domain": "energy_climate", "topic": "Will small modular nuclear reactors achieve commercial deployment by 2030?",
     "horizon": PredictionHorizon.LONG_TERM},
    {"domain": "energy_climate", "topic": "How will battery storage costs affect renewable energy grid integration?",
     "horizon": PredictionHorizon.MEDIUM_TERM},

    # 13. Data Engineering
    {"domain": "data_engineering", "topic": "Will real-time data streaming replace batch ETL as the default pipeline architecture?",
     "horizon": PredictionHorizon.MEDIUM_TERM},
    {"domain": "data_engineering", "topic": "How will AI-native data tools transform analytics workflows for non-technical users?",
     "horizon": PredictionHorizon.SHORT_TERM},

    # 14. Blockchain & Web3
    {"domain": "blockchain_web3", "topic": "Will Ethereum Layer 2 solutions achieve mainstream payment adoption?",
     "horizon": PredictionHorizon.MEDIUM_TERM},
    {"domain": "blockchain_web3", "topic": "How will tokenized real-world assets reshape traditional capital markets?",
     "horizon": PredictionHorizon.LONG_TERM},

    # 15. Mobile Development
    {"domain": "mobile_development", "topic": "Will on-device AI models make cloud-dependent mobile apps obsolete?",
     "horizon": PredictionHorizon.MEDIUM_TERM},
    {"domain": "mobile_development", "topic": "How will Apple Intelligence reshape iOS app development patterns?",
     "horizon": PredictionHorizon.SHORT_TERM},

    # 16. Agent Frameworks
    {"domain": "agent_frameworks", "topic": "Will multi-agent orchestration frameworks converge on a standard protocol?",
     "horizon": PredictionHorizon.MEDIUM_TERM},
    {"domain": "agent_frameworks", "topic": "How will autonomous agent swarms solve complex business processes?",
     "horizon": PredictionHorizon.SHORT_TERM},

    # 17. Open Source Models
    {"domain": "open_source_models", "topic": "Will open-weight models match GPT-5 performance within 12 months of release?",
     "horizon": PredictionHorizon.SHORT_TERM},
    {"domain": "open_source_models", "topic": "How will local AI model deployment change enterprise data privacy strategies?",
     "horizon": PredictionHorizon.MEDIUM_TERM},

    # 18. Multi-Modal AI
    {"domain": "multimodal_ai", "topic": "Will multi-modal models replace specialized single-task AI systems?",
     "horizon": PredictionHorizon.MEDIUM_TERM},
    {"domain": "multimodal_ai", "topic": "How will vision-language-action models transform robotics and manufacturing?",
     "horizon": PredictionHorizon.LONG_TERM},

    # 19. Systems & Infrastructure
    {"domain": "systems_infrastructure", "topic": "Will Rust become the dominant language for AI infrastructure and tooling?",
     "horizon": PredictionHorizon.MEDIUM_TERM},
    {"domain": "systems_infrastructure", "topic": "How will WebAssembly change edge computing and serverless architectures?",
     "horizon": PredictionHorizon.SHORT_TERM},

    # 20. Web Frameworks
    {"domain": "web_frameworks", "topic": "Will AI-first web frameworks replace React and Next.js as default choices?",
     "horizon": PredictionHorizon.LONG_TERM},
    {"domain": "web_frameworks", "topic": "How will server-side rendering trends affect frontend development practices?",
     "horizon": PredictionHorizon.SHORT_TERM},

    # 21. Education & Learning
    {"domain": "education_learning", "topic": "Will AI tutors outperform human teachers in standardized test preparation?",
     "horizon": PredictionHorizon.MEDIUM_TERM},
    {"domain": "education_learning", "topic": "How will AI-powered credential verification disrupt traditional university degrees?",
     "horizon": PredictionHorizon.LONG_TERM},

    # 22. Entertainment & Culture
    {"domain": "entertainment_culture", "topic": "Will AI-generated music dominate streaming platform charts by 2028?",
     "horizon": PredictionHorizon.MEDIUM_TERM},
    {"domain": "entertainment_culture", "topic": "How will interactive AI storytelling transform the entertainment industry?",
     "horizon": PredictionHorizon.SHORT_TERM},

    # 23. Sports
    {"domain": "sports", "topic": "Will AI-driven analytics give small-market sports teams a competitive edge?",
     "horizon": PredictionHorizon.SHORT_TERM},
    {"domain": "sports", "topic": "How will wearable tech and biometric AI reshape athlete performance optimization?",
     "horizon": PredictionHorizon.MEDIUM_TERM},

    # 24. Politics
    {"domain": "politics", "topic": "Will AI-generated deepfakes materially influence a major election by 2028?",
     "horizon": PredictionHorizon.MEDIUM_TERM},
    {"domain": "politics", "topic": "How will AI regulation differ between US, EU, and China governance models?",
     "horizon": PredictionHorizon.SHORT_TERM},

    # 25. Lifestyle
    {"domain": "lifestyle", "topic": "Will AI personal assistants manage most household purchasing decisions?",
     "horizon": PredictionHorizon.LONG_TERM},
    {"domain": "lifestyle", "topic": "How will remote work and AI tools reshape urban vs rural living preferences?",
     "horizon": PredictionHorizon.SHORT_TERM},

    # 26. Forecasting
    {"domain": "forecasting", "topic": "Will neural forecasting models outperform statistical methods across all domains?",
     "horizon": PredictionHorizon.MEDIUM_TERM},
    {"domain": "forecasting", "topic": "How will ensemble prediction councils improve forecast accuracy over single models?",
     "horizon": PredictionHorizon.SHORT_TERM},
]


def main():
    max_domains = None
    if len(sys.argv) > 1 and sys.argv[1] == "--domains":
        max_domains = int(sys.argv[2])

    config_path = "ncl_agency_runtime/fpc/config/council_config.json"
    store = PredictionStore()

    # Check current count
    before = len(store.list_all())
    print(f"Predictions before seeding: {before}")

    seeds = DOMAIN_SEEDS
    if max_domains:
        # Each domain has 2 seeds
        seeds = seeds[: max_domains * 2]

    total_stored = 0
    domains_done = set()

    for i, seed in enumerate(seeds, 1):
        domain = seed["domain"]
        topic = seed["topic"]
        horizon = seed["horizon"]

        print(f"\n[{i}/{len(seeds)}] {domain} — {horizon.value}")
        print(f"  Topic: {topic[:80]}...")

        # Fresh council instance per session so IDs don't collide
        council = FuturePredictorCouncil(config_path=config_path)
        session = council.convene_council(topic, horizon)

        preds = session.get("predictions", [])
        stored = 0
        for j, p in enumerate(preds):
            # Build unique ID: domain + session index + member index + microsecond
            unique_id = f"{domain}_s{i:02d}_m{j}_{int(time.time()*1000)}"
            scorer_domain = _REGISTRY_TO_SCORER.get(domain, "03_macroeconomics")
            # Convert enum values to strings for storage
            pred_dict = {
                "id": unique_id,
                "topic": p.get("topic", topic),
                "predicted_outcome": p.get("predicted_outcome", ""),
                "confidence": p.get("confidence", 0),
                "risk_level": p.get("risk_level", "medium"),
                "council_member": p.get("council_member", ""),
                "scorer_domain": scorer_domain,
                "source_domain": domain,
            }
            # Handle risk_level being a RiskLevel enum
            rl = pred_dict["risk_level"]
            if hasattr(rl, "value"):
                pred_dict["risk_level"] = rl.value

            store.record(pred_dict)
            stored += 1

        total_stored += stored
        domains_done.add(domain)
        consensus = session.get("consensus", {})
        print(f"  Stored {stored} predictions | consensus={consensus.get('consensus_reached', '?')} "
              f"conf={consensus.get('average_confidence', 0):.2f}")

    after = len(store.list_all())
    print(f"\n{'='*60}")
    print("SEEDING COMPLETE")
    print(f"  Domains covered:  {len(domains_done)}")
    print(f"  Sessions run:     {len(seeds)}")
    print(f"  Predictions added: {total_stored}")
    print(f"  Store before:     {before}")
    print(f"  Store after:      {after}")
    print(f"  Net new:          {after - before}")


if __name__ == "__main__":
    main()
