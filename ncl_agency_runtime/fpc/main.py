#!/usr/bin/env python3
"""future-predictor-council — unified CLI entrypoint.

Commands
--------
council <topic>         Run a council prediction session (classic mode)
think <topic>           Run ICM thinking pipeline (ICM + OpenClaw + Ralphy)
channels                List configured delivery channels
evolve                  Run Ralphy self-evolution analysis
backtest                Run rolling backtest on time-series data
ingest                  Fetch signals from configured RSS/API sources
serve                   Start the FastAPI server
status                  Print flywheel status
dashboard               Personal analysis command center
alerts                  View/manage active alerts
rank                    Ranked prediction leaderboard by impact score
scrape                  Run tiered data scraper
helix                   Produce a Helix News episode (full pipeline)
helix-script            Generate the broadcast script only
helix-audio             Generate script + TTS audio
schedule                Manage background task scheduler
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
    from .flywheel_feed import emit_status
    from .heuristic_council import FuturePredictorCouncil, PredictionHorizon
    from .reports import ReportGenerator
    from .tracker import PredictionTracker

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
    from pathlib import Path

    import pandas as pd

    from .eval import rolling_backtest
    from .flywheel_feed import emit_status
    from .forecasting import StatsForecastStrategy
    from .reports import ReportGenerator

    emit_status("backtest", f"Running h={args.h}, freq={args.freq}")
    df = pd.read_csv(args.data, parse_dates=["ds"])
    model = StatsForecastStrategy(season_length=args.season)
    report = rolling_backtest(
        df, model, freq=args.freq, h=args.h, n_windows=args.windows, seasonal_m=args.season
    )

    Path("data/artifacts").mkdir(parents=True, exist_ok=True)
    out = "data/artifacts/backtest_report.csv"
    report.to_csv(out, index=False)

    rg = ReportGenerator()
    rg.generate_backtest_report(report)

    emit_status("idle", f"Backtest complete — {out}")
    print(report.to_string(index=False))
    print(f"\nSaved: {out}")


def cmd_ingest(args):
    from .flywheel_feed import emit_status
    from .ingestion import IngestionPipeline

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
    uvicorn.run("future_predictor_council.src.serve.api:app", host=args.host, port=int(args.port), reload=args.reload)


def cmd_status(_args):
    from .flywheel_feed import read_status

    print(json.dumps(read_status(), indent=2))


def cmd_think(args):
    from .flywheel_feed import emit_status
    from .heuristic_council import FuturePredictorCouncil, PredictionHorizon

    horizon_map = {
        "short": PredictionHorizon.SHORT_TERM,
        "medium": PredictionHorizon.MEDIUM_TERM,
        "long": PredictionHorizon.LONG_TERM,
        "strategic": PredictionHorizon.STRATEGIC,
    }

    emit_status("thinking", f"ICM pipeline for: {args.topic}")
    council = FuturePredictorCouncil(args.config)
    result = council.think(
        topic=args.topic,
        horizon=horizon_map[args.horizon],
        channels=args.channels.split(",") if args.channels else None,
        run_evolution=not args.no_evolution,
    )

    emit_status("idle", "Thinking complete")
    print(json.dumps(result, indent=2, default=str))


def cmd_evolve(_args):
    from .ralphy_evolution import RalphyEvolution

    evo = RalphyEvolution()
    report = evo.analyze()

    print(f"Evolution Analysis — {report.timestamp}")
    print(f"  Predictions analyzed: {report.predictions_analyzed}")
    print(f"  Accuracy: {report.accuracy:.0%}")
    print(f"  Strengths: {len(report.strengths)}")
    for s in report.strengths:
        print(f"    + {s}")
    print(f"  Weaknesses: {len(report.weaknesses)}")
    for w in report.weaknesses:
        print(f"    - {w}")
    print(f"  Tasks generated: {len(report.tasks_generated)}")
    print("  Recommendations:")
    for r in report.recommendations:
        print(f"    > {r}")


def cmd_channels(_args):
    from .thinking import ThinkingLayer

    thinking = ThinkingLayer()
    gateway = thinking.gateway
    status = gateway.get_gateway_status()

    print("Delivery Channels")
    print("=" * 40)

    channels_cfg = gateway._channels
    if not channels_cfg:
        print("  No channels configured.")
        print("  Edit config/thinking_config.json to add channels.")
        return

    for name, cfg in channels_cfg.items():
        enabled = cfg.get("enabled", True)
        marker = "[ON]" if enabled else "[OFF]"
        print(f"  {marker} {name}")

        if name == "file":
            print(f"       output_dir: {cfg.get('output_dir', 'reports')}")
        elif name == "discord":
            has_url = bool(cfg.get("webhook_url", ""))
            print(f"       webhook_url: {'configured' if has_url else 'not set'}")
        elif name == "telegram":
            has_token = bool(cfg.get("bot_token", ""))
            has_chat = bool(cfg.get("chat_id", ""))
            print(f"       bot_token: {'configured' if has_token else 'not set'}")
            print(f"       chat_id: {'configured' if has_chat else 'not set'}")
        elif name == "slack":
            has_url = bool(cfg.get("webhook_url", ""))
            print(f"       webhook_url: {'configured' if has_url else 'not set'}")

        fmt = cfg.get("format", "summary")
        if name != "file":
            print(f"       format: {fmt}")

    print()
    print(f"Gateway URL: {status['gateway_url']}")
    connected = gateway.check_connection()
    print(f"Gateway reachable: {'yes' if connected else 'no'}")


def cmd_dashboard(_args):
    from .alerting import AlertEngine
    from .dashboard import Dashboard

    # Run alert scan first to catch any new conditions
    engine = AlertEngine()
    engine.scan()

    dash = Dashboard()
    print(dash.render_full())


def cmd_alerts(args):
    from .alerting import AlertEngine
    from .dashboard import Dashboard

    engine = AlertEngine()

    if args.ack:
        if engine.acknowledge(args.ack):
            print(f"Acknowledged: {args.ack}")
        else:
            print(f"Alert not found: {args.ack}")
        return

    if args.ack_all:
        count = engine.acknowledge_all(level=args.level)
        print(f"Acknowledged {count} alerts")
        return

    if args.scan:
        new = engine.scan()
        print(f"Scan complete — {len(new)} new alerts generated")

    dash = Dashboard()
    print(dash.render_alerts(level=args.level))


def cmd_rank(args):
    from .dashboard import Dashboard

    dash = Dashboard()
    print(dash.render_ranked(include_resolved=args.all, limit=args.limit))


def cmd_scrape(args):
    from .flywheel_feed import emit_status
    from .scraper import TopicScraper

    scraper = TopicScraper(config_path=args.config)

    if args.status:
        status = scraper.cache_status()
        print(json.dumps(status, indent=2, default=str))
        return

    if args.tier:
        emit_status("scraping", f"Scraping tier: {args.tier}")
        signals = scraper.scrape_tier(args.tier, free_only=not args.all_sources)
        emit_status("idle", f"Scraped {len(signals)} signals from {args.tier}")
        print(f"Tier {args.tier}: {len(signals)} signals collected")
    elif args.due:
        emit_status("scraping", "Scraping all due tiers")
        results = scraper.scrape_due(free_only=not args.all_sources)
        emit_status("idle", "Scheduled scrape complete")
        for tier, info in results.items():
            if isinstance(info, dict) and info.get("scraped"):
                print(f"  {tier}: {info['signal_count']} signals ✓")
            elif isinstance(info, dict):
                print(f"  {tier}: not due ({info.get('days_remaining', '?')}d remaining)")
    else:
        # Default: scrape all tiers
        emit_status("scraping", "Scraping all tiers")
        results = scraper.scrape_all(free_only=not args.all_sources)
        emit_status("idle", "Full scrape complete")
        total = sum(results.values())
        for tier, count in results.items():
            print(f"  {tier}: {count} signals")
        print(f"  Total: {total} signals across {len(results)} tiers")


def cmd_helix(args):
    """Produce a full Helix News episode."""
    from .helix_news.producer import Producer

    producer = Producer(args.config)
    result = producer.produce()
    video = result.get("final_video")
    if video:
        print(f"\n✅ Episode ready: {video}")
    else:
        print(f"\n⚠️  Pipeline incomplete: {result.get('error', 'check logs')}")
        script = result.get("stages", {}).get("script", {})
        if script.get("full_text"):
            print(f"Script generated at: {script.get('episode_id', '?')}")


def cmd_helix_script(args):
    """Generate broadcast script only (no GPU needed)."""
    from .helix_news.script_generator import ScriptGenerator

    gen = ScriptGenerator(args.config)
    script = gen.generate()
    print(f"\n{'='*60}")
    print(f"HELIX NEWS — {script.get('date', 'Today')}")
    print(f"{'='*60}\n")
    print(script["full_text"])
    print(f"\n{'='*60}")
    print(f"Words: {script['total_words']} | Est: {script['est_duration_display']}")
    print(f"Segments: {len(script['segments'])}")


def cmd_helix_audio(args):
    """Generate script + TTS audio (needs edge-tts)."""
    from .helix_news.producer import Producer

    producer = Producer(args.config)
    script = producer.run_script()
    audio = producer.run_audio(script)
    print(f"\nGenerated {len(audio)} audio segments in: {producer.episode_dir / 'audio'}")
    for name, result in audio.items():
        path = result.get("audio", "failed")
        print(f"  {name}: {path}")


def cmd_schedule(args):
    """Manage the background scheduler."""
    from .scheduler import Scheduler

    scheduler = Scheduler()

    if args.list:
        tasks = scheduler.list_tasks()
        print("Scheduled Tasks")
        print("=" * 50)
        for t in tasks:
            marker = "[ON]" if t["enabled"] else "[OFF]"
            interval = t["interval_minutes"]
            unit = "min" if interval < 60 else f"{interval // 60}h"
            if interval >= 1440:
                unit = f"{interval // 1440}d"
            print(f"  {marker} {t['name']:<20} every {unit:<6} cmd: {t['command']}")
            if t["last_run"]:
                print(f"       last run: {t['last_run']} ({t['last_status']})")
        return

    if args.run_once:
        print("Running all enabled tasks once...")
        scheduler.run_once()
        for t in scheduler.list_tasks():
            if t["last_run"]:
                print(f"  {t['name']}: {t['last_status']}")
        return

    # Default: start scheduler daemon
    print("Starting FPC scheduler (Ctrl+C to stop)...")
    print("Enabled tasks:")
    for t in scheduler.list_tasks():
        if t["enabled"]:
            interval = t["interval_minutes"]
            print(f"  {t['name']} — every {interval} min")
    scheduler.start()


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

    # think (ICM + OpenClaw + Ralphy pipeline)
    p_think = sub.add_parser("think", help="Run ICM thinking pipeline")
    p_think.add_argument("topic", help="Topic to analyse")
    p_think.add_argument(
        "--horizon", choices=["short", "medium", "long", "strategic"], default="medium"
    )
    p_think.add_argument("--config", default="config/council_config.json")
    p_think.add_argument("--channels", default=None, help="Comma-separated delivery channels")
    p_think.add_argument("--no-evolution", action="store_true", help="Skip evolution analysis")

    # channels (list/manage delivery channels)
    sub.add_parser("channels", help="List configured delivery channels")

    # evolve (Ralphy self-assessment)
    sub.add_parser("evolve", help="Run Ralphy evolution analysis")

    # dashboard (personal command center)
    sub.add_parser("dashboard", help="Personal analysis command center")

    # alerts (view/manage alerts)
    p_alerts = sub.add_parser("alerts", help="View and manage alerts")
    p_alerts.add_argument("--ack", default=None, help="Acknowledge alert by ID")
    p_alerts.add_argument("--ack-all", action="store_true", help="Acknowledge all active alerts")
    p_alerts.add_argument("--level", choices=["CRITICAL", "HIGH", "MEDIUM", "LOW"],
                          default=None, help="Filter by alert level")
    p_alerts.add_argument("--scan", action="store_true", help="Run alert scan first")

    # rank (prediction leaderboard)
    p_rank = sub.add_parser("rank", help="Ranked prediction leaderboard")
    p_rank.add_argument("--all", action="store_true", help="Include resolved predictions")
    p_rank.add_argument("--limit", type=int, default=25, help="Max predictions to show")

    # scrape (tiered data collection from MASTER_TOPICS.json)
    p_scrape = sub.add_parser("scrape", help="Run tiered data scraper")
    p_scrape.add_argument(
        "--tier",
        choices=["tier_1_daily", "tier_2_weekly", "tier_3_monthly", "tier_4_quarterly"],
        default=None,
        help="Scrape a specific tier only",
    )
    p_scrape.add_argument("--due", action="store_true", help="Only scrape tiers that are due")
    p_scrape.add_argument("--status", action="store_true", help="Show cache status")
    p_scrape.add_argument("--all-sources", action="store_true", help="Include API-key sources (not just free)")
    p_scrape.add_argument("--config", default="config/council_config.json")

    # helix (full pipeline)
    p_helix = sub.add_parser("helix", help="Produce a Helix News episode")
    p_helix.add_argument("--config", default="config/helix_news.json")

    # helix-script (script only — no GPU)
    p_hs = sub.add_parser("helix-script", help="Generate broadcast script only")
    p_hs.add_argument("--config", default="config/helix_news.json")

    # helix-audio (script + TTS — needs edge-tts)
    p_ha = sub.add_parser("helix-audio", help="Generate script + TTS audio")
    p_ha.add_argument("--config", default="config/helix_news.json")

    # schedule (background scheduler)
    p_sched = sub.add_parser("schedule", help="Manage background task scheduler")
    p_sched.add_argument("--list", action="store_true", help="List scheduled tasks")
    p_sched.add_argument("--run-once", action="store_true", help="Run all enabled tasks once immediately")

    args = parser.parse_args()

    dispatch = {
        "council": cmd_council,
        "backtest": cmd_backtest,
        "ingest": cmd_ingest,
        "serve": cmd_serve,
        "status": cmd_status,
        "think": cmd_think,
        "evolve": cmd_evolve,
        "channels": cmd_channels,
        "dashboard": cmd_dashboard,
        "alerts": cmd_alerts,
        "rank": cmd_rank,
        "scrape": cmd_scrape,
        "helix": cmd_helix,
        "helix-script": cmd_helix_script,
        "helix-audio": cmd_helix_audio,
        "schedule": cmd_schedule,
    }

    handler = dispatch.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
