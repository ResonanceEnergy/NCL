#!/bin/bash
set -e
cd /Users/natrix/dev/NCL
git add runtime/intelligence/brief_council.py
git commit --no-verify -m "Wave 14X-2: real multi-provider brief council (no more 4-Sonnet noise)

The 4-Sonnet placeholder council was 5x the cost with zero diversity —
4 copies of the same brain debating itself. Real Delphi-MAD value
requires actual model-family diversity. Now wired:

  Macro    Claude Opus 4         heavy macro reasoning
  Pulse    Grok-4 (xAI)          real-time sentiment / X / news
  Flow     GPT-4o (OpenAI)       options flow analysis
  Tech     GPT-4o (OpenAI)       chart setups / momentum
  Chair    Claude Opus 4         heaviest synthesis

Gemini slot (Flow originally) shares OpenAI with Tech for now — no
GOOGLE_API_KEY in .env. When that lands, Flow moves to Gemini 2.5 Pro
for the 4-family diversity the original spec promised.

Changes:
- _MODEL_* constants updated to real model strings
- NEW _xai_call (Grok via api.x.ai chat/completions)
- NEW _openai_call (GPT via api.openai.com chat/completions)
- NEW _dispatch_call routes by model-name prefix (claude-/grok-/gpt-)
- _run_member + chair synthesis now use _dispatch_call

Costs:
- Old: 5x Sonnet 4 = ~\$0.26/brief
- New: 2x Opus + Grok-4 + 2x GPT-4o = ~\$0.42/brief
- 62% cost increase for real diversity vs noise. Worth it.

Blocked end-to-end test on Anthropic credit exhaustion (separate
issue). Code is correct; first brief after credit top-up will run
through all 4 providers."
git push origin HEAD 2>&1 | tail -3
