# NCL Cost Audit — Open Source Addendum

**Companion to**: `outputs/COST_AUDIT_2026-05-30.md`
**Question being answered**: "What open-source tools can be swapped in to further reduce costs? Is DeepSeek free better than Haiku? What options are available?"

---

## TL;DR — direct answer first

**Yes, DeepSeek V3 beats Haiku 4.5 for Tier B work.** Pricing as of May 2026:

| Model | Input $/M | Output $/M | Speed | Quality |
|---|---:|---:|---|---|
| Claude Haiku 4.5 | $1.00 | $5.00 | medium | matches Sonnet 4 on benchmarks |
| **DeepSeek V3 (direct API)** | **$0.14** | **$0.28** | medium | matches GPT-4 on benchmarks |
| Llama 3.3 70B on Groq | $0.59 | $0.79 | **250 tok/sec** | matches Sonnet 3.7 |
| Llama 3.3 70B on Groq + batch + cache | ~$0.15 | ~$0.40 | 250 tok/sec | same |
| DeepInfra (gpt-oss-120B) | $0.08 blended | — | medium | matches Sonnet 3.7 |
| Local Ollama qwen3:32b | **$0** | **$0** | ~30 tok/sec on M1 Ultra | ~85% of Haiku |

**DeepSeek V3 is 7× cheaper on input and 18× cheaper on output than Haiku 4.5**, with comparable or better quality on the kinds of routine classification + summarization tasks the audit tagged as Tier B. For every Tier B call site, DeepSeek V3 direct API is the right default — easier to migrate than Ollama (still hosted, still reliable) but cheaper than Haiku by an order of magnitude.

"DeepSeek free" only really exists if you self-host the open weights. DeepSeek V3 is 671B MoE (37B active) — **too big for your 64 GB Mac Studio**. But the distilled variants (DeepSeek-R1-Distill-Qwen-32B at 20 GB, DeepSeek-R1-Distill-Llama-70B at 40 GB) would run fine and add reasoning chains that base Qwen lacks. Free at runtime, just slower (~30 tok/sec vs Groq's 250).

---

## The 2026 open-source LLM landscape

### Top open-weight models, ranked by benchmark (current as of May 2026)

| Model | Params | Best for | License | Local-feasible on 64GB M1 Ultra? |
|---|---:|---|---|---|
| **DeepSeek V4 Pro (Max)** | 671B MoE | Top-of-leaderboard general reasoning | Open weight | No (671B too big) |
| **Kimi K2.6** | ~1T MoE | Long context, math | Open weight | No |
| **GLM-5 / GLM-5.1** | 100B+ | MMLU 96, GPQA 94 — knowledge | Apache 2.0 | Partial (quantized) |
| **Qwen 3.5 397B** | 397B | MMLU 91, 1M context, 201 langs | Apache 2.0 | No (full); yes (distill) |
| **DeepSeek R1** | 671B MoE | Reasoning specialist | MIT | No |
| **DeepSeek R1 Distill Llama 70B** | 70B | Reasoning chain on smaller body | MIT | **Yes (40 GB)** |
| **DeepSeek R1 Distill Qwen 32B** | 32B | Reasoning + speed | MIT | **Yes (20 GB)** |
| **Llama 3.3 70B** | 70B | General-purpose, Groq-native | Llama license | **Yes (you already have it: 42 GB)** |
| **Qwen3 32B** | 32B | Mid-size general | Apache 2.0 | **Yes (you have it: 20 GB)** |
| **gpt-oss-120B** | 120B | OpenAI's open release | Apache 2.0 | Partial (quantized) |
| **Phi-4** | 14B | Surprisingly capable small model | MIT | **Yes (8 GB)** |
| **Gemma 3** | 27B | Google's open release | Gemma license | **Yes (~16 GB)** |

### Hosted OSS providers — pricing matrix

| Provider | Cheapest model | Speed | Notes |
|---|---|---|---|
| **DeepSeek direct API** | DeepSeek V3 @ $0.14/$0.28/M | medium | First-party, cheapest for V3 |
| **Groq** | Llama 3.3 70B @ $0.59/$0.79/M (batch: $0.15/$0.40) | **250 tok/sec** | Custom LPU silicon, fastest in market |
| **DeepInfra** | gpt-oss-120B @ $0.08 blended/M | medium | Cheapest hosted overall |
| **Together AI** | Llama 3.3 70B @ $0.88/$0.88/M | medium | 173 models, supports fine-tuning |
| **Fireworks** | Llama 3.3 70B @ ~$0.90/M blended | fast | Strong reliability, similar to Together |
| **OpenRouter** | Aggregator — DeepSeek V3.2 from $0.14/$0.28 | varies | Single key, falls over between providers |
| **Cerebras Cloud** | Llama 3.1 70B @ ~$0.60/$0.60/M | **2,000 tok/sec** | Wafer-scale chip, extreme speed |

### What "open source" means in practice for NCL

These are not Anthropic-equivalent black boxes — you have three substitution paths:

1. **Open API (cheapest hosted)** — pay DeepSeek/Groq/DeepInfra directly. Cheaper than Haiku, reliable like a hosted SaaS. Drop-in replacement: NCL's `runtime/llm/client.py` already does provider routing, just add an `OPENROUTER` or `DEEPSEEK` provider key.
2. **Self-hosted on Mac Studio** — Ollama already running with 5 models. Add `DeepSeek-R1-Distill-Qwen-32B` (`ollama pull deepseek-r1:32b`, ~20 GB) for reasoning-heavy tasks. Free at runtime.
3. **Self-hosted via MLX** — install `mlx-lm`, run Qwen3-8B natively on Apple Silicon. 2-4× faster than Ollama HTTP roundtrip for hot loops. Best for the in-process memory enrichment paths.

---

## Recommended revised provider tier map for NCL

| Tier | NCL use case | Recommended provider | Cost/M | Why |
|---|---|---|---:|---|
| **A — Frontier** | Brief chair, /chat default, journal reflection, auto-trader research, Strike Point council chair | **Claude Opus / Sonnet 4** | $15/$75 (Opus), $3/$15 (Sonnet) | Mandate-locked, user reads it, last 5% quality matters |
| **B-1 — Hosted OSS, balanced** | YTC analyzer, brief PLANNER, Awarebot exec brief, Awarebot predictor, intel engine summary, MapReduce compression, procedural distillation, Night Watch triage | **DeepSeek V3 (direct API)** | $0.14/$0.28 | 7-18× cheaper than Haiku; quality matches GPT-4 on routine tasks; reliable hosted |
| **B-2 — Hosted OSS, latency** | /chat fallback (when Anthropic exhausted), real-time Awarebot scoring on hot signals | **Groq Llama 3.3 70B** | $0.59/$0.79 | 250 tok/sec streaming = better UX than Claude during fallback |
| **C — Local Ollama** | Memory enrichment (importance scoring, entity extraction), narrative threads, contradiction scanning, dedup judgment | **Ollama qwen3:32b** (already pulled) | $0 | Already wired; no roundtrip cost; private |
| **C-R — Local Ollama reasoning** | Tasks needing chain-of-thought but not user-facing (e.g. cross-reference clustering judgment) | **Ollama DeepSeek-R1-Distill-Qwen-32B** (pull, 20 GB) | $0 | Reasoning chain in 32B model; runs on Mac |
| **D — Embeddings** | All vector ops (ChromaDB, memory recall, FusedRetriever) | **Ollama nomic-embed-text** (already pulled) | $0 | 274 MB, 768-d, already on disk |
| **D — Classification** | "Is this signal X?" rule-replaceable calls in Awarebot scorer | **MPS zero-shot via transformers** (after `pip install transformers`) | $0 | M1 Ultra GPU; ~50ms latency |
| **D — Entity extraction** | Named-entity + relation tuples for memory units | **spaCy en_core_web_sm** (after `pip install spacy`) | $0 | 12 MB model; faster than any LLM call |

---

## Mapping every Tier B audit site to its best replacement

From the audit's 18 Tier B sites, here are the specific recommendations:

| # | File:Line | Feature | Audit said | **Better answer** | Why |
|---|---|---|---|---|---|
| 1 | `api/routers/intel/brief_pipeline.py:73` | Legacy brief PLANNER | Haiku 4.5 | **DeepSeek V3** | 7× cheaper; routing decision doesn't need Anthropic |
| 2 | `autonomous/night_watch/analyst.py:485` | Night Watch M1-M5 triage | Haiku 4.5 | **DeepSeek V3** | Structured triage prompts; DeepSeek's JSON mode is solid |
| 3 | `awarebot/agent.py:3282` | Awarebot exec brief | Haiku 4.5 | **DeepSeek V3** | 2-3 sentence summary; same quality at 18× lower output cost |
| 4 | `awarebot/predictor.py:231` | Awarebot prediction emitter | Haiku 4.5 | **DeepSeek V3** | JSON output with 0-1 confidence; DeepSeek excels here |
| 5 | `intelligence/engine.py:1404` | Intel engine exec brief | Haiku 4.5 | **DeepSeek V3** | Routine summary; env var already exists |
| 6 | `memory/procedural.py:71` | Procedural skill distillation | Haiku 4.5 | **DeepSeek V3** | Distilled skill text; DeepSeek matches |
| 7 | `council_pack/assembler.py:361` | MapReduce section compression | Haiku 4.5 | **Groq Llama 3.3 70B** | Compression benefits from Groq's 250 tok/sec speed |
| 8 | `councils/youtube/analyzer.py:64` | YTC per-video analyzer | Haiku 4.5 or Ollama | **Local Ollama qwen3:32b** | High volume; 30 min transcripts; latency tolerable; saves $1-3/day |
| 9 | `councils/quorum.py:49,51` | Council quorum pre-pass | Both Haiku | **Keep Haiku 3.5 + DeepSeek V3 for "Sonnet" slot** | Adversarial pair benefits from provider diversity |
| 10 | `uni/gatherer.py:154,190` | UNI gathering | Grok-3-mini / Ollama | **Default DeepSeek V3** | Cheaper than Grok-3-mini; better than Ollama on research quality |
| 11 | `lde/agents.py:251,286` | LDE agents | Ollama default | **Keep Ollama** ✓ | Already wired; quality fine for code generation tasks |
| 12 | `swarm/agents/scout.py` | Swarm scout | Ollama | **Keep Ollama** ✓ | Scout doesn't need premium reasoning |
| 13 | `swarm/agents/scholar.py` | Swarm scholar | Haiku | **DeepSeek V3** | Research-grade output; DeepSeek matches |
| 14 | `autonomous/night_watch/intel_cycle.py:105` | Night Watch correlation | Haiku 4.5 | **DeepSeek V3** | Pattern matching; DeepSeek strong on JSON structure |
| 15 | `autonomous/scheduler.py:3229,3284` | Night Watch mini-council members | Haiku 4.5 + grok-3-mini | **DeepSeek V3 + Groq Llama 3.3** | Provider diversity with both cheap |
| 16 | `autonomous/scheduler.py:3342` | Night Watch mini-council chair | Sonnet 4 (was broken Opus) | **Keep Sonnet 4** | Chair-grade synthesis; this one matters |
| 17 | `councils/xai/analyzer.py:57` | X council analyzer | Haiku 4.5 | **DeepSeek V3** when X re-enabled |
| 18 | `calendar/todo_generator.py:56` | Calendar todo generator | already Haiku ✓ | **DeepSeek V3** | Even cheaper; identical quality |

**Provider routing change required**: NCL's `runtime/llm/client.py` already routes by `Provider` enum. Add `Provider.DEEPSEEK` (uses `deepseek-chat` endpoint at `api.deepseek.com/v1`, OpenAI-compatible — drops in via existing `_openai_call` shape) and `Provider.GROQ` (uses `api.groq.com/openai/v1`, also OpenAI-compatible). Both are a single new helper function each.

---

## Direct answer: "Is DeepSeek free better than Haiku?"

Three honest interpretations:

### 1. DeepSeek's free chat (chat.deepseek.com) vs Haiku
**Not relevant to NCL** — the consumer free chat isn't an API, can't be wired into the scheduler. The "DeepSeek free" path doesn't exist for programmatic use.

### 2. DeepSeek's API ($0.14/$0.28 per M) vs Haiku ($1.00/$5.00 per M)
**Yes — DeepSeek wins decisively.** Quality is comparable or better for the kinds of structured-output tasks NCL runs in Tier B (predictor JSON, classifier outputs, short summaries). The "frontier" gap that Anthropic charges for is in long-form reasoning and instruction-following at the edge — Haiku 4.5 was designed for those use cases. For predictor.py emitting `{ticker, direction, confidence}` JSON, that gap doesn't exist. **Switch all 13 of the 18 Tier B sites I tagged DEEPSEEK_V3 above. Saves ~$1.50/day on its own.**

### 3. Self-hosted DeepSeek (truly free at runtime) vs Haiku
**Mixed.** DeepSeek V3 full model is 671B MoE, doesn't fit in 64 GB. But:
- **DeepSeek-R1-Distill-Qwen-32B** (20 GB) DOES fit on your M1 Ultra. Runs at ~30 tok/sec via Ollama. Has reasoning chains that base Qwen3-32B doesn't. Free at runtime.
- **Better than Haiku for Tier C** (memory enrichment, narrative summarization, contradiction scanning) — quality close enough, latency tolerable for background tasks, zero marginal cost.
- **Worse than Haiku for Tier B hot paths** if latency matters — Ollama HTTP roundtrip ~150 ms vs DeepSeek API ~300 ms, but Groq absolutely demolishes both at ~50 ms for the same task.

---

## Revised savings projection (vs audit Phase 2 baseline)

| | Audit Phase 1 | Audit Phase 2 | **+ OSS addendum** |
|---|---:|---:|---:|
| Anthropic | $4.00/day | $2.00 | **$1.30** (only Tier A keeps it) |
| OpenAI | $0.87/day | $0.50 | **$0.20** (DeepSeek replaces most) |
| Perplexity | $1.20/day | $1.20 | **$0.30** (sonar-pro only on flagship research) |
| Google | $0.09/day | $0.09 | **$0.05** (Gemini stays for diversity) |
| **DeepSeek V3** | $0 | $0 | **$0.30** (new — replaces 13 Tier B sites) |
| **Groq Llama 3.3** | $0 | $0 | **$0.10** (new — /chat fallback + MapReduce) |
| YTC bucket | $0.42/day | $0.05 | **$0** (full Ollama switch) |
| Ollama (local) | $0 | $0 | $0 |
| **TOTAL** | **$6.58/day** | **$3.84** | **$2.25/day** |
| **vs $9.39/day baseline** | 30% saved | 59% saved | **76% saved** |

Adding DeepSeek + Groq to the mix saves an additional ~$1.60/day vs the audit's Phase 2, with the same one-week of effort. The added implementation cost is minimal — two new provider helpers in `llm/client.py` (each ~40 lines), one rebuild, done.

---

## What NOT to do, even though it's tempting

1. **Don't replace Sonnet 4 chair calls with hosted OSS.** Yes Llama 3.3 70B benchmarks close. No, the chair output quality difference is visible to NATRIX reading the brief twice a day. Spend the $0.40/day for Opus chair. Skim everywhere else.
2. **Don't add OpenRouter as the primary path.** Single point of failure across all OSS providers; outages are correlated. Use direct DeepSeek API + direct Groq + Ollama, in that order. Keep OpenRouter as an emergency third-tier fallback only.
3. **Don't replace Anthropic embeddings.** NCL doesn't use Anthropic embeddings — already uses ChromaDB's default model. Switching to nomic-embed-text is an improvement (quality + speed) but not a cost saving.
4. **Don't run DeepSeek-V3 full (671B) locally.** It won't fit, and quantizing it down to fit destroys the quality that makes it interesting. Pay $0.14/$0.28 per M and use the time you saved on better problems.
5. **Don't replace Whisper with anything.** `mlx-whisper` large-v3 is already free, already local, already running. Best-in-class for audio.

---

## Implementation order if shipping the OSS layer

If you want me to ship this, the order is:

1. **Add `DEEPSEEK_API_KEY` to `.env`** (sign up at platform.deepseek.com, ~30s) — $0 until first call
2. **Add `Provider.DEEPSEEK` to `runtime/llm/models.py`** — ~10 lines
3. **Add `_deepseek_call()` helper in `runtime/llm/client.py`** — ~40 lines, OpenAI-compatible shape so it's almost a copy of `_openai_call`
4. **Wire DeepSeek into `_dispatch_call()` model-name routing** — model strings like `deepseek-chat` and `deepseek-reasoner` route to the new helper
5. **Bulk-edit the 13 Tier B call sites** — change `claude-sonnet-4-20250514` → `deepseek-chat`
6. **Repeat steps 2-4 for Groq** — same shape, different endpoint
7. **Pull `deepseek-r1:32b` via Ollama** for the Tier C-R local reasoning slot (`ollama pull deepseek-r1:32b`, 20 GB download, ~10 min on home internet)
8. **Pre-commit run** + brain bounce + fire brief to verify nothing regressed

Total work: 4-6 hours including testing. Combined with the audit's Phase 1, you'd be at **~76% spend reduction** by end of day.

---

Sources:

- [DeepSeek API Pricing — official docs](https://api-docs.deepseek.com/quick_start/pricing)
- [Claude Haiku 4.5 pricing — Anthropic docs](https://platform.claude.com/docs/en/about-claude/pricing)
- [Groq on-demand pricing](https://groq.com/pricing)
- [Groq Llama 3.3 70B benchmark — 250 tok/sec](https://groq.com/blog/new-ai-inference-speed-benchmark-for-llama-3-3-70b-powered-by-groq)
- [DeepInfra pricing — $0.06/M small model floor](https://deepinfra.com/pricing)
- [Together AI vs DeepInfra comparison](https://pricepertoken.com/endpoints/compare/deepinfra-vs-together)
- [Best open-source LLM benchmarks May 2026](https://codersera.com/blog/best-open-source-llm-2026-llama-4-qwen-3-5-deepseek-v4-gemma-4-mistral/)
- [Open LLM Leaderboard 2026](https://llm-stats.com/leaderboards/open-llm-leaderboard)
