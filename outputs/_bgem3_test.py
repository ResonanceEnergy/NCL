import os
import sys


os.environ["NCL_MEMORY_EMBED_MODEL"] = "bge-m3"
sys.path.insert(0, "/Users/natrix/dev/NCL")
os.chdir("/Users/natrix/dev/NCL")
from runtime.memory.store import _load_chroma_embed_fn, _resolve_embed_model_id


print("model id:", _resolve_embed_model_id("bge-m3"))
fn = _load_chroma_embed_fn()
print("loaded:", fn is not None)
print("label:", getattr(fn, "_ncl_label", None))
if fn:
    out = fn(
        ["Fed signals June rate hold; markets shrug", "El BCE mantendrá tasas estables este mes"]
    )
    print(f"embedded {len(out)} texts; dim={len(out[0])}")
