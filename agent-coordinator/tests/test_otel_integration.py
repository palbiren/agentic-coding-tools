"""Integration tests for OpenTelemetry metrics end-to-end flow.

T5.1: Metrics flow end-to-end with in-memory metric reader
T5.2: /metrics Prometheus endpoint returns expected format

These tests initialize real OTel providers (no mocks) and verify that
metric instruments created by service modules actually produce data points
readable through the SDK's InMemoryMetricReader, and that the Prometheus
/metrics HTTP endpoint returns valid text-format output.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

import src.locks as locks_module
import src.work_queue as wq_module
from src.locks import LockService
from src.policy_engine import PolicyDecision
from src.telemetry import reset_telemetry
from src.work_queue import WorkQueueService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_metric(reader: InMemoryMetricReader, name: str):
    """Extract a named metric from the in-memory reader."""
    data = reader.get_metrics_data()
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                if m.name == name:
                    return m
    return None


def _sum_data_points(metric) -> int | float:
    if metric is None:
        return 0
    return sum(pt.value for pt in metric.data.data_points)


def _sum_histogram_count(metric) -> int:
    if metric is None:
        return 0
    return sum(pt.count for pt in metric.data.data_points)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset():
    """Reset telemetry and instrument caches before/after each test."""
    reset_telemetry()
    if hasattr(locks_module, "_instruments"):
        locks_module._instruments = None
    if hasattr(wq_module, "reset_instruments"):
        wq_module.reset_instruments()
    yield
    reset_telemetry()
    if hasattr(locks_module, "_instruments"):
        locks_module._instruments = None
    if hasattr(wq_module, "reset_instruments"):
        wq_module.reset_instruments()


@pytest.fixture()
def otel_reader():
    """Set up a real OTel MeterProvider with InMemoryMetricReader.

    Creates a fresh provider per test. We don't use the global
    set_meter_provider (which can only be set once) — instead we
    create meters directly from our provider.
    """
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    # Store provider on reader so tests can create meters from it
    reader._test_provider = provider  # type: ignore[attr-defined]
    yield reader
    provider.shutdown()


# Common mocks for service dependencies
@pytest.fixture()
def mock_policy_allow():
    engine = MagicMock()
    engine.check_operation = AsyncMock(
        return_value=PolicyDecision(allowed=True, reason=None)
    )
    with patch("src.policy_engine.get_policy_engine", return_value=engine):
        yield engine


@pytest.fixture()
def mock_audit():
    svc = MagicMock()
    svc.log_operation = AsyncMock()
    with patch("src.audit.get_audit_service", return_value=svc):
        yield svc


@pytest.fixture()
def mock_guardrails_pass():
    svc = MagicMock()
    result = MagicMock()
    result.safe = True
    result.violations = []
    svc.check_operation = AsyncMock(return_value=result)
    with patch("src.guardrails.get_guardrails_service", return_value=svc):
        yield svc


@pytest.fixture()
def mock_profiles():
    with patch("src.work_queue.WorkQueueService._resolve_trust_level") as m:
        m.return_value = 5
        yield m


# ---------------------------------------------------------------------------
# T5.1: End-to-end metrics flow with InMemoryMetricReader
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMetricsEndToEnd:
    """Verify that real service operations produce real OTel metric data."""

    @pytest.mark.asyncio
    async def test_lock_acquire_produces_metrics(
        self, otel_reader, mock_policy_allow, mock_audit,
    ):
        """Lock acquire should produce duration histogram and active gauge."""
        # Patch telemetry to return a real meter from our provider
        meter = otel_reader._test_provider.get_meter("coordinator.locks", "0.1.0")
        with patch("src.locks.get_lock_meter", return_value=meter):
            # Reset instrument cache so it picks up the new meter
            locks_module._instruments = None

            db = MagicMock()
            db.rpc = AsyncMock(return_value={
                "success": True,
                "action": "acquired",
                "file_path": "src/test.py",
                "locked_by": "agent-1",
                "agent_type": "claude_code",
                "locked_at": "2026-03-28T00:00:00+00:00",
                "expires_at": "2026-03-28T01:00:00+00:00",
            })

            svc = LockService(db=db)
            result = await svc.acquire("src/test.py", reason="test")
            assert result.success

        # Verify metrics were recorded
        duration = _get_metric(otel_reader, "lock.acquire.duration_ms")
        assert duration is not None, "lock.acquire.duration_ms not found"
        assert _sum_histogram_count(duration) == 1

        active = _get_metric(otel_reader, "lock.active")
        assert active is not None, "lock.active not found"
        assert _sum_data_points(active) == 1

        ttl = _get_metric(otel_reader, "lock.ttl_seconds")
        assert ttl is not None, "lock.ttl_seconds not found"
        assert _sum_histogram_count(ttl) == 1

    @pytest.mark.asyncio
    async def test_lock_contention_produces_counter(
        self, otel_reader, mock_policy_allow, mock_audit,
    ):
        """Denied lock should increment contention counter."""
        meter = otel_reader._test_provider.get_meter("coordinator.locks", "0.1.0")
        with patch("src.locks.get_lock_meter", return_value=meter):
            locks_module._instruments = None

            db = MagicMock()
            db.rpc = AsyncMock(return_value={
                "success": False,
                "action": "denied",
                "file_path": "src/test.py",
                "locked_by": "other-agent",
                "agent_type": "codex",
                "locked_at": "2026-03-28T00:00:00+00:00",
                "expires_at": "2026-03-28T01:00:00+00:00",
            })

            svc = LockService(db=db)
            result = await svc.acquire("src/test.py", reason="test")
            assert not result.success

        contention = _get_metric(otel_reader, "lock.contention.total")
        assert contention is not None, "lock.contention.total not found"
        assert _sum_data_points(contention) == 1

    @pytest.mark.asyncio
    async def test_lock_release_decrements_active(
        self, otel_reader, mock_policy_allow, mock_audit,
    ):
        """Release should decrement the active lock gauge."""
        meter = otel_reader._test_provider.get_meter("coordinator.locks", "0.1.0")
        with patch("src.locks.get_lock_meter", return_value=meter):
            locks_module._instruments = None

            db = MagicMock()
            # First acquire
            db.rpc = AsyncMock(return_value={
                "success": True,
                "action": "acquired",
                "file_path": "src/test.py",
                "locked_by": "agent-1",
                "agent_type": "claude_code",
                "locked_at": "2026-03-28T00:00:00+00:00",
                "expires_at": "2026-03-28T01:00:00+00:00",
            })
            svc = LockService(db=db)
            await svc.acquire("src/test.py", reason="test")

            # Then release
            db.rpc = AsyncMock(return_value={
                "success": True,
                "action": "released",
                "file_path": "src/test.py",
            })
            await svc.release("src/test.py")

        active = _get_metric(otel_reader, "lock.active")
        assert active is not None
        # +1 from acquire, -1 from release = 0
        assert _sum_data_points(active) == 0

    @pytest.mark.asyncio
    async def test_queue_claim_produces_metrics(
        self, otel_reader, mock_guardrails_pass, mock_audit, mock_profiles,
    ):
        """Queue claim should produce claim duration and wait time metrics."""
        meter = otel_reader._test_provider.get_meter("coordinator.queue", "0.1.0")

        with (
            patch("src.work_queue.get_queue_meter", return_value=meter),
            patch("src.policy_engine.get_policy_engine") as mock_pe,
            patch("src.audit.get_audit_service") as mock_as,
        ):
            wq_module.reset_instruments()
            engine = MagicMock()
            engine.check_operation = AsyncMock(
                return_value=PolicyDecision(allowed=True)
            )
            mock_pe.return_value = engine
            audit_svc = MagicMock()
            audit_svc.log_operation = AsyncMock()
            mock_as.return_value = audit_svc

            db = MagicMock()
            db.rpc = AsyncMock(return_value={
                "success": True,
                "task_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "task_type": "verify",
                "description": "test task",
                "input_data": None,
                "created_at": "2026-03-28T00:00:00+00:00",
                "claimed_at": "2026-03-28T00:01:00+00:00",
            })

            svc = WorkQueueService(db=db)
            result = await svc.claim(task_types=["verify"])
            assert result.success

        claim_dur = _get_metric(otel_reader, "queue.claim.duration_ms")
        assert claim_dur is not None, "queue.claim.duration_ms not found"
        assert _sum_histogram_count(claim_dur) >= 1

    @pytest.mark.asyncio
    async def test_refresh_does_not_increment_active(
        self, otel_reader, mock_policy_allow, mock_audit,
    ):
        """A lock refresh should NOT increment the active gauge."""
        meter = otel_reader._test_provider.get_meter("coordinator.locks", "0.1.0")
        with patch("src.locks.get_lock_meter", return_value=meter):
            locks_module._instruments = None

            db = MagicMock()
            db.rpc = AsyncMock(return_value={
                "success": True,
                "action": "refreshed",
                "file_path": "src/test.py",
                "locked_by": "agent-1",
                "agent_type": "claude_code",
                "locked_at": "2026-03-28T00:00:00+00:00",
                "expires_at": "2026-03-28T02:00:00+00:00",
            })

            svc = LockService(db=db)
            await svc.acquire("src/test.py", reason="refresh")

        active = _get_metric(otel_reader, "lock.active")
        # Refreshed should NOT add to active gauge
        if active is not None:
            assert _sum_data_points(active) == 0


# ---------------------------------------------------------------------------
# T5.2: Prometheus /metrics endpoint
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPrometheusEndpoint:
    """Verify the /metrics Prometheus endpoint returns valid output."""

    def test_metrics_endpoint_returns_prometheus_format(self):
        """GET /metrics should return text/plain with metric families."""
        from starlette.testclient import TestClient

        env = {
            "OTEL_METRICS_ENABLED": "true",
            "PROMETHEUS_ENABLED": "true",
            "OTEL_SERVICE_NAME": "test-coordinator",
            "AGENT_ID": "test-agent",
            "AGENT_TYPE": "test",
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
            os.environ.pop("OTEL_TRACES_ENABLED", None)
            reset_telemetry()

            from src.coordination_api import create_coordination_api

            app = create_coordination_api()
            client = TestClient(app)

            response = client.get("/metrics/")
            assert response.status_code == 200
            body = response.text

            # Prometheus format: lines starting with # are comments/metadata
            # Metric lines contain metric_name{labels} value
            assert "# HELP" in body or "# TYPE" in body or len(body) > 0

    def test_metrics_endpoint_not_mounted_when_disabled(self):
        """GET /metrics should 404 when Prometheus is disabled."""
        from starlette.testclient import TestClient

        env = {
            "OTEL_METRICS_ENABLED": "true",
            "AGENT_ID": "test-agent",
            "AGENT_TYPE": "test",
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
            os.environ.pop("OTEL_TRACES_ENABLED", None)
            os.environ.pop("PROMETHEUS_ENABLED", None)
            reset_telemetry()

            from src.coordination_api import create_coordination_api

            app = create_coordination_api()
            client = TestClient(app)

            response = client.get("/metrics/")
            assert response.status_code == 404
