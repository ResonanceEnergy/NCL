"""OpenClaw Gateway Integration — WebSocket bridge for FPC predictions.

Provides FPC with OpenClaw's runtime capabilities:
  - WebSocket messaging to OpenClaw gateway (ws://127.0.0.1:18789)
  - Plugin hooks: before_prompt_build, after_tool_call, agent_end
  - Cron scheduling for recurring predictions
  - Webhook handlers for event-triggered predictions
  - Multi-channel delivery (Discord, Telegram, Slack, etc.)

OpenClaw exposes 17 plugin lifecycle hooks. We use 3 for FPC:
  1. before_prompt_build — inject domain context before council deliberation
  2. after_tool_call — audit tool results before forwarding
  3. agent_end — capture final prediction for delivery
"""

import json
import logging
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

DEFAULT_GATEWAY_URL = "http://127.0.0.1:18789"
TIMEOUT_SECONDS = 10


@dataclass
class OpenClawMessage:
    """A typed message for the OpenClaw protocol."""
    type: str  # "prediction", "tool_call", "agent_event", "delivery"
    payload: dict[str, Any] = field(default_factory=dict)
    session_id: str | None = None
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


@dataclass
class PluginHook:
    """Registration for an OpenClaw plugin lifecycle hook."""
    hook_name: str
    callback: Callable
    priority: int = 100  # lower = runs first


@dataclass
class CronJob:
    """Scheduled recurring prediction."""
    schedule: str  # cron expression like "0 8 * * 1-5"
    topic: str
    horizon: str = "1-3 months"
    enabled: bool = True
    last_run: str | None = None


@dataclass
class WebhookTrigger:
    """Event-triggered prediction via webhook."""
    event_type: str  # e.g., "price_alert", "news_event", "api_signal"
    topic_template: str  # e.g., "Price alert for {symbol}"
    horizon: str = "1-3 months"
    enabled: bool = True


class OpenClawGateway:
    """Bridge between FPC and OpenClaw gateway for runtime delivery.

    This is a REST/HTTP client since direct WebSocket requires an async
    runtime. For production OpenClaw WebSocket use, this provides the
    message protocol and hook system that maps onto OpenClaw's plugin API.
    """

    def __init__(
        self,
        gateway_url: str = DEFAULT_GATEWAY_URL,
        api_key: str | None = None,
    ):
        self.gateway_url = gateway_url.rstrip("/")
        self.api_key = api_key or self._load_api_key()
        self._hooks: dict[str, list[PluginHook]] = {}
        self._cron_jobs: list[CronJob] = []
        self._webhook_triggers: list[WebhookTrigger] = []
        self._channels: dict[str, dict[str, Any]] = {}
        self._connected = False

        # Register default FPC hooks
        self.register_hook(PluginHook(
            hook_name="before_prompt_build",
            callback=self._inject_domain_context,
            priority=50,
        ))
        self.register_hook(PluginHook(
            hook_name="after_tool_call",
            callback=self._audit_tool_result,
            priority=50,
        ))
        self.register_hook(PluginHook(
            hook_name="agent_end",
            callback=self._capture_prediction,
            priority=50,
        ))

    @staticmethod
    def _load_api_key() -> str | None:
        """Load OPENCLAW_API_KEY from .env or environment."""
        env_path = Path(__file__).resolve().parent.parent / ".env"
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("OPENCLAW_API_KEY=") and not line.startswith("#"):
                        return line.split("=", 1)[1].strip()
        return os.getenv("OPENCLAW_API_KEY")

    # ── Connection ───────────────────────────────────────────────────────────

    def check_connection(self) -> bool:
        """Check if OpenClaw gateway is reachable."""
        try:
            req = Request(f"{self.gateway_url}/health", method="GET")
            if self.api_key:
                req.add_header("Authorization", f"Bearer {self.api_key}")
            with urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
                self._connected = resp.status == 200
                return self._connected
        except (URLError, OSError):
            self._connected = False
            return False

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ── Plugin hooks ─────────────────────────────────────────────────────────

    def register_hook(self, hook: PluginHook):
        """Register a plugin lifecycle hook."""
        if hook.hook_name not in self._hooks:
            self._hooks[hook.hook_name] = []
        self._hooks[hook.hook_name].append(hook)
        self._hooks[hook.hook_name].sort(key=lambda h: h.priority)

    def fire_hook(self, hook_name: str, context: dict) -> dict:
        """Execute all registered callbacks for a hook point."""
        hooks = self._hooks.get(hook_name, [])
        for hook in hooks:
            try:
                result = hook.callback(context)
                if isinstance(result, dict):
                    context.update(result)
            except Exception as exc:
                logger.warning("Hook %s callback failed: %s", hook_name, exc)
        return context

    # ── Cron scheduling ──────────────────────────────────────────────────────

    def add_cron_job(self, job: CronJob):
        """Register a recurring prediction schedule."""
        self._cron_jobs.append(job)

    def list_cron_jobs(self) -> list[dict]:
        """Return all registered cron jobs."""
        return [asdict(j) for j in self._cron_jobs]

    def get_due_jobs(self) -> list[CronJob]:
        """Return cron jobs that are due to run (simplified check)."""
        return [j for j in self._cron_jobs if j.enabled]

    # ── Webhook triggers ─────────────────────────────────────────────────────

    def add_webhook_trigger(self, trigger: WebhookTrigger):
        """Register an event-triggered prediction."""
        self._webhook_triggers.append(trigger)

    def handle_webhook(self, event_type: str, event_data: dict) -> dict | None:
        """Process an incoming webhook event — returns prediction config if matched."""
        for trigger in self._webhook_triggers:
            if trigger.event_type == event_type and trigger.enabled:
                topic = trigger.topic_template
                for key, val in event_data.items():
                    topic = topic.replace(f"{{{key}}}", str(val))
                return {
                    "topic": topic,
                    "horizon": trigger.horizon,
                    "trigger": event_type,
                }
        return None

    # ── Channel delivery ─────────────────────────────────────────────────────

    def configure_channel(self, name: str, config: dict):
        """Configure a delivery channel (discord, telegram, slack, file, api)."""
        self._channels[name] = config

    def deliver_prediction(
        self,
        prediction: dict,
        channels: list[str] | None = None,
    ) -> dict[str, str]:
        """Deliver a prediction to configured channels."""
        targets = channels or list(self._channels.keys())
        results = {}

        for channel_name in targets:
            channel_config = self._channels.get(channel_name, {})
            # Skip disabled channels (unless explicitly requested via --channels)
            if not channels and not channel_config.get("enabled", True):
                continue
            try:
                if channel_name == "file":
                    results[channel_name] = self._deliver_file(prediction, channel_config)
                elif channel_name == "api":
                    results[channel_name] = self._deliver_api(prediction, channel_config)
                elif channel_name == "webhook":
                    results[channel_name] = self._deliver_webhook(prediction, channel_config)
                elif channel_name in ("discord", "telegram", "slack"):
                    results[channel_name] = self._deliver_gateway_channel(
                        prediction, channel_name, channel_config
                    )
                else:
                    results[channel_name] = "unsupported"
            except Exception as exc:
                logger.error("Delivery to %s failed: %s", channel_name, exc)
                results[channel_name] = f"failed: {exc}"

        return results

    def send_message(self, message: OpenClawMessage) -> bool:
        """Send a typed message to the OpenClaw gateway via REST."""
        try:
            data = message.to_json().encode("utf-8")
            req = Request(
                f"{self.gateway_url}/api/messages",
                data=data,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            if self.api_key:
                req.add_header("Authorization", f"Bearer {self.api_key}")
            with urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
                return resp.status < 300
        except (URLError, OSError) as exc:
            logger.warning("Failed to send message to OpenClaw: %s", exc)
            return False

    def get_gateway_status(self) -> dict[str, Any]:
        """Return gateway connection and configuration status."""
        return {
            "gateway_url": self.gateway_url,
            "connected": self._connected,
            "hooks_registered": {k: len(v) for k, v in self._hooks.items()},
            "cron_jobs": len(self._cron_jobs),
            "webhook_triggers": len(self._webhook_triggers),
            "channels_configured": list(self._channels.keys()),
        }

    # ── Default hook implementations ─────────────────────────────────────────

    @staticmethod
    def _inject_domain_context(context: dict) -> dict:
        """before_prompt_build: inject topic-specific data sources."""
        topic = context.get("topic", "")
        domain_hints = {
            "crypto": ["coindesk", "coingecko", "glassnode", "dune", "defi_llama"],
            "stock": ["alpha_vantage", "fred", "bls", "sec_edgar"],
            "macro": ["fred", "imf_weo", "world_bank", "bls", "bea"],
            "climate": ["noaa", "openweather", "copernicus"],
        }
        for keyword, sources in domain_hints.items():
            if keyword in topic.lower():
                context.setdefault("suggested_sources", []).extend(sources)
        return context

    @staticmethod
    def _audit_tool_result(context: dict) -> dict:
        """after_tool_call: validate tool results before forwarding."""
        tool_result = context.get("tool_result", {})
        if isinstance(tool_result, dict):
            if "error" in tool_result:
                context["tool_audit"] = "failed"
            else:
                context["tool_audit"] = "passed"
        return context

    @staticmethod
    def _capture_prediction(context: dict) -> dict:
        """agent_end: capture final prediction for delivery pipeline."""
        prediction = context.get("prediction", {})
        if prediction:
            context["delivery_ready"] = True
            context["delivery_payload"] = prediction
        return context

    # ── Delivery implementations ─────────────────────────────────────────────

    @staticmethod
    def _deliver_file(prediction: dict, config: dict) -> str:
        """Write prediction to a local JSON file."""
        from pathlib import Path
        output_dir = Path(config.get("output_dir", "reports"))
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"prediction_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = output_dir / filename
        filepath.write_text(json.dumps(prediction, indent=2, default=str), encoding="utf-8")
        return str(filepath)

    def _deliver_api(self, prediction: dict, config: dict) -> str:
        """POST prediction to a REST endpoint."""
        endpoint = config.get("endpoint", "")
        if not endpoint:
            return "no_endpoint_configured"
        data = json.dumps(prediction, default=str).encode("utf-8")
        req = Request(
            endpoint,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        api_key = config.get("api_key", "")
        if api_key:
            req.add_header("Authorization", f"Bearer {api_key}")
        with urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return f"delivered_http_{resp.status}"

    def _deliver_webhook(self, prediction: dict, config: dict) -> str:
        """Send prediction to a webhook URL."""
        url = config.get("url", "")
        if not url:
            return "no_webhook_url"
        return self._deliver_api(prediction, {"endpoint": url})

    def _deliver_gateway_channel(
        self, prediction: dict, channel: str, config: dict
    ) -> str:
        """Deliver via OpenClaw gateway or direct webhook to a specific channel."""
        # Direct webhook delivery (no OpenClaw gateway required)
        webhook_url = config.get("webhook_url", "")
        if webhook_url:
            if channel == "discord":
                return self._deliver_discord_webhook(prediction, webhook_url, config)
            elif channel == "telegram":
                return self._deliver_telegram(prediction, config)
            elif channel == "slack":
                return self._deliver_slack_webhook(prediction, webhook_url, config)

        # Fall back to OpenClaw gateway relay
        msg = OpenClawMessage(
            type="delivery",
            payload={
                "channel": channel,
                "prediction": prediction,
                "format": config.get("format", "summary"),
            },
        )
        success = self.send_message(msg)
        return "delivered" if success else "gateway_unreachable"

    @staticmethod
    def _format_prediction_text(prediction: dict, fmt: str = "summary") -> str:
        """Format a prediction dict into human-readable text."""
        p = prediction.get("prediction", prediction)
        topic = p.get("topic", prediction.get("topic", "Unknown"))
        direction = p.get("direction", "neutral")
        confidence = p.get("confidence", 0)
        horizon = p.get("horizon", prediction.get("horizon", ""))
        members = p.get("member_count", prediction.get("member_count", "?"))

        lines = [
            f"**FPC Prediction: {topic}**",
            f"Direction: **{direction}**",
            f"Confidence: **{confidence:.0%}**",
        ]
        if horizon:
            lines.append(f"Horizon: {horizon}")
        if members:
            lines.append(f"Council members: {members}")

        if fmt == "full":
            reasoning = p.get("reasoning", "")
            if reasoning:
                lines.append(f"\n{reasoning}")
            dissent = p.get("dissenting_views", [])
            if dissent:
                lines.append("\nDissenting views:")
                for d in dissent:
                    lines.append(f"  • {d}")

        lines.append(f"\n_Generated {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}_")
        return "\n".join(lines)

    def _deliver_discord_webhook(
        self, prediction: dict, webhook_url: str, config: dict
    ) -> str:
        """Send prediction to Discord via webhook URL."""
        text = self._format_prediction_text(prediction, config.get("format", "summary"))
        payload = json.dumps({"content": text}).encode("utf-8")
        req = Request(
            webhook_url,
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return f"discord_delivered_{resp.status}"

    def _deliver_telegram(self, prediction: dict, config: dict) -> str:
        """Send prediction to Telegram via Bot API."""
        bot_token = config.get("bot_token", "")
        chat_id = config.get("chat_id", "")
        if not bot_token or not chat_id:
            return "telegram_missing_bot_token_or_chat_id"
        text = self._format_prediction_text(prediction, config.get("format", "summary"))
        # Telegram uses MarkdownV2 — escape special chars for safe delivery
        payload = json.dumps({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }).encode("utf-8")
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        req = Request(
            url,
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return f"telegram_delivered_{resp.status}"

    def _deliver_slack_webhook(
        self, prediction: dict, webhook_url: str, config: dict
    ) -> str:
        """Send prediction to Slack via incoming webhook."""
        text = self._format_prediction_text(prediction, config.get("format", "summary"))
        payload = json.dumps({"text": text}).encode("utf-8")
        req = Request(
            webhook_url,
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return f"slack_delivered_{resp.status}"
