"""CLI entry point — council backtest runner."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser(description="Future Predictor Council — CLI")
    parser.add_argument("--data", required=True, help="Path to panel CSV (unique_id, ds, y)")
    parser.add_argument("--freq", default="D", help="Frequency code (D, W, M)")
    parser.add_argument("--h", type=int, default=14, help="Forecast horizon")
    parser.add_argument("--foundation", choices=["on", "off"], default="off", help="Include foundation models")
    parser.add_argument("--output", default=None, help="Output path for backtest report CSV")
    parser.add_argument("--windows", type=int, default=5, help="Number of CV windows")
    args = parser.parse_args()

    # Load steering config
    config_path = pathlib.Path(__file__).resolve().parents[1] / "config" / "steering.json"
    if config_path.exists():
        _ = json.loads(config_path.read_text())  # reserved for future steering overrides

    # Build council
    from .council.base import ModelStrategy
    from .council.ensemble import WeightedEnsemble
    from .council.strategy_statsforecast import StatsForecastStrategy

    strategies: list[ModelStrategy] = [StatsForecastStrategy()]

    try:
        from .council.strategy_patchtst import PatchTSTStrategy
        strategies.append(PatchTSTStrategy())
    except ImportError:
        print("[warn] NeuralForecast not available — skipping PatchTST", file=sys.stderr)

    if args.foundation == "on":
        try:
            from .council.strategy_timesfm import TimesFMStrategy
            strategies.append(TimesFMStrategy())
        except ImportError:
            print("[warn] TimesFM not available — skipping", file=sys.stderr)
        try:
            from .council.strategy_chronos import ChronosStrategy
            strategies.append(ChronosStrategy())
        except ImportError:
            print("[warn] Chronos-2 not available — skipping", file=sys.stderr)

    ensemble = WeightedEnsemble(strategies)

    # Load data
    df = pd.read_csv(args.data)
    print(f"Loaded {len(df)} rows, {df['unique_id'].nunique()} series")

    # Rolling backtest
    from .eval.rolling_backtest import rolling_backtest

    result = rolling_backtest(
        strategy=ensemble,
        df=df,
        h=args.h,
        n_windows=args.windows,
        freq=args.freq,
    )

    print(f"\n{'='*50}")
    print(f"Avg MASE:  {result.avg_mase:.4f}")
    print(f"Avg sMAPE: {result.avg_smape:.2f}%")
    print(f"Windows:   {len(result.windows)}")
    print(f"Members:   {[s.name for s in strategies]}")
    print(f"{'='*50}")

    if args.output:
        report = pd.DataFrame(result.windows)
        report.to_csv(args.output, index=False)
        print(f"Report saved to {args.output}")


if __name__ == "__main__":
    main()
