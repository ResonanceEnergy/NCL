"""Future Predictor Council — DEPRECATED.

This module has been merged into ncl_agency_runtime.fpc.
All imports from future_predictor_council.src.* are shimmed
to ncl_agency_runtime.fpc.* for backward compatibility.
"""

import warnings as _warnings

_warnings.warn(
    "future_predictor_council.src is deprecated — use ncl_agency_runtime.fpc",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export everything from the new location
from ncl_agency_runtime.fpc import *  # noqa: F403, E402
from ncl_agency_runtime.fpc import __all__ as __all__  # noqa: E402
from ncl_agency_runtime.fpc import __version__ as __version__  # noqa: E402
