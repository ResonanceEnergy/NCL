"""
NCL Shortcuts Pack v1 — Shortcut definitions for iOS Shortcuts app.

Each shortcut definition contains:
    - name: Siri-friendly shortcut name
    - description: What it does
    - trigger_phrase: "Hey Siri, ..."
    - endpoint: NCL API endpoint to call
    - method: HTTP method
    - input_fields: What the shortcut asks the user for
    - output_format: How to display the response
    - actions: Step-by-step iOS Shortcut action sequence (for import)

These definitions are served by GET /shortcuts/config so the user can
auto-configure their iPhone from the Mac Mini.
"""

from __future__ import annotations
from typing import Any


def get_shortcut_definitions(
    ncl_host: str = "localhost",
    ncl_port: int = 8800,
    strike_token: str = "",
) -> list[dict[str, Any]]:
    """
    Return all shortcut definitions with the given host/port/token baked in.

    Args:
        ncl_host: NCL brain hostname or IP (e.g., Tailscale hostname)
        ncl_port: NCL brain port
        strike_token: STRIKE_AUTH_TOKEN for authentication
    """
    base_url = f"http://{ncl_host}:{ncl_port}"

    return [
        {
            "id": "ncl-pump",
            "name": "NCL Pump",
            "description": "Send a pump prompt to NCL Brain for council analysis and mandate generation",
            "trigger_phrase": "pump NCL",
            "siri_phrase": "Hey Siri, pump NCL",
            "icon": "brain.head.profile",
            "color": "#38bdf8",
            "endpoint": f"{base_url}/pump",
            "method": "POST",
            "auth_header": f"Bearer {strike_token}",
            "input_fields": [
                {
                    "key": "intent",
                    "label": "What should NCL think about?",
                    "type": "text",
                    "required": True,
                    "siri_prompt": "What should NCL think about?",
                },
                {
                    "key": "urgency",
                    "label": "Urgency",
                    "type": "choice",
                    "options": ["low", "normal", "high", "critical"],
                    "default": "normal",
                },
            ],
            "body_template": {
                "prompt_id": "pump-{{UUID}}",
                "source": "iphone-shortcut",
                "intent": "{{intent}}",
                "context": {"origin": "siri", "device": "iphone"},
                "urgency": "{{urgency}}",
            },
            "output_format": {
                "success_message": "Pump sent to NCL Brain. Pending your approval.",
                "show_fields": ["pump_id", "mandates_generated"],
            },
            "actions": [
                {"type": "ask_for_input", "prompt": "What should NCL think about?", "var": "intent"},
                {"type": "choose_from_menu", "prompt": "Urgency?", "options": ["low", "normal", "high", "critical"], "default": "normal", "var": "urgency"},
                {"type": "get_contents_of_url", "url": f"{base_url}/pump", "method": "POST",
                 "headers": {"Authorization": f"Bearer {strike_token}", "Content-Type": "application/json"},
                 "body": "json"},
                {"type": "show_result", "template": "Pump submitted. Check /pump/pending for approval."},
            ],
        },
        {
            "id": "ncl-status",
            "name": "NCL Status",
            "description": "Check NCL pipeline health, pending pumps, active mandates",
            "trigger_phrase": "NCL status",
            "siri_phrase": "Hey Siri, NCL status",
            "icon": "chart.bar.xaxis",
            "color": "#22c55e",
            "endpoint": f"{base_url}/dashboard",
            "method": "GET",
            "auth_header": None,
            "input_fields": [],
            "output_format": {
                "speak_template": (
                    "NCL is {{pipeline_status}}. "
                    "{{pump_count}} pumps pending, "
                    "{{active_mandates}} active mandates, "
                    "{{completed_count}} completed."
                ),
                "show_fields": ["pipeline_status", "pump_count", "active_mandates", "completed_count",
                                "youtube_reports", "x_reports"],
            },
            "actions": [
                {"type": "get_contents_of_url", "url": f"{base_url}/dashboard", "method": "GET"},
                {"type": "speak_text", "template": "NCL pipeline is {{pipeline_status}}. {{pump_count}} pumps pending."},
                {"type": "show_result", "template": "Pipeline: {{pipeline_status}}\nPumps: {{pump_count}}\nActive Mandates: {{active_mandates}}"},
            ],
        },
        {
            "id": "ncl-approve",
            "name": "NCL Approve",
            "description": "Review and approve pending pump prompts for NCC dispatch",
            "trigger_phrase": "approve pump",
            "siri_phrase": "Hey Siri, approve pump",
            "icon": "checkmark.seal.fill",
            "color": "#f59e0b",
            "endpoint": f"{base_url}/pump/pending",
            "method": "GET",
            "auth_header": f"Bearer {strike_token}",
            "input_fields": [],
            "output_format": {
                "speak_template": "{{total}} pumps pending approval.",
                "show_fields": ["total", "pending"],
            },
            "actions": [
                {"type": "get_contents_of_url", "url": f"{base_url}/pump/pending", "method": "GET",
                 "headers": {"Authorization": f"Bearer {strike_token}"}},
                {"type": "if", "condition": "total > 0", "then": [
                    {"type": "choose_from_list", "prompt": "Which pump to approve?", "list_key": "pending", "display_key": "intent", "var": "chosen_pump"},
                    {"type": "get_contents_of_url", "url": f"{base_url}/pump/approve/{{{{chosen_pump.pump_id}}}}", "method": "POST",
                     "headers": {"Authorization": f"Bearer {strike_token}"}},
                    {"type": "speak_text", "template": "Pump approved and dispatched to NCC."},
                ], "else": [
                    {"type": "speak_text", "template": "No pumps pending approval."},
                ]},
            ],
        },
        {
            "id": "ncl-council",
            "name": "NCL Council",
            "description": "Trigger an intelligence council session (YouTube + X scan)",
            "trigger_phrase": "run council",
            "siri_phrase": "Hey Siri, run council",
            "icon": "person.3.fill",
            "color": "#8b5cf6",
            "endpoint": f"{base_url}/councils/run",
            "method": "POST",
            "auth_header": f"Bearer {strike_token}",
            "input_fields": [
                {
                    "key": "council_type",
                    "label": "Council type",
                    "type": "choice",
                    "options": ["both", "youtube", "x"],
                    "default": "both",
                },
            ],
            "body_template": {
                "council_type": "{{council_type}}",
            },
            "output_format": {
                "success_message": "Council session started. Reports will be available in intelligence-scan/.",
                "show_fields": ["session_id", "status"],
            },
            "actions": [
                {"type": "choose_from_menu", "prompt": "Which council?", "options": ["both", "youtube", "x"], "default": "both", "var": "council_type"},
                {"type": "get_contents_of_url", "url": f"{base_url}/councils/run", "method": "POST",
                 "headers": {"Authorization": f"Bearer {strike_token}", "Content-Type": "application/json"},
                 "body": "json"},
                {"type": "speak_text", "template": "Intelligence council started."},
            ],
        },
        {
            "id": "ncl-search",
            "name": "NCL Search",
            "description": "Full-text search across NCL events, memory, and mandates",
            "trigger_phrase": "search NCL",
            "siri_phrase": "Hey Siri, search NCL",
            "icon": "magnifyingglass",
            "color": "#06b6d4",
            "endpoint": f"{base_url}/search",
            "method": "POST",
            "auth_header": None,
            "input_fields": [
                {
                    "key": "query",
                    "label": "Search for...",
                    "type": "text",
                    "required": True,
                    "siri_prompt": "What do you want to search for?",
                },
            ],
            "body_template": {
                "query": "{{query}}",
                "limit": 10,
            },
            "output_format": {
                "speak_template": "Found {{total}} results for {{query}}.",
                "show_fields": ["total", "results"],
            },
            "actions": [
                {"type": "ask_for_input", "prompt": "What do you want to search for?", "var": "query"},
                {"type": "get_contents_of_url", "url": f"{base_url}/search", "method": "POST",
                 "headers": {"Content-Type": "application/json"},
                 "body": "json"},
                {"type": "speak_text", "template": "Found {{total}} results."},
                {"type": "show_result", "template": "Results:\n{{#results}}• {{snippet}}\n{{/results}}"},
            ],
        },
        # ── Intelligence Brief Shortcut ──────────────────────────────────
        {
            "id": "ncl-intel",
            "name": "NCL Intel",
            "description": "Get the latest intelligence brief or generate a fresh one. View top signals, predictions, and risk alerts with options to escalate to STRIKE-POINT.",
            "trigger_phrase": "NCL intel",
            "siri_phrase": "Hey Siri, NCL intel",
            "icon": "globe.desk",
            "color": "#ef4444",
            "endpoint": f"{base_url}/intelligence/latest",
            "method": "GET",
            "auth_header": f"Bearer {strike_token}",
            "input_fields": [
                {
                    "key": "action",
                    "label": "What do you want?",
                    "type": "choice",
                    "options": ["latest brief", "generate fresh", "escalate top signals"],
                    "default": "latest brief",
                    "siri_prompt": "Latest brief, generate fresh, or escalate top signals?",
                },
            ],
            "output_format": {
                "speak_template": (
                    "Intelligence brief ready. "
                    "{{total_signals}} signals processed. "
                    "{{risk_alert_count}} risk alerts."
                ),
                "show_fields": ["brief_type", "total_signals", "executive_summary",
                                "risk_alerts", "top_signals"],
            },
            "actions": [
                {"type": "choose_from_menu", "prompt": "What do you want?",
                 "options": ["latest brief", "generate fresh", "escalate top signals"],
                 "default": "latest brief", "var": "action"},
                # Branch: latest brief
                {"type": "if", "condition": "action == 'latest brief'", "then": [
                    {"type": "get_contents_of_url", "url": f"{base_url}/intelligence/latest", "method": "GET",
                     "headers": {"Authorization": f"Bearer {strike_token}"}},
                    {"type": "if", "condition": "status == 'no_brief'", "then": [
                        {"type": "speak_text", "template": "No brief available yet. Generating one now."},
                        {"type": "get_contents_of_url", "url": f"{base_url}/intelligence/brief", "method": "POST",
                         "headers": {"Authorization": f"Bearer {strike_token}", "Content-Type": "application/json"}},
                    ]},
                    {"type": "speak_text", "template": "Intel brief: {{total_signals}} signals. {{executive_summary}}"},
                    {"type": "show_result", "template": "{{text}}"},
                ]},
                # Branch: generate fresh
                {"type": "if", "condition": "action == 'generate fresh'", "then": [
                    {"type": "get_contents_of_url", "url": f"{base_url}/intelligence/brief", "method": "POST",
                     "headers": {"Authorization": f"Bearer {strike_token}", "Content-Type": "application/json"}},
                    {"type": "speak_text", "template": "Fresh brief generated. {{total_signals}} signals across {{sectors}} sectors."},
                    {"type": "show_result", "template": "{{text}}"},
                ]},
                # Branch: escalate to STRIKE-POINT
                {"type": "if", "condition": "action == 'escalate top signals'", "then": [
                    {"type": "get_contents_of_url", "url": f"{base_url}/intelligence/latest", "method": "GET",
                     "headers": {"Authorization": f"Bearer {strike_token}"}},
                    {"type": "get_contents_of_url", "url": f"{base_url}/intelligence/escalate", "method": "POST",
                     "headers": {"Authorization": f"Bearer {strike_token}", "Content-Type": "application/json"},
                     "body": "json"},
                    {"type": "speak_text", "template": "Top signals escalated to STRIKE-POINT for deep analysis."},
                    {"type": "show_result", "template": "Escalated {{escalated_count}} signals. Mandate: {{mandate_id}}"},
                ]},
            ],
        },
        # ── Signal Alert Quick Action ────────────────────────────────────
        {
            "id": "ncl-intel-act",
            "name": "NCL Signal Action",
            "description": "Take action on a specific intelligence signal — acknowledge, investigate, or escalate to STRIKE-POINT for mandate generation.",
            "trigger_phrase": "NCL signal",
            "siri_phrase": "Hey Siri, NCL signal",
            "icon": "bolt.circle.fill",
            "color": "#f97316",
            "endpoint": f"{base_url}/intelligence/signals/top",
            "method": "GET",
            "auth_header": f"Bearer {strike_token}",
            "input_fields": [],
            "output_format": {
                "speak_template": "Top signal: {{title}}. Direction: {{direction}}.",
                "show_fields": ["title", "source", "direction", "importance", "change_pct"],
            },
            "actions": [
                # Fetch top unacknowledged signals
                {"type": "get_contents_of_url", "url": f"{base_url}/intelligence/signals/top", "method": "GET",
                 "headers": {"Authorization": f"Bearer {strike_token}"}},
                {"type": "if", "condition": "total > 0", "then": [
                    {"type": "choose_from_list", "prompt": "Which signal?", "list_key": "signals",
                     "display_key": "title", "var": "chosen_signal"},
                    {"type": "choose_from_menu", "prompt": "Action?",
                     "options": ["Acknowledge", "Escalate to STRIKE-POINT", "Get more detail"],
                     "var": "signal_action"},
                    {"type": "if", "condition": "signal_action == 'Escalate to STRIKE-POINT'", "then": [
                        {"type": "get_contents_of_url",
                         "url": f"{base_url}/intelligence/escalate/{{{{chosen_signal.signal_id}}}}",
                         "method": "POST",
                         "headers": {"Authorization": f"Bearer {strike_token}"}},
                        {"type": "speak_text", "template": "Signal escalated to STRIKE-POINT."},
                    ]},
                    {"type": "if", "condition": "signal_action == 'Get more detail'", "then": [
                        {"type": "get_contents_of_url",
                         "url": f"{base_url}/intelligence/signal/{{{{chosen_signal.signal_id}}}}",
                         "method": "GET",
                         "headers": {"Authorization": f"Bearer {strike_token}"}},
                        {"type": "show_result", "template": "{{detail}}"},
                    ]},
                ], "else": [
                    {"type": "speak_text", "template": "No active signals right now."},
                ]},
            ],
        },
    ]
