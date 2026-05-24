"""Golden Task Suite v1 — CI gate for regression testing."""

import asyncio
import sys

from .runner import GoldenTaskRunner


def print_header(text: str) -> None:
    """Print formatted header."""
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70)


def print_summary(result) -> None:
    """Print test results summary."""
    print_header("GOLDEN TASK SUITE RESULTS")

    print(f"\nTotal Tasks:     {result.total_tasks}")
    print(f"Passed:          {result.passed} ✓")
    print(f"Failed:          {result.failed} ✗")
    if result.skipped > 0:
        print(f"Skipped:         {result.skipped}")

    print(f"\nPass Rate:       {result.pass_rate:.1f}%")
    print(f"Duration:        {result.total_duration_ms:.1f}ms")

    if result.regression_detected:
        print("\n⚠️  REGRESSION DETECTED")
        print(f"Regressions:     {len(result.regression_tasks)}")
        for task_name in result.regression_tasks[:5]:
            print(f"  - {task_name}")
        if len(result.regression_tasks) > 5:
            print(f"  ... and {len(result.regression_tasks) - 5} more")


def print_failures(result) -> None:
    """Print detailed failure information."""
    failed_results = [r for r in result.results if not r.passed]

    if not failed_results:
        return

    print_header("FAILURES")

    for i, task_result in enumerate(failed_results[:10], 1):
        print(f"\n{i}. {task_result.task_name}")
        print(f"   ID: {task_result.task_id}")
        print(f"   Duration: {task_result.duration_ms:.1f}ms")

        if task_result.errors:
            print("   Errors:")
            for error in task_result.errors:
                print(f"     - {error}")

        if task_result.failure_reasons:
            print("   Reasons:")
            for reason in task_result.failure_reasons:
                print(f"     - {reason}")

    if len(failed_results) > 10:
        print(f"\n... and {len(failed_results) - 10} more failures")


def print_passing_tasks(result) -> None:
    """Print sample of passing tasks."""
    passed_results = [r for r in result.results if r.passed]

    if not passed_results:
        return

    print_header("SAMPLE PASSING TASKS")

    for task_result in passed_results[:5]:
        print(f"✓ {task_result.task_name:50s} {task_result.duration_ms:7.1f}ms")

    if len(passed_results) > 5:
        print(f"... and {len(passed_results) - 5} more passing tasks")


async def main() -> int:
    """
    Run CI gate: execute suite, check thresholds, exit with appropriate code.

    Returns:
        Exit code: 0 if pass, 1 if fail.
    """
    print("\n🧠 NCL Brain Pipeline — Golden Task Suite v1.0")
    print("   RESONANCE ENERGY / NARTIX Ecosystem")

    # Initialize runner
    runner = GoldenTaskRunner(data_dir="/sessions/focused-clever-mccarthy/mnt/dev/NCL/runtime")

    # Run suite
    print("\nRunning 50 golden tasks...")
    result = await runner.run_suite()

    # Save results
    saved_path = await runner.save_results(result)
    print(f"Results saved: {saved_path}")

    # Print detailed report
    print_summary(result)
    print_passing_tasks(result)
    print_failures(result)

    # Determine gate status
    print_header("CI GATE STATUS")

    min_pass_rate = 95.0
    has_regressions = result.regression_detected

    passed_gate = result.pass_rate >= min_pass_rate and not has_regressions

    if passed_gate:
        print("\n✓ GATE PASSED")
        print(f"  Pass rate {result.pass_rate:.1f}% >= {min_pass_rate}%")
        if not has_regressions:
            print("  No regressions detected")
        return 0
    else:
        print("\n✗ GATE FAILED")
        if result.pass_rate < min_pass_rate:
            print(
                f"  Pass rate {result.pass_rate:.1f}% < {min_pass_rate}% "
                f"({result.failed} failures)"
            )
        if has_regressions:
            print(f"  {len(result.regression_tasks)} regression(s) detected")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
