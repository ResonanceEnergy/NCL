import os
os.environ["NCL_CROSS_REF_BERTOPIC_ENABLED"] = "true"
import sys
sys.path.insert(0, "/Users/natrix/dev/NCL")

from runtime.cross_reference import _extract_themes, _THEME_CLUSTERS
print("hardcoded clusters:", list(_THEME_CLUSTERS.keys()))
text = "Bitcoin market dump today, crypto in freefall after Fed"
extracted = _extract_themes(text, source="reddit")
print(f"extracted from text: {extracted}")
themes_active = {"bt:crypto bitcoin market", "crypto_macro"}
print(f"themes_active: {themes_active}")
print(f"intersection: {extracted & themes_active}")
