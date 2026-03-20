"""Generate Helix News reference portrait library.

Calls Grok Imagine once per look to build a stock of reference images
in ncl_agency_runtime/fpc/helix_news/assets/helix_refs/.
Each image is saved alongside a catalogue entry in helix_refs.json
that records the outfit/angle description used — this is then
injected into scene prompts during daily brief generation so Helix
has a different look every episode.

Usage::

    cd C:\\dev\\NCL
    C:\\Python314\\python.exe _generate_helix_refs.py

Produces:
    assets/helix_refs/helix_ref_00.png  (original portrait)
    assets/helix_refs/helix_ref_01.png  ... helix_ref_12.png
    assets/helix_refs/helix_refs.json   (catalogue)
"""

import base64
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, ".")

# ── Load API keys ────────────────────────────────────────────────────────────
env_path = r"C:\dev\DIGITAL LABOUR\DIGITAL LABOUR\.env"
with open(env_path) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()

key = os.environ.get("GROK_API_KEY", "")
if not key:
    print("ERROR: GROK_API_KEY not found")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("helix_refs")

ASSETS_DIR = Path("ncl_agency_runtime/fpc/helix_news/assets/helix_refs")
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
CATALOGUE_PATH = ASSETS_DIR / "helix_refs.json"
GROK_MODEL = "grok-imagine-image"

# ── Reference definitions ────────────────────────────────────────────────────
# Each entry:
#   id        : used as filename helix_ref_{id:02d}.png
#   outfit    : injected into Grok prompts instead of the static description
#   angle     : camera framing description
#   lighting  : lighting mood
#   notes     : human-readable label shown in catalogue
HELIX_REFS = [
    # ── Existing assets (catalogue entries, images already on disk) ────────
    {
        "id": 0,
        "filename": "helix_portrait.png",
        "path": "../helix_portrait.png",
        "outfit": "sleek dark navy blazer with subtle circuit-pattern trim",
        "angle": "medium close-up, direct fourth-wall eye contact",
        "lighting": "neutral studio three-point lighting",
        "notes": "Original portrait — v1 reference",
    },
    {
        "id": 1,
        "filename": "helix_newsdesk.png",
        "path": "../helix_newsdesk.png",
        "outfit": "dark navy blazer, seated at illuminated glass anchor desk",
        "angle": "wide newsdesk shot, direct camera",
        "lighting": "blue and purple broadcast studio lighting",
        "notes": "Original newsdesk — v1 reference",
    },
    # ── New references (to be generated) ──────────────────────────────────
    {
        "id": 2,
        "outfit": "crimson structured blazer with chrome collar tabs",
        "angle": "medium shot, slight left profile, glancing at camera",
        "lighting": "warm golden key light from the right, deep shadow left",
        "notes": "Power red — formal authority look",
    },
    {
        "id": 3,
        "outfit": "white tailored suit jacket with fine silver pinstripe",
        "angle": "close-up portrait, straight-on, direct eye contact",
        "lighting": "cool white high-key broadcast lighting, minimal shadow",
        "notes": "Platinum white — clean authority",
    },
    {
        "id": 4,
        "outfit": "deep forest green blazer with iridescent lapels",
        "angle": "over-the-shoulder reverse angle, turning to face camera",
        "lighting": "cinematic teal and amber split lighting",
        "notes": "Emerald edge — cinematic broadcast",
    },
    {
        "id": 5,
        "outfit": "matte black blazer with subtle holographic thread weave",
        "angle": "wide anchor desk shot, leaning slightly forward, engaged",
        "lighting": "dramatic dark studio, neon blue rim light from behind",
        "notes": "Midnight black — breaking news urgency",
    },
    {
        "id": 6,
        "outfit": "structured cobalt blue blazer with silver shoulder piping",
        "angle": "low angle hero shot, looking slightly down at camera",
        "lighting": "purple studio backlighting, strong front fill",
        "notes": "Cobalt dominant — confident authority angle",
    },
    {
        "id": 7,
        "outfit": "charcoal grey double-breasted blazer with chrome buttons",
        "angle": "three-quarter shot at desk, hands visible on desk surface",
        "lighting": "classic newsroom warm tungsten fill, clean background",
        "notes": "Classic grey — traditional network anchor",
    },
    {
        "id": 8,
        "outfit": "ivory and silver brocade structured jacket, mandarin collar",
        "angle": "tight medium close-up, slightly tilted head, intense gaze",
        "lighting": "soft diffused window light from left, warm tone",
        "notes": "Ivory editorial — magazine anchor",
    },
    {
        "id": 9,
        "outfit": "burgundy blazer with dark velvet lapels",
        "angle": "wide shot, standing in front of newsroom monitors",
        "lighting": "evening broadcast warm amber tones, screens glowing behind",
        "notes": "Burgundy standing — evening news energy",
    },
    {
        "id": 10,
        "outfit": "slate blue utility blazer with geometric pattern stitching",
        "angle": "medium shot, turned slightly right, two-screen reflection visible",
        "lighting": "dual-screen bounce light giving cool blue fill, dark studio",
        "notes": "Slate utility — tech/cybersecurity segments",
    },
    {
        "id": 11,
        "outfit": "black and gold abstract print blazer, bold statement look",
        "angle": "close-up portrait, dramatic shadows, half-face composition",
        "lighting": "single harsh side key light from right, deep contrast",
        "notes": "Gold noir — dramatic special editions",
    },
]

# ── Prompt template ──────────────────────────────────────────────────────────
PROMPT_TEMPLATE = (
    "Helix, a professional AI news anchor, silver-chrome shoulder-length hair, "
    "sharp angular facial features, luminous blue eyes, "
    "wearing {outfit}, "
    "{angle}, "
    "futuristic HELIX NEWS broadcast studio background, "
    "{lighting}, "
    "photorealistic portrait, 16:9 aspect ratio, "
    "cinematic quality, ultra-detailed"
)


def call_grok_imagine(prompt: str, output_path: Path) -> bool:
    body = json.dumps(
        {
            "model": GROK_MODEL,
            "prompt": prompt,
            "n": 1,
            "response_format": "b64_json",
        }
    ).encode()

    req = urllib.request.Request(
        "https://api.x.ai/v1/images/generations",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "NCL-HelixRefs/1.0",
        },
        method="POST",
    )

    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode())
            images = data.get("data", [])
            if not images:
                logger.error("No images returned")
                return False
            img_b64 = images[0].get("b64_json", "")
            if img_b64:
                output_path.write_bytes(base64.b64decode(img_b64))
                logger.info("Saved: %s", output_path.name)
                return True
            img_url = images[0].get("url", "")
            if img_url:
                with urllib.request.urlopen(img_url, timeout=60) as r:
                    output_path.write_bytes(r.read())
                logger.info("Saved (url): %s", output_path.name)
                return True
            logger.error("No image data in response")
            return False
        except urllib.error.HTTPError as e:
            body_text = e.read().decode(errors="replace")[:300]
            logger.warning("HTTP %d (attempt %d/3): %s", e.code, attempt + 1, body_text)
            if e.code == 429:
                time.sleep(8 * (attempt + 1))
                continue
            return False
        except (urllib.error.URLError, TimeoutError) as e:
            logger.warning("Network error (attempt %d/3): %s", attempt + 1, e)
            time.sleep(5)
    return False


def main() -> None:
    catalogue = []

    for ref in HELIX_REFS:
        ref_id = ref["id"]
        notes = ref["notes"]

        # Existing assets — just add catalogue entry, no API call needed
        if "path" in ref:
            existing = ASSETS_DIR.parent / ref["path"].lstrip("../")
            catalogue.append(
                {
                    "id": ref_id,
                    "filename": ref["filename"],
                    "path": str(ASSETS_DIR.parent / ref["filename"]),
                    "outfit": ref["outfit"],
                    "angle": ref["angle"],
                    "lighting": ref["lighting"],
                    "notes": notes,
                    "prompt": None,
                }
            )
            logger.info("Catalogued existing: %s — %s", ref["filename"], notes)
            continue

        # New reference — generate via Grok Imagine
        filename = f"helix_ref_{ref_id:02d}.png"
        output_path = ASSETS_DIR / filename

        if output_path.exists():
            logger.info("Already exists, skipping: %s", filename)
        else:
            prompt = PROMPT_TEMPLATE.format(
                outfit=ref["outfit"],
                angle=ref["angle"],
                lighting=ref["lighting"],
            )
            logger.info("Generating ref %02d: %s", ref_id, notes)
            logger.info("Prompt: %s", prompt[:120])
            success = call_grok_imagine(prompt, output_path)

            if not success:
                logger.error("FAILED: helix_ref_%02d.png", ref_id)
                # Don't add failed entries to catalogue
                time.sleep(3)
                continue

            time.sleep(3)  # rate limit protection between calls

        prompt_used = PROMPT_TEMPLATE.format(
            outfit=ref["outfit"],
            angle=ref["angle"],
            lighting=ref["lighting"],
        )
        catalogue.append(
            {
                "id": ref_id,
                "filename": filename,
                "path": str(output_path),
                "outfit": ref["outfit"],
                "angle": ref["angle"],
                "lighting": ref["lighting"],
                "notes": notes,
                "prompt": prompt_used,
            }
        )

    # Write catalogue
    CATALOGUE_PATH.write_text(json.dumps(catalogue, indent=2), encoding="utf-8")
    logger.info("Catalogue written: %s (%d entries)", CATALOGUE_PATH, len(catalogue))

    print(f"\n{'=' * 60}")
    print(f"HELIX REFERENCE LIBRARY — {len(catalogue)} images catalogued")
    print(f"Catalogue: {CATALOGUE_PATH}")
    print(f"Assets:    {ASSETS_DIR}")
    print(f"{'=' * 60}")
    for entry in catalogue:
        size = ""
        p = Path(entry["path"])
        if p.exists():
            size = f"{p.stat().st_size // 1024}KB"
        print(f"  ref_{entry['id']:02d}  {entry['notes']}  {size}")


if __name__ == "__main__":
    main()
