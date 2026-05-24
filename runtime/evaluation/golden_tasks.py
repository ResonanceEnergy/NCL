"""Golden Task Suite v1 — 50 deterministic evaluation tasks for NCL brain pipeline."""

from .models import GoldenTask, TaskCategory, TaskDifficulty


def get_golden_tasks() -> list[GoldenTask]:
    """
    Returns 50 deterministic golden tasks for NCL brain pipeline regression testing.
    Organized by category (CAPTURE, SUMMARIZE, PLAN, RECALL, CLASSIFY, EXTRACT,
    DEBATE, MANDATE, SEARCH, PIPELINE).
    """

    tasks = []

    # ============================================================================
    # CAPTURE (8 tasks) - Input ingestion & parsing
    # ============================================================================

    tasks.append(
        GoldenTask(
            name="capture_simple_json_pump",
            category=TaskCategory.CAPTURE,
            difficulty=TaskDifficulty.TRIVIAL,
            description="Parse simple JSON pump prompt",
            input_data={
                "prompt": '{"action": "analyze", "target": "market_signal"}',
                "content_type": "application/json",
            },
            expected_keys=["action", "target"],
            expected_patterns=[r"analyze", r"market_signal"],
            failure_conditions=["Invalid JSON"],
            tags=["json", "pump-prompt"],
        )
    )

    tasks.append(
        GoldenTask(
            name="capture_url_detection",
            category=TaskCategory.CAPTURE,
            difficulty=TaskDifficulty.STANDARD,
            description="Detect and extract URLs from text",
            input_data={
                "text": "Check https://example.com/api for updates and http://test.org/data",
                "mode": "extract_urls",
            },
            expected_keys=["urls"],
            expected_patterns=[r"https://example\.com", r"http://test\.org"],
            failure_conditions=["No URLs found"],
            tags=["url", "parsing"],
        )
    )

    tasks.append(
        GoldenTask(
            name="capture_event_schema_creation",
            category=TaskCategory.CAPTURE,
            difficulty=TaskDifficulty.STANDARD,
            description="Create event schema from structured fields",
            input_data={
                "timestamp": "2026-04-13T10:30:00Z",
                "event_type": "signal_received",
                "source": "market_feed",
                "severity": "high",
                "data": {"ticker": "ACME", "price": 42.5},
            },
            expected_keys=["timestamp", "event_type", "source", "severity"],
            expected_patterns=[r"signal_received", r"high"],
            failure_conditions=["Missing required field"],
            tags=["schema", "event"],
        )
    )

    tasks.append(
        GoldenTask(
            name="capture_multi_field_extraction",
            category=TaskCategory.CAPTURE,
            difficulty=TaskDifficulty.STANDARD,
            description="Extract multiple fields from mixed content",
            input_data={
                "content": "User john@example.com reported issue at 2026-04-13. Priority: CRITICAL",
                "fields": ["email", "date", "priority"],
            },
            expected_keys=["email", "date", "priority"],
            expected_patterns=[r"john@example\.com", r"2026-04-13", r"CRITICAL"],
            failure_conditions=["Missing field"],
            tags=["extraction", "multi-field"],
        )
    )

    tasks.append(
        GoldenTask(
            name="capture_empty_input_handling",
            category=TaskCategory.CAPTURE,
            difficulty=TaskDifficulty.EDGE_CASE,
            description="Handle empty input gracefully",
            input_data={"content": "", "strict": False},
            expected_keys=["content", "error", "empty"],
            expected_patterns=[r"empty", r"true"],
            failure_conditions=["Exception thrown"],
            tags=["edge-case", "empty"],
        )
    )

    tasks.append(
        GoldenTask(
            name="capture_unicode_handling",
            category=TaskCategory.CAPTURE,
            difficulty=TaskDifficulty.EDGE_CASE,
            description="Handle Unicode and special characters",
            input_data={
                "text": "Signal from 日本 market: €500K allocation. Status: ✓ confirmed",
                "preserve_unicode": True,
            },
            expected_keys=["text", "preserved"],
            expected_patterns=[r"日本", r"€", r"✓"],
            failure_conditions=["Unicode lost"],
            tags=["unicode", "international"],
        )
    )

    tasks.append(
        GoldenTask(
            name="capture_large_payload",
            category=TaskCategory.CAPTURE,
            difficulty=TaskDifficulty.STRESS,
            description="Handle large payload (10KB+ text)",
            input_data={"content": "x" * 15000, "compression": False},
            expected_keys=["length", "received"],
            expected_patterns=[r"15000"],
            failure_conditions=["Payload too large"],
            max_duration_ms=5000,
            tags=["stress", "large-payload"],
        )
    )

    tasks.append(
        GoldenTask(
            name="capture_nested_json_parsing",
            category=TaskCategory.CAPTURE,
            difficulty=TaskDifficulty.STANDARD,
            description="Parse deeply nested JSON structure",
            input_data={
                "data": {
                    "level1": {
                        "level2": {
                            "level3": {"value": "nested_target", "metadata": {"type": "signal"}}
                        }
                    }
                }
            },
            expected_keys=["level1", "nested_target", "signal"],
            expected_patterns=[r"nested_target"],
            failure_conditions=["Structure mismatch"],
            tags=["json", "nested"],
        )
    )

    # ============================================================================
    # SUMMARIZE (6 tasks) - Content summarization
    # ============================================================================

    tasks.append(
        GoldenTask(
            name="summarize_council_synthesis",
            category=TaskCategory.SUMMARIZE,
            difficulty=TaskDifficulty.STANDARD,
            description="Synthesize council debate into summary",
            input_data={
                "debate_text": (
                    "Alpha: Market indicates upward trend. Beta: Disagree, volatility high. "
                    "Gamma: We need caution. Delta: Consensus—monitor with threshold."
                ),
                "target_length": "brief",
            },
            expected_keys=["summary", "consensus_score"],
            expected_patterns=[r"monitor", r"caution"],
            failure_conditions=["No consensus"],
            tags=["debate", "council"],
        )
    )

    tasks.append(
        GoldenTask(
            name="summarize_mandate_output",
            category=TaskCategory.SUMMARIZE,
            difficulty=TaskDifficulty.STANDARD,
            description="Summarize generated mandate to key actions",
            input_data={
                "mandate": {
                    "actions": ["Allocate 5K units", "Set stop at 40.5", "Monitor for 2h"],
                    "priority": "high",
                    "status": "active",
                }
            },
            expected_keys=["action_summary", "priority"],
            expected_patterns=[r"5K", r"high"],
            failure_conditions=["Missing actions"],
            tags=["mandate", "actions"],
        )
    )

    tasks.append(
        GoldenTask(
            name="summarize_event_log",
            category=TaskCategory.SUMMARIZE,
            difficulty=TaskDifficulty.STANDARD,
            description="Summarize event log into timeline",
            input_data={
                "events": [
                    {"time": "10:00", "type": "signal", "detail": "Received"},
                    {"time": "10:15", "type": "debate", "detail": "Started"},
                    {"time": "10:30", "type": "mandate", "detail": "Generated"},
                ]
            },
            expected_keys=["timeline", "event_count"],
            expected_patterns=[r"10:00", r"10:15", r"10:30"],
            failure_conditions=["Events missing"],
            tags=["timeline", "events"],
        )
    )

    tasks.append(
        GoldenTask(
            name="summarize_multi_source_content",
            category=TaskCategory.SUMMARIZE,
            difficulty=TaskDifficulty.STANDARD,
            description="Merge summaries from multiple sources",
            input_data={
                "sources": [
                    {"source": "feed_a", "content": "Long analysis text here"},
                    {"source": "feed_b", "content": "Different market view"},
                ],
                "merge_style": "balanced",
            },
            expected_keys=["merged_summary", "source_count"],
            expected_patterns=[r"feed_a", r"feed_b"],
            failure_conditions=["Source missing"],
            tags=["multi-source", "merge"],
        )
    )

    tasks.append(
        GoldenTask(
            name="summarize_empty_content",
            category=TaskCategory.SUMMARIZE,
            difficulty=TaskDifficulty.EDGE_CASE,
            description="Summarize empty or null content",
            input_data={"content": None, "strict": False},
            expected_keys=["summary", "empty"],
            expected_patterns=[r"empty|null"],
            failure_conditions=["Exception thrown"],
            tags=["edge-case", "null"],
        )
    )

    tasks.append(
        GoldenTask(
            name="summarize_truncation_behavior",
            category=TaskCategory.SUMMARIZE,
            difficulty=TaskDifficulty.STRESS,
            description="Truncate long summary to max length",
            input_data={
                "content": "word " * 2000,  # Large text
                "max_words": 100,
            },
            expected_keys=["summary", "truncated", "word_count"],
            expected_patterns=[r"truncated|true"],
            failure_conditions=["Exceeds max_words"],
            tags=["stress", "truncation"],
        )
    )

    # ============================================================================
    # PLAN (5 tasks) - Strategy & planning
    # ============================================================================

    tasks.append(
        GoldenTask(
            name="plan_mandate_generation",
            category=TaskCategory.PLAN,
            difficulty=TaskDifficulty.STANDARD,
            description="Generate mandate from council output",
            input_data={
                "council_decision": {
                    "action": "allocate",
                    "target": "asset_pool",
                    "amount": 5000,
                    "confidence": 0.85,
                }
            },
            expected_keys=["mandate", "action", "target", "amount"],
            expected_patterns=[r"allocate", r"5000"],
            failure_conditions=["No mandate generated"],
            tags=["mandate", "decision"],
        )
    )

    tasks.append(
        GoldenTask(
            name="plan_multi_pillar_planning",
            category=TaskCategory.PLAN,
            difficulty=TaskDifficulty.STANDARD,
            description="Create multi-pillar strategy plan",
            input_data={"pillars": ["finance", "risk", "execution"], "resources": 10000},
            expected_keys=["finance_plan", "risk_plan", "execution_plan"],
            expected_patterns=[r"finance|risk|execution"],
            failure_conditions=["Missing pillar"],
            tags=["strategy", "pillars"],
        )
    )

    tasks.append(
        GoldenTask(
            name="plan_priority_assignment",
            category=TaskCategory.PLAN,
            difficulty=TaskDifficulty.STANDARD,
            description="Assign priorities to plan items",
            input_data={
                "items": [
                    {"name": "buy", "impact": 0.9},
                    {"name": "monitor", "impact": 0.6},
                    {"name": "alert", "impact": 0.8},
                ]
            },
            expected_keys=["priorities", "ranked"],
            expected_patterns=[r"buy|monitor|alert"],
            failure_conditions=["Items unranked"],
            tags=["priority", "ranking"],
        )
    )

    tasks.append(
        GoldenTask(
            name="plan_deadline_extraction",
            category=TaskCategory.PLAN,
            difficulty=TaskDifficulty.STANDARD,
            description="Extract and assign deadlines to actions",
            input_data={
                "actions": [
                    {"task": "execute", "deadline": "2026-04-13T12:00:00Z"},
                    {"task": "verify", "deadline": "2026-04-13T13:00:00Z"},
                ]
            },
            expected_keys=["deadlines", "earliest", "latest"],
            expected_patterns=[r"12:00", r"13:00"],
            failure_conditions=["No deadlines"],
            tags=["deadline", "scheduling"],
        )
    )

    tasks.append(
        GoldenTask(
            name="plan_resource_allocation",
            category=TaskCategory.PLAN,
            difficulty=TaskDifficulty.STANDARD,
            description="Allocate resources across plan items",
            input_data={
                "total_budget": 10000,
                "allocations": [
                    {"pillar": "core", "percentage": 0.6},
                    {"pillar": "buffer", "percentage": 0.4},
                ],
            },
            expected_keys=["core_allocation", "buffer_allocation"],
            expected_patterns=[r"6000|4000"],
            failure_conditions=["Budget mismatch"],
            tags=["resource", "budget"],
        )
    )

    # ============================================================================
    # RECALL (6 tasks) - Memory retrieval
    # ============================================================================

    tasks.append(
        GoldenTask(
            name="recall_memory_search_by_tags",
            category=TaskCategory.RECALL,
            difficulty=TaskDifficulty.STANDARD,
            description="Search memory entries by tags",
            input_data={
                "query_tags": ["market", "signal"],
                "memory": [
                    {"id": "m1", "tags": ["market", "signal"], "content": "Signal data"},
                    {"id": "m2", "tags": ["risk"], "content": "Risk data"},
                ],
            },
            expected_keys=["matches", "count"],
            expected_patterns=[r"m1"],
            failure_conditions=["No matches"],
            tags=["memory", "search"],
        )
    )

    tasks.append(
        GoldenTask(
            name="recall_memory_by_importance",
            category=TaskCategory.RECALL,
            difficulty=TaskDifficulty.STANDARD,
            description="Retrieve memory entries above importance threshold",
            input_data={
                "threshold": 0.7,
                "memory": [
                    {"id": "m1", "importance": 0.95, "content": "Critical"},
                    {"id": "m2", "importance": 0.5, "content": "Low"},
                ],
            },
            expected_keys=["results", "count"],
            expected_patterns=[r"m1", r"Critical"],
            failure_conditions=["Threshold ignored"],
            tags=["memory", "importance"],
        )
    )

    tasks.append(
        GoldenTask(
            name="recall_memory_by_time_range",
            category=TaskCategory.RECALL,
            difficulty=TaskDifficulty.STANDARD,
            description="Query memory entries within time window",
            input_data={
                "start": "2026-04-13T09:00:00Z",
                "end": "2026-04-13T11:00:00Z",
                "memory": [
                    {"id": "m1", "timestamp": "2026-04-13T10:00:00Z", "content": "In range"},
                    {"id": "m2", "timestamp": "2026-04-13T12:00:00Z", "content": "Out of range"},
                ],
            },
            expected_keys=["results", "in_range_count"],
            expected_patterns=[r"m1"],
            failure_conditions=["Time filtering failed"],
            tags=["memory", "time"],
        )
    )

    tasks.append(
        GoldenTask(
            name="recall_memory_by_content_similarity",
            category=TaskCategory.RECALL,
            difficulty=TaskDifficulty.STANDARD,
            description="Find similar memory entries by content matching",
            input_data={
                "query": "market signal",
                "memory": [
                    {"id": "m1", "content": "market signal received"},
                    {"id": "m2", "content": "unrelated data"},
                ],
            },
            expected_keys=["similar", "best_match"],
            expected_patterns=[r"m1"],
            failure_conditions=["No match"],
            tags=["memory", "similarity"],
        )
    )

    tasks.append(
        GoldenTask(
            name="recall_empty_memory",
            category=TaskCategory.RECALL,
            difficulty=TaskDifficulty.EDGE_CASE,
            description="Query empty memory store",
            input_data={"memory": [], "query": "anything"},
            expected_keys=["results", "count"],
            expected_patterns=[r"0|empty"],
            failure_conditions=["Exception thrown"],
            tags=["memory", "empty"],
        )
    )

    tasks.append(
        GoldenTask(
            name="recall_memory_with_decay",
            category=TaskCategory.RECALL,
            difficulty=TaskDifficulty.STANDARD,
            description="Apply time decay to memory importance",
            input_data={
                "current_time": "2026-04-13T12:00:00Z",
                "memory": [
                    {"id": "m1", "created": "2026-04-13T10:00:00Z", "importance": 1.0},
                    {"id": "m2", "created": "2026-04-12T12:00:00Z", "importance": 1.0},
                ],
                "decay_rate": 0.1,
            },
            expected_keys=["decayed_importance", "m1", "m2"],
            expected_patterns=[r"0\.\d+"],
            failure_conditions=["Decay not applied"],
            tags=["memory", "decay"],
        )
    )

    # ============================================================================
    # CLASSIFY (5 tasks) - Categorization & routing
    # ============================================================================

    tasks.append(
        GoldenTask(
            name="classify_event_type",
            category=TaskCategory.CLASSIFY,
            difficulty=TaskDifficulty.STANDARD,
            description="Classify incoming event to type",
            input_data={
                "event": {
                    "content": "Price dropped 5%",
                    "source": "market_feed",
                    "urgency_indicator": "high",
                }
            },
            expected_keys=["classification", "type"],
            expected_patterns=[r"price|market"],
            failure_conditions=["Unclassified"],
            tags=["classify", "event"],
        )
    )

    tasks.append(
        GoldenTask(
            name="classify_pump_urgency",
            category=TaskCategory.CLASSIFY,
            difficulty=TaskDifficulty.STANDARD,
            description="Classify pump prompt urgency level",
            input_data={"pump": {"action": "buy", "amount": 5000, "time_constraint": "2h"}},
            expected_keys=["urgency", "level"],
            expected_patterns=[r"high|critical|normal"],
            failure_conditions=["No urgency classification"],
            tags=["urgency", "pump"],
        )
    )

    tasks.append(
        GoldenTask(
            name="classify_pillar_routing",
            category=TaskCategory.CLASSIFY,
            difficulty=TaskDifficulty.STANDARD,
            description="Route decision to appropriate pillar",
            input_data={"decision": {"action": "allocate_capital", "risk_level": 0.8}},
            expected_keys=["pillar", "target"],
            expected_patterns=[r"finance|risk"],
            failure_conditions=["No routing"],
            tags=["routing", "pillar"],
        )
    )

    tasks.append(
        GoldenTask(
            name="classify_signal_category",
            category=TaskCategory.CLASSIFY,
            difficulty=TaskDifficulty.STANDARD,
            description="Categorize market signal type",
            input_data={"signal": {"metric": "volume_spike", "direction": "up", "magnitude": 2.5}},
            expected_keys=["category", "category_name"],
            expected_patterns=[r"volume|technical"],
            failure_conditions=["Unknown signal"],
            tags=["signal", "category"],
        )
    )

    tasks.append(
        GoldenTask(
            name="classify_ambiguous_input",
            category=TaskCategory.CLASSIFY,
            difficulty=TaskDifficulty.EDGE_CASE,
            description="Handle ambiguous input with confidence",
            input_data={"ambiguous_text": "May or may not act", "fallback_class": "neutral"},
            expected_keys=["classification", "confidence"],
            expected_patterns=[r"neutral|0\.\d+"],
            failure_conditions=["Exception thrown"],
            tags=["ambiguous", "edge-case"],
        )
    )

    # ============================================================================
    # EXTRACT (5 tasks) - Structured data extraction
    # ============================================================================

    tasks.append(
        GoldenTask(
            name="extract_from_council_debate",
            category=TaskCategory.EXTRACT,
            difficulty=TaskDifficulty.STANDARD,
            description="Extract structured data from council debate text",
            input_data={
                "debate_text": (
                    "Alpha voted 'yes' with confidence 0.9. Beta voted 'no' with confidence 0.6. "
                    "Consensus: proceed with caution."
                )
            },
            expected_keys=["votes", "confidences", "consensus"],
            expected_patterns=[r"yes|no", r"0\.[0-9]"],
            failure_conditions=["Extraction failed"],
            tags=["extract", "debate"],
        )
    )

    tasks.append(
        GoldenTask(
            name="extract_mandate_from_text",
            category=TaskCategory.EXTRACT,
            difficulty=TaskDifficulty.STANDARD,
            description="Extract mandate fields from unstructured text",
            input_data={
                "text": "MANDATE: Buy 5000 shares at max 42.5, execute by 14:00, stop at 40.0"
            },
            expected_keys=["action", "amount", "price_limit", "deadline", "stop_loss"],
            expected_patterns=[r"Buy|buy", r"5000", r"42\.5", r"14:00", r"40\.0"],
            failure_conditions=["Field missing"],
            tags=["extract", "mandate"],
        )
    )

    tasks.append(
        GoldenTask(
            name="extract_ticker_symbols",
            category=TaskCategory.EXTRACT,
            difficulty=TaskDifficulty.STANDARD,
            description="Extract ticker symbols from content",
            input_data={"content": "Monitor AAPL, GOOGL, and BRK.B for movements"},
            expected_keys=["tickers"],
            expected_patterns=[r"AAPL", r"GOOGL", r"BRK\.B"],
            failure_conditions=["Tickers missing"],
            tags=["extract", "ticker"],
        )
    )

    tasks.append(
        GoldenTask(
            name="extract_numerical_signals",
            category=TaskCategory.EXTRACT,
            difficulty=TaskDifficulty.STANDARD,
            description="Extract numerical metrics from signal content",
            input_data={"content": "Volume increased 250%, price delta +3.5%, RSI=72"},
            expected_keys=["metrics"],
            expected_patterns=[r"250|3\.5|72"],
            failure_conditions=["Metrics missing"],
            tags=["extract", "metrics"],
        )
    )

    tasks.append(
        GoldenTask(
            name="extract_from_malformed_input",
            category=TaskCategory.EXTRACT,
            difficulty=TaskDifficulty.EDGE_CASE,
            description="Extract data from malformed or partial input",
            input_data={
                "broken_json": '{"key": "value"',  # Missing closing brace
                "lenient": True,
            },
            expected_keys=["extracted", "recovered"],
            expected_patterns=[r"key|value"],
            failure_conditions=["No recovery attempted"],
            tags=["malformed", "resilience"],
        )
    )

    # ============================================================================
    # DEBATE (5 tasks) - Council debate quality
    # ============================================================================

    tasks.append(
        GoldenTask(
            name="debate_council_response_validation",
            category=TaskCategory.DEBATE,
            difficulty=TaskDifficulty.STANDARD,
            description="Validate council debate response format",
            input_data={
                "response": {
                    "proposer": "Alpha",
                    "position": "proceed",
                    "reasoning": "Market conditions favorable",
                    "confidence": 0.88,
                }
            },
            expected_keys=["proposer", "position", "reasoning", "confidence"],
            expected_patterns=[r"proceed", r"0\.[0-9]"],
            failure_conditions=["Validation failed"],
            tags=["debate", "validation"],
        )
    )

    tasks.append(
        GoldenTask(
            name="debate_consensus_scoring",
            category=TaskCategory.DEBATE,
            difficulty=TaskDifficulty.STANDARD,
            description="Score consensus level across council",
            input_data={
                "votes": [
                    {"proposer": "Alpha", "vote": 1},
                    {"proposer": "Beta", "vote": 1},
                    {"proposer": "Gamma", "vote": 0},
                ]
            },
            expected_keys=["consensus_score", "agreement_percentage"],
            expected_patterns=[r"0\.\d+", r"\d+%"],
            failure_conditions=["No score computed"],
            tags=["debate", "consensus"],
        )
    )

    tasks.append(
        GoldenTask(
            name="debate_dissent_detection",
            category=TaskCategory.DEBATE,
            difficulty=TaskDifficulty.STANDARD,
            description="Detect and flag dissenting opinions",
            input_data={"votes": [1, 1, 1, 0, 0], "threshold": 0.8},
            expected_keys=["dissent_detected", "dissent_count"],
            expected_patterns=[r"true|false", r"\d"],
            failure_conditions=["No dissent analysis"],
            tags=["debate", "dissent"],
        )
    )

    tasks.append(
        GoldenTask(
            name="debate_role_adherence",
            category=TaskCategory.DEBATE,
            difficulty=TaskDifficulty.STANDARD,
            description="Check council member adheres to role",
            input_data={
                "member": "risk_officer",
                "statement": "Risk exposure now exceeds 15% threshold",
                "expected_concern": "risk",
            },
            expected_keys=["adherent", "role_match"],
            expected_patterns=[r"true|risk"],
            failure_conditions=["Check failed"],
            tags=["debate", "roles"],
        )
    )

    tasks.append(
        GoldenTask(
            name="debate_synthesis_quality",
            category=TaskCategory.DEBATE,
            difficulty=TaskDifficulty.STANDARD,
            description="Evaluate quality of debate synthesis",
            input_data={
                "debate_points": [
                    "Point A: Market conditions good",
                    "Point B: Risk level moderate",
                    "Point C: Timing favorable",
                ],
                "synthesis": "Consider market + risk + timing holistically",
            },
            expected_keys=["quality_score", "synthesis_valid"],
            expected_patterns=[r"0\.\d+", r"true"],
            failure_conditions=["Invalid synthesis"],
            tags=["debate", "synthesis"],
        )
    )

    # ============================================================================
    # MANDATE (5 tasks) - Mandate generation & validation
    # ============================================================================

    tasks.append(
        GoldenTask(
            name="mandate_structure_validation",
            category=TaskCategory.MANDATE,
            difficulty=TaskDifficulty.STANDARD,
            description="Validate mandate structure completeness",
            input_data={
                "mandate": {
                    "id": "mandate_001",
                    "action": "buy",
                    "amount": 5000,
                    "price_limit": 42.5,
                    "deadline": "2026-04-13T14:00:00Z",
                    "status": "active",
                }
            },
            expected_keys=["id", "action", "amount", "price_limit", "deadline", "status"],
            expected_patterns=[r"mandate_001", r"buy", r"active"],
            failure_conditions=["Missing field"],
            tags=["mandate", "structure"],
        )
    )

    tasks.append(
        GoldenTask(
            name="mandate_priority_bounds",
            category=TaskCategory.MANDATE,
            difficulty=TaskDifficulty.STANDARD,
            description="Validate priority within valid range",
            input_data={"mandate": {"priority": 8, "priority_range": [1, 10]}},
            expected_keys=["priority_valid", "priority"],
            expected_patterns=[r"true|8"],
            failure_conditions=["Priority out of bounds"],
            tags=["mandate", "priority"],
        )
    )

    tasks.append(
        GoldenTask(
            name="mandate_status_transitions",
            category=TaskCategory.MANDATE,
            difficulty=TaskDifficulty.STANDARD,
            description="Validate allowed status transitions",
            input_data={
                "current_status": "active",
                "target_status": "executed",
                "allowed": ["active", "executed", "cancelled"],
            },
            expected_keys=["transition_valid", "new_status"],
            expected_patterns=[r"true", r"executed"],
            failure_conditions=["Invalid transition"],
            tags=["mandate", "status"],
        )
    )

    tasks.append(
        GoldenTask(
            name="mandate_pillar_assignment",
            category=TaskCategory.MANDATE,
            difficulty=TaskDifficulty.STANDARD,
            description="Assign mandate to responsible pillar",
            input_data={
                "mandate_type": "capital_allocation",
                "pillars": ["finance", "risk", "ops"],
            },
            expected_keys=["assigned_pillar", "assignment_confidence"],
            expected_patterns=[r"finance|risk|ops"],
            failure_conditions=["No assignment"],
            tags=["mandate", "pillar"],
        )
    )

    tasks.append(
        GoldenTask(
            name="mandate_success_criteria",
            category=TaskCategory.MANDATE,
            difficulty=TaskDifficulty.STANDARD,
            description="Extract and validate success criteria",
            input_data={
                "mandate_text": (
                    "Execute buy order: success = order filled at ≤42.5 within 1h, "
                    "no slippage >0.2%"
                )
            },
            expected_keys=["criteria_count", "criteria"],
            expected_patterns=[r"42\.5|0\.2|1h"],
            failure_conditions=["Criteria empty"],
            tags=["mandate", "criteria"],
        )
    )

    # ============================================================================
    # SEARCH (3 tasks) - Search accuracy
    # ============================================================================

    tasks.append(
        GoldenTask(
            name="search_tfidf_accuracy",
            category=TaskCategory.SEARCH,
            difficulty=TaskDifficulty.STANDARD,
            description="TF-IDF search returns relevant documents",
            input_data={
                "query": "market signal",
                "documents": [
                    {"id": "d1", "text": "market signal received today"},
                    {"id": "d2", "text": "unrelated content here"},
                    {"id": "d3", "text": "market analysis with signal"},
                ],
            },
            expected_keys=["results", "top_match"],
            expected_patterns=[r"d1|d3"],
            failure_conditions=["d2 ranked first"],
            tags=["search", "tfidf"],
        )
    )

    tasks.append(
        GoldenTask(
            name="search_tag_based",
            category=TaskCategory.SEARCH,
            difficulty=TaskDifficulty.STANDARD,
            description="Tag-based search filters correctly",
            input_data={
                "tags": ["urgent", "market"],
                "documents": [
                    {"id": "d1", "tags": ["urgent", "market"]},
                    {"id": "d2", "tags": ["urgent"]},
                    {"id": "d3", "tags": ["market"]},
                ],
            },
            expected_keys=["matches", "match_ids"],
            expected_patterns=[r"d1"],
            failure_conditions=["Wrong matches"],
            tags=["search", "tags"],
        )
    )

    tasks.append(
        GoldenTask(
            name="search_correlation_chain",
            category=TaskCategory.SEARCH,
            difficulty=TaskDifficulty.STANDARD,
            description="Retrieve correlated entries in search chain",
            input_data={
                "seed_id": "m1",
                "correlations": {"m1": ["m2", "m3"], "m2": ["m4"], "m3": ["m4"]},
                "depth": 2,
            },
            expected_keys=["chain", "correlation_count"],
            expected_patterns=[r"m1|m2|m3|m4"],
            failure_conditions=["Chain incomplete"],
            tags=["search", "correlation"],
        )
    )

    # ============================================================================
    # PIPELINE (2 tasks) - End-to-end pipeline integration
    # ============================================================================

    tasks.append(
        GoldenTask(
            name="pipeline_pump_to_mandate",
            category=TaskCategory.PIPELINE,
            difficulty=TaskDifficulty.STANDARD,
            description="Full pump → council debate → mandate flow",
            input_data={
                "pump": {
                    "action": "analyze",
                    "target": "market",
                    "data": {"ticker": "TEST", "price": 100},
                }
            },
            expected_keys=["mandate", "status", "pillar"],
            expected_patterns=[r"active|generated"],
            failure_conditions=["Mandate not generated"],
            max_duration_ms=10000,
            tags=["pipeline", "e2e"],
        )
    )

    tasks.append(
        GoldenTask(
            name="pipeline_feedback_loop",
            category=TaskCategory.PIPELINE,
            difficulty=TaskDifficulty.STANDARD,
            description="Mandate execution feeds back to memory",
            input_data={
                "mandate_id": "m_001",
                "execution_result": {"status": "filled", "price": 99.5},
                "feedback_mode": "learn",
            },
            expected_keys=["feedback_recorded", "memory_updated"],
            expected_patterns=[r"true"],
            failure_conditions=["Feedback lost"],
            max_duration_ms=5000,
            tags=["pipeline", "feedback"],
        )
    )

    return tasks
