#!/usr/bin/env python3
"""
NCL Memory Manager - Maintenance and reporting for the memory system
"""

import argparse
import json
from pathlib import Path
import sys
from datetime import datetime, timedelta

# Add parent directories to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

try:
    from ncl_memory import get_memory_manager
    from ncl_agency_runtime.runtime.memory_api import get_memory_api
    from ncl_agency_runtime.runtime.learning_engine import get_learning_engine
    MEMORY_ENABLED = True
except ImportError:
    print("Warning: Memory system not available")
    MEMORY_ENABLED = False


class MemoryManagerCLI:
    """Command-line interface for memory system management"""

    def __init__(self):
        self.memory_manager = get_memory_manager() if MEMORY_ENABLED else None
        self.memory_api = get_memory_api() if MEMORY_ENABLED else None
        self.learning_engine = get_learning_engine() if MEMORY_ENABLED else None

    def stats(self) -> None:
        """Show memory system statistics"""
        if not MEMORY_ENABLED:
            print("Memory system not available")
            return

        stats = self.memory_api.get_memory_stats()
        print("=== NCL Memory System Statistics ===")
        print(f"Working Memory: {stats.get('working_memory_count', 0)} items")
        print(f"Short-term Memory: {stats.get('short_term_count', 0)} items")
        print(f"Long-term Memory: {stats.get('long_term_count', 0)} items")
        print(f"Consolidation Queue: {stats.get('consolidation_queue_size', 0)} items")
        print(f"Total Memories: {stats.get('working_memory_count', 0) + stats.get('short_term_count', 0) + stats.get('long_term_count', 0)}")

    def consolidate(self) -> None:
        """Consolidate memories from short-term to long-term"""
        if not MEMORY_ENABLED:
            print("Memory system not available")
            return

        count = self.memory_manager.consolidate_memories()
        print(f"Consolidated {count} memories to long-term storage")

    def prune(self) -> None:
        """Prune low-importance memories"""
        if not MEMORY_ENABLED:
            print("Memory system not available")
            return

        self.memory_manager.prune_memories()
        print("Memory pruning completed")

    def analyze(self, days: int = 7) -> None:
        """Analyze recent patterns"""
        if not MEMORY_ENABLED:
            print("Memory system not available")
            return

        analysis = self.learning_engine.analyze_recent_events(days_back=days)

        print(f"=== Pattern Analysis (Last {days} days) ===")
        print(f"Total Events: {analysis['total_events']}")

        print(f"\nTop Event Types:")
        for event_type, count in analysis['patterns'].get('event_types', {}).items():
            print(f"  {event_type}: {count}")

        print(f"\nInsights ({len(analysis['insights'])}):")
        for insight in analysis['insights']:
            print(f"  • {insight}")

        print(f"\nRecommendations ({len(analysis['recommendations'])}):")
        for rec in analysis['recommendations']:
            print(f"  • {rec}")

    def search(self, query: str, limit: int = 10) -> None:
        """Search memories"""
        if not MEMORY_ENABLED:
            print("Memory system not available")
            return

        from ncl_memory import search_memories
        results = search_memories({"content": query}, limit=limit)

        print(f"=== Search Results for '{query}' ===")
        print(f"Found {len(results)} memories:")

        for i, mem in enumerate(results, 1):
            print(f"\n{i}. [{mem.memory_type}] {mem.id[:8]}...")
            print(f"   Tags: {', '.join(mem.tags)}")
            print(f"   Importance: {mem.importance:.2f}")
            print(f"   Time: {mem.timestamp.strftime('%Y-%m-%d %H:%M')}")
            if isinstance(mem.content, str) and len(mem.content) > 100:
                print(f"   Content: {mem.content[:100]}...")
            else:
                print(f"   Content: {mem.content}")

    def learnings(self, limit: int = 10) -> None:
        """Show recent learnings"""
        if not MEMORY_ENABLED:
            print("Memory system not available")
            return

        from ncl_memory import search_memories
        results = search_memories({"memory_type": "semantic"}, limit=limit)

        print(f"=== Recent Learnings ({len(results)}) ===")

        for i, mem in enumerate(results, 1):
            content = mem.content
            if isinstance(content, dict):
                concept = content.get("concept", "Unknown")
                knowledge = content.get("knowledge", "No details")
                print(f"\n{i}. {concept}")
                print(f"   {knowledge}")
                print(f"   Confidence: {content.get('confidence', 'N/A')}")
            else:
                print(f"\n{i}. {content}")

            print(f"   Learned: {mem.timestamp.strftime('%Y-%m-%d %H:%M')}")

    def export(self, output_file: str) -> None:
        """Export memory data for backup/analysis"""
        if not MEMORY_ENABLED:
            print("Memory system not available")
            return

        # This would export memories to a JSON file
        # Implementation would depend on specific export requirements
        print(f"Export functionality not yet implemented. Would export to {output_file}")

    def maintenance(self) -> None:
        """Run full maintenance cycle"""
        if not MEMORY_ENABLED:
            print("Memory system not available")
            return

        print("Running memory maintenance...")

        # Consolidate old memories
        consolidated = self.memory_manager.consolidate_memories()
        print(f"✓ Consolidated {consolidated} memories")

        # Prune low-importance memories
        self.memory_manager.prune_memories()
        print("✓ Pruned old memories")

        # Analyze recent patterns
        analysis = self.learning_engine.analyze_recent_events(days_back=7)
        print(f"✓ Analyzed patterns: {analysis['total_events']} events, {len(analysis['insights'])} insights")

        print("Memory maintenance completed")


def main():
    parser = argparse.ArgumentParser(description="NCL Memory System Manager")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Stats command
    subparsers.add_parser("stats", help="Show memory statistics")

    # Maintenance commands
    subparsers.add_parser("consolidate", help="Consolidate short-term to long-term memory")
    subparsers.add_parser("prune", help="Prune low-importance memories")
    subparsers.add_parser("maintenance", help="Run full maintenance cycle")

    # Analysis commands
    analyze_parser = subparsers.add_parser("analyze", help="Analyze recent patterns")
    analyze_parser.add_argument("--days", type=int, default=7, help="Days to analyze")

    # Search commands
    search_parser = subparsers.add_parser("search", help="Search memories")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--limit", type=int, default=10, help="Maximum results")

    learnings_parser = subparsers.add_parser("learnings", help="Show recent learnings")
    learnings_parser.add_argument("--limit", type=int, default=10, help="Maximum results")

    # Export command
    export_parser = subparsers.add_parser("export", help="Export memory data")
    export_parser.add_argument("output_file", help="Output file path")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    cli = MemoryManagerCLI()

    if args.command == "stats":
        cli.stats()
    elif args.command == "consolidate":
        cli.consolidate()
    elif args.command == "prune":
        cli.prune()
    elif args.command == "maintenance":
        cli.maintenance()
    elif args.command == "analyze":
        cli.analyze(args.days)
    elif args.command == "search":
        cli.search(args.query, args.limit)
    elif args.command == "learnings":
        cli.learnings(args.limit)
    elif args.command == "export":
        cli.export(args.output_file)


if __name__ == "__main__":
    main()