"""Forecasting strategies — statistical, neural, and foundation model backends."""
from .base import ForecastResult, ModelStrategy


def StatsForecastStrategy(*args, **kwargs):
    """Lazy import to avoid hard dependency on statsforecast at import time."""
    from .strategy_statsforecast import StatsForecastStrategy as _Cls
    return _Cls(*args, **kwargs)


def ChronosStrategy(*args, **kwargs):
    """Lazy import — requires ``pip install chronos-forecasting torch``."""
    from .strategy_chronos import ChronosStrategy as _Cls
    return _Cls(*args, **kwargs)


def TimesFMStrategy(*args, **kwargs):
    """Lazy import — requires ``pip install timesfm``."""
    from .strategy_timesfm import TimesFMStrategy as _Cls
    return _Cls(*args, **kwargs)


def ProphetStrategy(*args, **kwargs):
    """Lazy import — requires ``pip install prophet``."""
    from .strategy_prophet import ProphetStrategy as _Cls
    return _Cls(*args, **kwargs)


def NeuralForecastStrategy(*args, **kwargs):
    """Lazy import — requires ``pip install neuralforecast``."""
    from .strategy_neuralforecast import NeuralForecastStrategy as _Cls
    return _Cls(*args, **kwargs)


__all__ = [
    "ChronosStrategy",
    "ForecastResult",
    "ModelStrategy",
    "NeuralForecastStrategy",
    "ProphetStrategy",
    "StatsForecastStrategy",
    "TimesFMStrategy",
]
