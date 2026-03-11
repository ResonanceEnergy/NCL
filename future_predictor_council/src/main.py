#!/usr/bin/env python3
"""future-predictor-council — unified CLI entrypoint.

Commands
--------
council <topic>         Run a council prediction session
backtest                Run rolling backtest on time-series data
ingest                  Fetch signals from configured RSS/API sources
serve                   Start the FastAPI server
status                  Print flywheel status
"""

import argparse
import json
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("fpc")


def cmd_council(args):
    from .council_orchestrator import FuturePredictorCouncil, PredictionHorizon
    from .reports import ReportGenerator
    from .tracker import PredictionTracker
    from .flywheel_feed import emit_status

    horizon_map = {
        "short": PredictionHorizon.SHORT_TERM,
        "medium": PredictionHorizon.MEDIUM_TERM,
        "long": PredictionHorizon.LONG_TERM,
        "strategic": PredictionHorizon.STRATEGIC,
    }

    emit_status("council", f"Convening on: {args.topic}")
    council = FuturePredictorCouncil(args.config)
    result = council.convene_council(args.topic, horizon_map[args.horizon])

    # Track predictions
    tracker = PredictionTracker()
    for pred in result.get("predictions", []):
        tracker.record(pred)

    # Generate reports
    rg = ReportGenerator()
    paths = rg.generate(result)
    emit_status("idle", f"Council complete — {paths['md_path']}")

    print(json.dumps(result, indent=2, default=str))


def cmd_backtest(args):
    import pandas as pd
    from pathlib import Path
    from .council.strategy_statsforecast import StatsForecastStrategy
    from .eval.rolling_backtest import rolling_backtest
    from .reports import ReportGenerator
    from .flywheel_feed import emit_status

    emit_status("backtest", f"Running h={args.h}, freq={args.freq}")
    df = pd.read_csv(args.data, parse_dates=["ds"])
    model = StatsForecastStrategy(season_length=args.season)
    result = rolling_backtest(
        model, df, h=args.h, n_windows=args.windows, freq=args.freq, seasonality=args.season
    )

    Path("data/artifacts").mkdir(parents=True, exist_ok=True)
    out = "data/artifacts/backtest_report.csv"
    report_df = pd.DataFrame(result.windows)
    report_df.to_csv(out, index=False)

    rg = ReportGenerator()
    rg.generate_backtest_report(report_df)

    emit_status("idle", f"Backtest complete — {out}")
    print(report_df.to_string(index=False))
    print(f"\nAvg MASE: {result.avg_mase:.4f}  Avg sMAPE: {result.avg_smape:.4f}")
    print(f"Saved: {out}")


def cmd_ingest(args):
    from .ingestion import IngestionPipeline
    from .flywheel_feed import emit_status

    emit_status("ingestion", "Fetching signals")
    pipeline = IngestionPipeline(args.config)
    signals = pipeline.run()
    emit_status("idle", f"Ingested {len(signals)} signals")
    for s in signals[:10]:
        print(f"  [{s.source[:40]}] {s.title[:80]}")
    if len(signals) > 10:
        print(f"  ... and {len(signals) - 10} more")


def cmd_serve(args):
    import uvicorn

    logger.info("Starting API server on %s:%d", args.host, args.port)
    uvicorn.run(
        "future_predictor_council.src.serve:app",
        host=args.host,
        port=int(args.port),
        reload=args.reload,
    )


def cmd_status(_args):
    from .flywheel_feed import read_status

    print(json.dumps(read_status(), indent=2))


def main():
    parser = argparse.ArgumentParser(
        prog="fpc",
        description="Future Predictor Council — unified CLI",
    )
    sub = parser.add_subparsers(dest="command")

    # council
    p_council = sub.add_parser("council", help="Run a council prediction session")
    p_council.add_argument("topic", help="Topic to analyse")
    p_council.add_argument(
        "--horizon", choices=["short", "medium", "long", "strategic"], default="medium"
    )
    p_council.add_argument("--config", default="config/council_config.json")

    # backtest
    p_bt = sub.add_parser("backtest", help="Run rolling backtest")
    p_bt.add_argument("--data", default="data/raw/example.csv")
    p_bt.add_argument("--freq", default="D")
    p_bt.add_argument("--h", type=int, default=14)
    p_bt.add_argument("--windows", type=int, default=3)
    p_bt.add_argument("--season", type=int, default=7)

    # ingest
    p_ing = sub.add_parser("ingest", help="Fetch signals from configured sources")
    p_ing.add_argument("--config", default="config/council_config.json")

    # serve
    p_srv = sub.add_parser("serve", help="Start FastAPI server")
    p_srv.add_argument("--host", default="0.0.0.0")
    p_srv.add_argument("--port", type=int, default=8000)
    p_srv.add_argument("--reload", action="store_true")

    # status
    sub.add_parser("status", help="Print flywheel status")

    args = parser.parse_args()

    dispatch = {
        "council": cmd_council,
        "backtest": cmd_backtest,
        "ingest": cmd_ingest,
        "serve": cmd_serve,
        "status": cmd_status,
    }

    handler = dispatch.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()
        sys.exit(1)
