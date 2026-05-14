"""CI Lint for Privacy-Safe Telemetry.

Validates telemetry files for schema compliance and PII leakage.
Run as: python -m runtime.telemetry.lint /path/to/data
"""

import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .schema import (
    TelemetryRecord,
    RedactionRule,
)

logger = logging.getLogger(__name__)


class TelemetryLinter:
    """Validates telemetry files for schema and privacy compliance."""

    # Additional PII patterns beyond RedactionRule
    ADDITIONAL_PII_PATTERNS = [
        (
            "credit_card",
            re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
        ),  # Credit card
        (
            "domain_password",
            re.compile(
                r"(?i)(password|passwd|pwd|pass)\s*[:=]\s*[^\s\",}]+",
            ),
        ),  # Password assignment
    ]

    def __init__(self, data_dir: str | Path):
        """Initialize linter.

        Args:
            data_dir: Root data directory containing telemetry/ subdirectory
        """
        self.data_dir = Path(data_dir)
        self.telemetry_dir = self.data_dir / "telemetry"
        self.violations: list[dict] = []

    def scan(self) -> list[dict]:
        """Scan all telemetry files for violations.

        Returns:
            List of violation dicts with file, line, issue, value keys
        """
        self.violations = []

        if not self.telemetry_dir.exists():
            logger.info(f"Telemetry directory does not exist: {self.telemetry_dir}")
            return self.violations

        # Find all NDJSON files
        ndjson_files = list(self.telemetry_dir.glob("*.ndjson"))
        if not ndjson_files:
            logger.info(f"No .ndjson files found in {self.telemetry_dir}")
            return self.violations

        logger.info(f"Scanning {len(ndjson_files)} telemetry files")

        for filepath in sorted(ndjson_files):
            self._scan_file(filepath)

        return self.violations

    def _scan_file(self, filepath: Path) -> None:
        """Scan a single NDJSON file.

        Args:
            filepath: Path to .ndjson file
        """
        try:
            with open(filepath) as f:
                for line_num, line in enumerate(f, 1):
                    if not line.strip():
                        continue
                    self._scan_line(filepath, line_num, line)
        except Exception as e:
            self.violations.append(
                {
                    "file": str(filepath),
                    "line": 0,
                    "issue": f"Failed to read file: {e}",
                    "value": None,
                }
            )

    def _scan_line(self, filepath: Path, line_num: int, line: str) -> None:
        """Scan a single line (JSON record).

        Args:
            filepath: Source file path
            line_num: Line number (1-indexed)
            line: Raw JSON line
        """
        # Parse JSON
        try:
            data = json.loads(line)
        except json.JSONDecodeError as e:
            self.violations.append(
                {
                    "file": str(filepath),
                    "line": line_num,
                    "issue": f"Invalid JSON: {e}",
                    "value": line[:100],
                }
            )
            return

        # Validate schema
        try:
            record = TelemetryRecord(**data)
        except Exception as e:
            self.violations.append(
                {
                    "file": str(filepath),
                    "line": line_num,
                    "issue": f"Schema validation failed: {e}",
                    "value": str(data.get("workflow", "unknown")),
                }
            )
            return

        # Check for PII in payload
        if record.payload:
            pii_issues = self._check_pii_in_dict(record.payload)
            for issue, value in pii_issues:
                self.violations.append(
                    {
                        "file": str(filepath),
                        "line": line_num,
                        "issue": f"PII detected in payload: {issue}",
                        "value": value[:50] if value else None,
                    }
                )

        # Check for PII in workflow/action (should be safe, but verify)
        for field in ["workflow", "action"]:
            value = getattr(record, field, "")
            pii_issues = self._check_pii_in_string(value)
            if pii_issues:
                for issue, val in pii_issues:
                    self.violations.append(
                        {
                            "file": str(filepath),
                            "line": line_num,
                            "issue": f"Suspicious pattern in {field}: {issue}",
                            "value": val[:50] if val else None,
                        }
                    )

    def _check_pii_in_dict(self, data: dict) -> list[tuple[str, Optional[str]]]:
        """Check dict for PII patterns.

        Args:
            data: Dictionary to check

        Returns:
            List of (issue, value) tuples
        """
        issues = []

        def check_value(v: any, path: str = ""):
            if isinstance(v, str):
                pii = self._check_pii_in_string(v)
                for issue, val in pii:
                    issues.append((f"{path}: {issue}", val))
            elif isinstance(v, dict):
                for k, subv in v.items():
                    check_value(subv, f"{path}.{k}")
            elif isinstance(v, list):
                for idx, item in enumerate(v):
                    check_value(item, f"{path}[{idx}]")

        for key, value in data.items():
            check_value(value, key)

        return issues

    def _check_pii_in_string(self, text: str) -> list[tuple[str, Optional[str]]]:
        """Check string for PII patterns.

        Args:
            text: String to check

        Returns:
            List of (issue, matched_text) tuples
        """
        if not isinstance(text, str):
            return []

        issues = []

        # Check RedactionRule patterns
        for name, pattern, _ in RedactionRule.PATTERNS:
            match = pattern.search(text)
            if match:
                issues.append((f"Matches {name} pattern", match.group(0)))

        # Check additional patterns
        for name, pattern in self.ADDITIONAL_PII_PATTERNS:
            match = pattern.search(text)
            if match:
                issues.append((f"Matches {name} pattern", match.group(0)))

        return issues

    def report(self, verbose: bool = False) -> None:
        """Print violation report.

        Args:
            verbose: Print full violation details
        """
        if not self.violations:
            print("✓ All telemetry files passed validation")
            return

        print(f"✗ Found {len(self.violations)} violation(s):\n")
        for i, v in enumerate(self.violations, 1):
            print(f"{i}. {v['file']}:{v['line']}")
            print(f"   Issue: {v['issue']}")
            if verbose and v["value"]:
                print(f"   Value: {v['value']}")
            print()


def scan_telemetry_files(data_dir: str | Path) -> list[dict]:
    """Standalone function to scan telemetry files.

    Args:
        data_dir: Root data directory

    Returns:
        List of violation dicts
    """
    linter = TelemetryLinter(data_dir)
    return linter.scan()


def main():
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    if len(sys.argv) < 2:
        print("Usage: python -m runtime.telemetry.lint <data_dir>")
        print("  Example: python -m runtime.telemetry.lint /path/to/data")
        sys.exit(1)

    data_dir = sys.argv[1]
    verbose = "--verbose" in sys.argv

    linter = TelemetryLinter(data_dir)
    violations = linter.scan()
    linter.report(verbose=verbose)

    # Exit code
    exit_code = 1 if violations else 0
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
