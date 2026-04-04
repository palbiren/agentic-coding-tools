"""Tests for gate logic — soft, hard, and pre-merge gates for validation pipeline.

TDD tests written before implementation (task 5.5).
Tests cover:
- check_phase_status parsing of validation-report.md (generic + smoke)
- Soft gate: always returns 'continue' regardless of status
- Hard gate: returns 'halt' on fail/skipped/missing, 'continue' on pass
- Pre-merge gate: checks all required phases, supports --force override
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure scripts dir is importable
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from gate_logic import (
    _check_phase_with_aliases,
    check_phase_status,
    check_smoke_status,
    hard_gate,
    pre_merge_gate,
    soft_gate,
)

# Helper: full passing report with all required phases
_ALL_PASS = (
    "## Smoke Tests\n\n- **Status**: pass\n\n"
    "## Security\n\n- **Status**: pass\n\n"
    "## E2E Tests\n\n- **Status**: pass\n"
)


class TestCheckSmokeStatus:
    """Test parsing validation-report.md for smoke status."""

    def test_pass_status(self, tmp_path: Path) -> None:
        """Should return 'pass' when Status: pass."""
        report = tmp_path / "validation-report.md"
        report.write_text(
            "## Smoke Tests\n\n"
            "- **Status**: pass\n"
            "- **Environment**: docker\n"
        )

        assert check_smoke_status(str(report)) == "pass"

    def test_fail_status(self, tmp_path: Path) -> None:
        """Should return 'fail' when Status: fail."""
        report = tmp_path / "validation-report.md"
        report.write_text(
            "## Smoke Tests\n\n"
            "- **Status**: fail\n"
            "- **Environment**: docker\n"
        )

        assert check_smoke_status(str(report)) == "fail"

    def test_skipped_status(self, tmp_path: Path) -> None:
        """Should return 'skipped' when Status: skipped."""
        report = tmp_path / "validation-report.md"
        report.write_text(
            "## Smoke Tests\n\n"
            "- **Status**: skipped\n"
        )

        assert check_smoke_status(str(report)) == "skipped"

    def test_missing_report_file(self) -> None:
        """Should return 'missing' when file doesn't exist."""
        assert check_smoke_status("/nonexistent/report.md") == "missing"

    def test_missing_smoke_section(self, tmp_path: Path) -> None:
        """Should return 'missing' when ## Smoke Tests section absent."""
        report = tmp_path / "validation-report.md"
        report.write_text(
            "## Spec Compliance\n\n"
            "All requirements met.\n"
        )

        assert check_smoke_status(str(report)) == "missing"

    def test_smoke_section_without_status_line(self, tmp_path: Path) -> None:
        """Should return 'missing' when section exists but no Status line."""
        report = tmp_path / "validation-report.md"
        report.write_text(
            "## Smoke Tests\n\n"
            "No results yet.\n"
        )

        assert check_smoke_status(str(report)) == "missing"

    def test_status_among_other_sections(self, tmp_path: Path) -> None:
        """Should find status even when other sections exist."""
        report = tmp_path / "validation-report.md"
        report.write_text(
            "## Spec Compliance\n\n"
            "All requirements met.\n\n"
            "## Smoke Tests\n\n"
            "- **Status**: pass\n"
            "- **Environment**: docker\n\n"
            "## Security\n\n"
            "No issues.\n"
        )

        assert check_smoke_status(str(report)) == "pass"


class TestSoftGate:
    """Test soft gate logic (implement-feature).

    Soft gate always returns 'continue' — never blocks.
    """

    def test_pass_continues(self, tmp_path: Path) -> None:
        """Status: pass -> continue."""
        report = tmp_path / "validation-report.md"
        report.write_text("## Smoke Tests\n\n- **Status**: pass\n")

        action, reason = soft_gate(str(report))
        assert action == "continue"

    def test_fail_warns_and_continues(self, tmp_path: Path) -> None:
        """Status: fail -> warn, continue."""
        report = tmp_path / "validation-report.md"
        report.write_text("## Smoke Tests\n\n- **Status**: fail\n")

        action, reason = soft_gate(str(report))
        assert action == "continue"
        assert "fail" in reason.lower() or "warn" in reason.lower()

    def test_skipped_warns_and_continues(self, tmp_path: Path) -> None:
        """Status: skipped -> warn, continue."""
        report = tmp_path / "validation-report.md"
        report.write_text("## Smoke Tests\n\n- **Status**: skipped\n")

        action, reason = soft_gate(str(report))
        assert action == "continue"
        assert "skip" in reason.lower() or "warn" in reason.lower()

    def test_missing_report_continues(self) -> None:
        """Missing report -> continue (deploy+smoke will be triggered)."""
        action, reason = soft_gate("/nonexistent/report.md")
        assert action == "continue"


class TestHardGate:
    """Test hard gate logic (cleanup-feature).

    hard_gate() delegates to pre_merge_gate() and checks all required
    phases (smoke, security, E2E). Blocks on any non-pass status.
    """

    def test_all_pass_continues(self, tmp_path: Path) -> None:
        """All phases pass -> continue to merge."""
        report = tmp_path / "validation-report.md"
        report.write_text(_ALL_PASS)

        action, reason = hard_gate(str(report))
        assert action == "continue"

    def test_smoke_fail_halts(self, tmp_path: Path) -> None:
        """Smoke fail -> halt."""
        report = tmp_path / "validation-report.md"
        report.write_text(
            "## Smoke Tests\n\n- **Status**: fail\n\n"
            "## Security\n\n- **Status**: pass\n\n"
            "## E2E Tests\n\n- **Status**: pass\n"
        )

        action, reason = hard_gate(str(report))
        assert action == "halt"
        assert "fail" in reason.lower()

    def test_smoke_only_halts(self, tmp_path: Path) -> None:
        """Only smoke present -> halt (security + E2E missing)."""
        report = tmp_path / "validation-report.md"
        report.write_text("## Smoke Tests\n\n- **Status**: pass\n")

        action, reason = hard_gate(str(report))
        assert action == "halt"

    def test_missing_report_halts(self) -> None:
        """Missing report -> halt."""
        action, reason = hard_gate("/nonexistent/report.md")
        assert action == "halt"

    def test_after_rerun_all_pass_continues(self, tmp_path: Path) -> None:
        """After re-run with all pass -> continue."""
        report = tmp_path / "validation-report.md"
        report.write_text(_ALL_PASS)

        action, reason = hard_gate(str(report))
        assert action == "continue"

    def test_missing_section_halts(self, tmp_path: Path) -> None:
        """Report exists but missing required sections -> halt."""
        report = tmp_path / "validation-report.md"
        report.write_text("## Spec Compliance\n\nDone.\n")

        action, reason = hard_gate(str(report))
        assert action == "halt"


class TestCheckPhaseStatus:
    """Test generic phase status parsing."""

    def test_security_pass(self, tmp_path: Path) -> None:
        report = tmp_path / "validation-report.md"
        report.write_text(
            "## Security\n\n"
            "- **Status**: pass\n"
        )
        assert check_phase_status(str(report), "Security") == "pass"

    def test_security_fail(self, tmp_path: Path) -> None:
        report = tmp_path / "validation-report.md"
        report.write_text(
            "## Security\n\n"
            "- **Status**: fail\n"
        )
        assert check_phase_status(str(report), "Security") == "fail"

    def test_e2e_pass(self, tmp_path: Path) -> None:
        report = tmp_path / "validation-report.md"
        report.write_text(
            "## E2E Tests\n\n"
            "- **Status**: pass\n"
        )
        assert check_phase_status(str(report), "E2E Tests") == "pass"

    def test_missing_section(self, tmp_path: Path) -> None:
        report = tmp_path / "validation-report.md"
        report.write_text("## Other\n\nStuff.\n")
        assert check_phase_status(str(report), "Security") == "missing"

    def test_missing_file(self) -> None:
        assert check_phase_status("/nonexistent", "Security") == "missing"


class TestPreMergeGate:
    """Test pre-merge gate — checks all required phases."""

    def test_all_pass_continues(self, tmp_path: Path) -> None:
        """All required phases pass -> continue."""
        report = tmp_path / "validation-report.md"
        report.write_text(_ALL_PASS)

        action, _, statuses = pre_merge_gate(str(report))
        assert action == "continue"
        assert statuses["Smoke Tests"] == "pass"
        assert statuses["Security"] == "pass"
        assert statuses["E2E Tests"] == "pass"

    def test_smoke_fail_halts(self, tmp_path: Path) -> None:
        """Smoke tests fail -> halt."""
        report = tmp_path / "validation-report.md"
        report.write_text(
            "## Smoke Tests\n\n- **Status**: fail\n\n"
            "## Security\n\n- **Status**: pass\n\n"
            "## E2E Tests\n\n- **Status**: pass\n"
        )

        action, reason, statuses = pre_merge_gate(str(report))
        assert action == "halt"
        assert "Smoke tests: fail" in reason

    def test_security_missing_halts(self, tmp_path: Path) -> None:
        """Security section missing -> halt."""
        report = tmp_path / "validation-report.md"
        report.write_text(
            "## Smoke Tests\n\n- **Status**: pass\n\n"
            "## E2E Tests\n\n- **Status**: pass\n"
        )

        action, reason, statuses = pre_merge_gate(str(report))
        assert action == "halt"
        assert "Security scan: missing" in reason

    def test_e2e_skipped_halts(self, tmp_path: Path) -> None:
        """E2E skipped -> halt."""
        report = tmp_path / "validation-report.md"
        report.write_text(
            "## Smoke Tests\n\n- **Status**: pass\n\n"
            "## Security\n\n- **Status**: pass\n\n"
            "## E2E Tests\n\n- **Status**: skipped\n"
        )

        action, reason, statuses = pre_merge_gate(str(report))
        assert action == "halt"
        assert "E2E tests: skipped" in reason

    def test_multiple_failures_reported(self, tmp_path: Path) -> None:
        """Multiple failures are all reported."""
        report = tmp_path / "validation-report.md"
        report.write_text(
            "## Smoke Tests\n\n- **Status**: fail\n\n"
            "## Security\n\n- **Status**: fail\n"
        )

        action, reason, statuses = pre_merge_gate(str(report))
        assert action == "halt"
        assert "Smoke tests: fail" in reason
        assert "Security scan: fail" in reason
        assert "E2E tests: missing" in reason

    def test_missing_report_halts(self) -> None:
        """No report file -> halt (all phases missing)."""
        action, reason, statuses = pre_merge_gate("/nonexistent/report.md")
        assert action == "halt"
        assert all(s == "missing" for s in statuses.values())

    def test_force_overrides_failures(self, tmp_path: Path) -> None:
        """--force allows merge despite failures."""
        report = tmp_path / "validation-report.md"
        report.write_text(
            "## Smoke Tests\n\n- **Status**: fail\n\n"
            "## Security\n\n- **Status**: fail\n"
        )

        action, reason, statuses = pre_merge_gate(str(report), force=True)
        assert action == "continue"
        assert "FORCED OVERRIDE" in reason
        assert "Smoke tests: fail" in reason

    def test_force_on_passing_continues(self, tmp_path: Path) -> None:
        """--force on passing report still continues normally."""
        report = tmp_path / "validation-report.md"
        report.write_text(_ALL_PASS)

        action, reason, _ = pre_merge_gate(str(report), force=True)
        assert action == "continue"
        assert "FORCED" not in reason  # No override needed


class TestHeadingAliases:
    """Test that heading aliases are accepted for E2E and Security."""

    def test_e2e_short_heading(self, tmp_path: Path) -> None:
        """'## E2E' is accepted as an alias for '## E2E Tests'."""
        report = tmp_path / "validation-report.md"
        report.write_text(
            "## Smoke Tests\n\n- **Status**: pass\n\n"
            "## Security\n\n- **Status**: pass\n\n"
            "## E2E\n\n- **Status**: pass\n"
        )

        action, _, statuses = pre_merge_gate(str(report))
        assert action == "continue"
        assert statuses["E2E"] == "pass"

    def test_end_to_end_heading(self, tmp_path: Path) -> None:
        """'## End-to-End Tests' is accepted as an alias."""
        report = tmp_path / "validation-report.md"
        report.write_text(
            "## Smoke Tests\n\n- **Status**: pass\n\n"
            "## Security\n\n- **Status**: pass\n\n"
            "## End-to-End Tests\n\n- **Status**: pass\n"
        )

        action, _, statuses = pre_merge_gate(str(report))
        assert action == "continue"
        assert statuses["End-to-End Tests"] == "pass"

    def test_security_scan_heading(self, tmp_path: Path) -> None:
        """'## Security Scan' is accepted as an alias for '## Security'."""
        report = tmp_path / "validation-report.md"
        report.write_text(
            "## Smoke Tests\n\n- **Status**: pass\n\n"
            "## Security Scan\n\n- **Status**: pass\n\n"
            "## E2E Tests\n\n- **Status**: pass\n"
        )

        action, _, statuses = pre_merge_gate(str(report))
        assert action == "continue"
        assert statuses["Security Scan"] == "pass"

    def test_alias_with_failure(self, tmp_path: Path) -> None:
        """Alias heading still reports failure correctly."""
        report = tmp_path / "validation-report.md"
        report.write_text(
            "## Smoke Tests\n\n- **Status**: pass\n\n"
            "## Security\n\n- **Status**: pass\n\n"
            "## E2E\n\n- **Status**: fail\n"
        )

        action, reason, _ = pre_merge_gate(str(report))
        assert action == "halt"
        assert "E2E tests: fail" in reason

    def test_check_phase_with_aliases_returns_first_match(
        self, tmp_path: Path,
    ) -> None:
        """_check_phase_with_aliases returns the first matching heading."""
        report = tmp_path / "validation-report.md"
        report.write_text("## E2E\n\n- **Status**: pass\n")

        status, heading = _check_phase_with_aliases(
            str(report), ["E2E Tests", "E2E", "End-to-End Tests"],
        )
        assert status == "pass"
        assert heading == "E2E"

    def test_check_phase_with_aliases_missing(self, tmp_path: Path) -> None:
        """_check_phase_with_aliases returns 'missing' with primary heading."""
        report = tmp_path / "validation-report.md"
        report.write_text("## Other\n\nStuff.\n")

        status, heading = _check_phase_with_aliases(
            str(report), ["E2E Tests", "E2E"],
        )
        assert status == "missing"
        assert heading == "E2E Tests"  # Falls back to primary heading
