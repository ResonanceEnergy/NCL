"""Wave 14W-B verification — confirm thresholds + authority + memgate
loaded correctly from the agent module."""
import sys, os
sys.path.insert(0, "/Users/natrix/dev/NCL")
from runtime.awarebot.agent import (
    THRESHOLD_HIGH, THRESHOLD_CRITICAL, THRESHOLD_MEDIUM,
)

print(f"THRESHOLD_CRITICAL = {THRESHOLD_CRITICAL}")
print(f"THRESHOLD_HIGH     = {THRESHOLD_HIGH}")
print(f"THRESHOLD_MEDIUM   = {THRESHOLD_MEDIUM}")
print(f"NCL_AWAREBOT_HIGH_THRESHOLD env: {os.getenv('NCL_AWAREBOT_HIGH_THRESHOLD', '(unset → default)')}")
print(f"NCL_AUTH_GOOGLE_TRENDS env: {os.getenv('NCL_AUTH_GOOGLE_TRENDS', '(unset → default)')}")
print(f"NCL_AWAREBOT_MEM_GATE env: {os.getenv('NCL_AWAREBOT_MEM_GATE', '(unset → default ON)')}")
print(f"NCL_AWAREBOT_WC_INJECT env: {os.getenv('NCL_AWAREBOT_WC_INJECT', '(unset → default OFF)')}")
print(f"NCL_AWAREBOT_NEWS_ENABLED env: {os.getenv('NCL_AWAREBOT_NEWS_ENABLED', '(unset → default OFF)')}")
print(f"NCL_AWAREBOT_CITY_EVENTS_ENABLED env: {os.getenv('NCL_AWAREBOT_CITY_EVENTS_ENABLED', '(unset → default OFF)')}")
print(f"NCL_NARRATIVE_THREAD_IMPORTANCE_CAP env: {os.getenv('NCL_NARRATIVE_THREAD_IMPORTANCE_CAP', '(unset → default 60)')}")

# Sanity check authority
from runtime.awarebot.agent import _compute_source_authority
auth_gt = _compute_source_authority("google_trends", {})
auth_pm = _compute_source_authority("polymarket", {})
auth_rd = _compute_source_authority("reddit", {})
print(f"\nauth(google_trends) = {auth_gt:.3f} (expect ~0.40)")
print(f"auth(polymarket)    = {auth_pm:.3f} (expect ~0.85)")
print(f"auth(reddit)        = {auth_rd:.3f} (expect ~0.45)")
