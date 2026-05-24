"""
Example usage of Council Runner v1.

Demonstrates:
1. Running a parallel council with Planner/Skeptic/Risk agents
2. Saving and retrieving runs
3. Replaying with different models/temperatures
4. Comparing runs
"""

import asyncio

from council_runner import (
    CouncilRunStore,
    ReplayEngine,
    run_parallel_council,
)


async def main():
    """Run example council execution."""

    # Define a topic and prompt
    topic = "Strategic AI Integration Plan"
    prompt = """
    Our organization needs to integrate AI into our core product offering.

    Key considerations:
    - We have 6 months to launch the first MVP
    - Budget is $2M for initial development
    - We need 3 engineers and 1 product manager
    - Customers are asking for it but we don't have deep AI expertise yet

    What should be our strategic approach?
    """

    print("=" * 80)
    print("COUNCIL RUNNER v1 — Example Execution")
    print("=" * 80)
    print(f"\nTopic: {topic}")
    print(f"Prompt: {prompt[:200]}...\n")

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Run the parallel council
    # ─────────────────────────────────────────────────────────────────────────

    print("Running parallel council (Planner → Skeptic → Risk)...")
    try:
        record = await run_parallel_council(
            topic=topic,
            prompt=prompt,
            context={"budget_millions": 2, "timeline_months": 6},
        )

        print(f"\n✓ Council completed in {record.total_duration_ms}ms")
        print(f"  Run ID: {record.run_id}")
        print(f"  Replay Seed: {record.replay_seed}\n")

        # Display agent outputs
        print("Agent Outputs:")
        print("-" * 80)
        for output in record.agent_outputs:
            print(
                f"\n{output.role.value.upper()} (Confidence: {output.confidence:.1%}, "
                f"{output.duration_ms}ms)"
            )
            print(f"  Model: {output.model_used}")
            print(
                f"  Key Points: {', '.join(output.key_points[:2]) if output.key_points else 'N/A'}"
            )
            if output.risks_identified:
                print(f"  Risks: {', '.join(output.risks_identified[:2])}")
            if output.dissent_notes:
                print(f"  Dissent: {', '.join(output.dissent_notes[:1])}")

        # Display consensus
        print("\n" + "=" * 80)
        print("CONSENSUS")
        print("=" * 80)
        if record.consensus:
            print(f"Consensus Score: {record.consensus.consensus_score}/100")
            print(
                f"Agreement Areas: {', '.join(record.consensus.agreement_areas[:2]) if record.consensus.agreement_areas else 'N/A'}"
            )
            print(
                f"Dissent Areas: {', '.join(record.consensus.dissent_areas[:2]) if record.consensus.dissent_areas else 'N/A'}"
            )
            print(
                f"Risk Flags: {', '.join(record.consensus.risk_flags[:2]) if record.consensus.risk_flags else 'N/A'}"
            )
            if record.consensus.recommendations:
                print(f"Recommendations: {', '.join(record.consensus.recommendations[:2])}")

        # ─────────────────────────────────────────────────────────────────────
        # 2. Save the run
        # ─────────────────────────────────────────────────────────────────────

        print("\n" + "=" * 80)
        print("PERSISTENCE")
        print("=" * 80)

        store = CouncilRunStore(data_dir="./data")
        await store.save_run(record)
        print("✓ Run saved to store")

        # Retrieve and verify
        retrieved = await store.get_run(record.run_id)
        print("✓ Run retrieved from store")
        print(f"  Topic: {retrieved.topic}")
        print(f"  Agents: {len(retrieved.agent_outputs)} outputs")

        # Get stats
        stats = await store.get_stats()
        print("\nStore Statistics:")
        print(f"  Total runs: {stats['total_runs']}")
        print(f"  Avg consensus score: {stats['avg_consensus_score']}")
        print(f"  Avg duration: {stats['avg_duration_ms']}ms")

        # ─────────────────────────────────────────────────────────────────────
        # 3. Replay the run
        # ─────────────────────────────────────────────────────────────────────

        print("\n" + "=" * 80)
        print("REPLAY")
        print("=" * 80)

        replay_engine = ReplayEngine(data_dir="./data")
        print(f"Replaying run {record.run_id[:8]}...")

        try:
            replayed = await replay_engine.replay(
                record.run_id,
                force_models={"planner": "grok", "skeptic": "claude"},
            )

            print(f"✓ Replay completed (new run: {replayed.run_id[:8]})")
            print(f"  Original consensus: {record.consensus.consensus_score}")
            print(f"  Replay consensus: {replayed.consensus.consensus_score}")

            # Compare
            comparison = await replay_engine.compare_runs(record.run_id, replayed.run_id)
            print("\nComparison Report:")
            print(f"  Score delta: {comparison['consensus_score_delta']}")
            print(f"  Duration delta: {comparison['duration_delta_ms']}ms")
            if comparison["agreement_areas_changed"]["added"]:
                print(
                    f"  New agreement: {', '.join(comparison['agreement_areas_changed']['added'][:1])}"
                )

        except Exception as e:
            print(f"✗ Replay failed: {e}")
            print("  (This is expected if model APIs are not configured)")

        # ─────────────────────────────────────────────────────────────────────
        # 4. Provenance chain
        # ─────────────────────────────────────────────────────────────────────

        print("\n" + "=" * 80)
        print("PROVENANCE")
        print("=" * 80)

        provenance = await store.get_provenance(record.run_id)
        print(f"Run: {provenance['run_id'][:8]}")
        print(f"Topic: {provenance['topic']}")
        print("Agents:")
        for agent in provenance["agents"]:
            print(
                f"  • {agent['role']:8s} | Model: {agent['model']:20s} | "
                f"Confidence: {agent['confidence']:.1%} | {agent['duration_ms']}ms"
            )
        print(f"Replay Seed: {provenance['replay_seed']}")

    except Exception as e:
        print(f"✗ Council execution failed: {e}")
        print("\nNote: This example requires API keys for Claude, Grok, or Ollama.")
        print("  Set ANTHROPIC_API_KEY, XAI_API_KEY, or OLLAMA_HOST environment variables.")


if __name__ == "__main__":
    asyncio.run(main())
