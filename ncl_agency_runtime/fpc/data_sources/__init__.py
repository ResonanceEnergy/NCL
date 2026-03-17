"""Data source ingesters — 60+ APIs across finance, climate, health, and more."""

from .economic import FRED_INDICATORS, AlphaVantageIngester, FREDIngester  # noqa: F401
from .registry import IngesterRegistry, run_all_ingesters  # noqa: F401
