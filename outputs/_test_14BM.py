"""Wave 14BM smoke test — _ollama_call + _dispatch_call routing."""
import asyncio
import os
import sys
sys.path.insert(0, "/Users/natrix/dev/NCL")
from runtime.intelligence.brief_council import (
    _ollama_call,
    _dispatch_call,
    _resolve_council_models,
)

# 1. flag off → original models
os.environ.pop("NCL_BRIEF_COUNCIL_LOCAL_AB", None)
print("flag OFF:", _resolve_council_models())

# 2. flag on → local Ollama for pulse + flow
os.environ["NCL_BRIEF_COUNCIL_LOCAL_AB"] = "true"
print("flag ON :", _resolve_council_models())

# 3. direct Ollama call (qwen3:32b — small probe to keep it fast)
async def probe():
    text, in_tok, out_tok = await _ollama_call(
        "qwen3:8b",
        "Say exactly the three words: macro flow tech. Nothing else.",
        max_tokens=20,
        timeout_s=60.0,
        label="smoketest",
    )
    print(f"ollama qwen3:8b reply: {text!r} (in={in_tok} out={out_tok})")

    # 4. dispatch routes ollama: prefix
    text2, in2, out2 = await _dispatch_call(
        "ollama:qwen3:8b",
        "Reply with: ok",
        max_tokens=10,
        timeout_s=60.0,
        label="dispatch-probe",
    )
    print(f"dispatch ollama:qwen3:8b reply: {text2!r}")

asyncio.run(probe())
