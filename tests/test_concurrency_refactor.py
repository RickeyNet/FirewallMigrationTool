import sys
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "FortiGateToFTDTool"))

import concurrency_utils
import ftd_api_cleanup
import ftd_api_importer


def test_run_with_retry_retries_transient_then_succeeds(monkeypatch):
    monkeypatch.setattr(concurrency_utils.time, "sleep", lambda _s: None)
    monkeypatch.setattr(concurrency_utils.random, "uniform", lambda _a, _b: 0.0)

    attempts = {"count": 0}

    def flaky_operation():
        attempts["count"] += 1
        if attempts["count"] == 1:
            return False, "HTTP 429 rate limit"
        return True, "ok"

    success, result = concurrency_utils.run_with_retry(flaky_operation, max_attempts=3)

    assert success is True
    assert result == "ok"
    assert attempts["count"] == 2


def test_run_with_retry_stops_after_max_attempts(monkeypatch):
    monkeypatch.setattr(concurrency_utils.time, "sleep", lambda _s: None)
    monkeypatch.setattr(concurrency_utils.random, "uniform", lambda _a, _b: 0.0)

    attempts = {"count": 0}

    def always_fails():
        attempts["count"] += 1
        return False, "HTTP 503 Service Unavailable"

    success, result = concurrency_utils.run_with_retry(always_fails, max_attempts=3)

    assert success is False
    assert result == "HTTP 503 Service Unavailable"
    assert attempts["count"] == 3


class _FakeImporterClient:
    def __init__(self):
        self.stats = {
            "address_objects_created": 0,
            "address_objects_failed": 0,
            "address_objects_skipped": 0,
            "port_objects_created": 0,
            "port_objects_failed": 0,
            "port_objects_skipped": 0,
        }
        self._attempts = {}

    def record_stat(self, key: str) -> None:
        self.stats[key] += 1

    def create_network_object(self, obj, track_stats=False):
        name = obj.get("name", "")
        count = self._attempts.get(name, 0)
        self._attempts[name] = count + 1

        if name == "retry-me" and count == 0:
            return False, "HTTP 429 Too Many Requests"
        return True, f"id-{name}"

    def create_port_object(self, obj, track_stats=False):
        name = obj.get("name", "")
        count = self._attempts.get(name, 0)
        self._attempts[name] = count + 1

        if name == "svc-retry-503" and count == 0:
            return False, "HTTP 503 Service Unavailable"
        if name == "svc-hard-fail":
            return False, "HTTP 400 Bad Request"
        return True, f"id-{name}"


def test_import_address_objects_retries_and_updates_stats(monkeypatch):
    monkeypatch.setattr(concurrency_utils.time, "sleep", lambda _s: None)
    monkeypatch.setattr(concurrency_utils.random, "uniform", lambda _a, _b: 0.0)
    monkeypatch.setattr(
        ftd_api_importer,
        "load_json_file",
        lambda _filename: [{"name": "retry-me"}, {"name": "ok-me"}],
    )

    client = _FakeImporterClient()

    success = ftd_api_importer.import_address_objects(
        cast(ftd_api_importer.FTDAPIClient, client),
        "dummy.json",
        max_workers=2,
        max_attempts=3,
    )

    assert success is True
    assert client.stats["address_objects_created"] == 2
    assert client.stats["address_objects_failed"] == 0
    assert client._attempts["retry-me"] == 2


def test_import_service_objects_retries_on_503(monkeypatch):
    monkeypatch.setattr(concurrency_utils.time, "sleep", lambda _s: None)
    monkeypatch.setattr(concurrency_utils.random, "uniform", lambda _a, _b: 0.0)
    monkeypatch.setattr(
        ftd_api_importer,
        "load_json_file",
        lambda _filename: [{"name": "svc-retry-503", "type": "tcpportobject"}, {"name": "svc-ok", "type": "udpportobject"}],
    )

    client = _FakeImporterClient()

    success = ftd_api_importer.import_service_objects(
        cast(ftd_api_importer.FTDAPIClient, client),
        "dummy.json",
        max_workers=2,
        max_attempts=3,
    )

    assert success is True
    assert client.stats["port_objects_created"] == 2
    assert client.stats["port_objects_failed"] == 0
    assert client._attempts["svc-retry-503"] == 2


def test_import_service_objects_hard_failure_exhausts_attempts(monkeypatch):
    monkeypatch.setattr(concurrency_utils.time, "sleep", lambda _s: None)
    monkeypatch.setattr(concurrency_utils.random, "uniform", lambda _a, _b: 0.0)
    monkeypatch.setattr(
        ftd_api_importer,
        "load_json_file",
        lambda _filename: [{"name": "svc-hard-fail", "type": "tcpportobject"}],
    )

    client = _FakeImporterClient()

    success = ftd_api_importer.import_service_objects(
        cast(ftd_api_importer.FTDAPIClient, client),
        "dummy.json",
        max_workers=1,
        max_attempts=3,
    )

    assert success is False
    assert client.stats["port_objects_created"] == 0
    assert client.stats["port_objects_failed"] == 1
    # Non-retryable 400 should fail on first attempt.
    assert client._attempts["svc-hard-fail"] == 1


def test_importer_compute_outcome_success():
    """All items created/skipped, none failed → exit 0."""
    client = _FakeImporterClient()
    client.stats["address_objects_created"] = 5
    client.stats["address_objects_skipped"] = 2
    client.stats["address_objects_failed"] = 0
    client.stats["port_objects_created"] = 3
    # Graft compute_outcome from the real class
    client.compute_outcome = ftd_api_importer.FTDAPIClient.compute_outcome.__get__(client)

    code, label = client.compute_outcome()
    assert code == 0
    assert label == "SUCCESS"


def test_importer_compute_outcome_partial_failure():
    """Some items succeeded, some failed → exit 2."""
    client = _FakeImporterClient()
    client.stats["address_objects_created"] = 3
    client.stats["address_objects_failed"] = 2
    client.compute_outcome = ftd_api_importer.FTDAPIClient.compute_outcome.__get__(client)

    code, label = client.compute_outcome()
    assert code == 2
    assert label == "PARTIAL_FAILURE"


def test_importer_compute_outcome_all_failed():
    """Every item failed, nothing succeeded → exit 3."""
    client = _FakeImporterClient()
    client.stats["address_objects_failed"] = 5
    client.compute_outcome = ftd_api_importer.FTDAPIClient.compute_outcome.__get__(client)

    code, label = client.compute_outcome()
    assert code == 3
    assert label == "ALL_FAILED"


class _FakeBulkDelete(ftd_api_cleanup.FTDBulkDelete):
    def __init__(self):
        super().__init__(host="dummy", username="user", password="pass", debug=False)
        self._delete_attempts = {}

    def get_all_objects(self, endpoint: str):
        if "staticrouteentries" in endpoint:
            return [
                {"id": "r1", "name": "route-retry-503"},
                {"id": "r2", "name": "route-ok"},
            ]
        return [
            {"id": "1", "name": "obj-retry", "isSystemDefined": False},
            {"id": "2", "name": "obj-ok", "isSystemDefined": False},
            {"id": "sys-1", "name": "sys-obj", "isSystemDefined": True},
        ]

    def get_default_virtual_router_id(self):
        return True, "vr-1"

    def delete_object(self, endpoint: str, object_id: str):
        count = self._delete_attempts.get(object_id, 0)
        self._delete_attempts[object_id] = count + 1

        if object_id == "1" and count == 0:
            return False, "HTTP 429 Too Many Requests"
        if object_id == "r1" and count == 0:
            return False, "HTTP 503 Service Unavailable"
        return True, ""


def test_cleanup_custom_objects_retries_and_updates_stats(monkeypatch):
    monkeypatch.setattr(concurrency_utils.time, "sleep", lambda _s: None)
    monkeypatch.setattr(concurrency_utils.random, "uniform", lambda _a, _b: 0.0)

    client = _FakeBulkDelete()

    success = client.delete_all_custom_objects(
        endpoint="/object/networks",
        object_type="Address Objects",
        dry_run=False,
        max_workers=2,
        max_attempts=3,
    )

    assert success is True
    assert client.stats["total_found"] == 3
    assert client.stats["custom_objects"] == 2
    assert client.stats["system_objects"] == 1
    assert client.stats["deleted"] == 2
    assert client.stats["failed"] == 0
    assert client._delete_attempts["1"] == 2


def test_cleanup_static_routes_retries_on_503(monkeypatch):
    monkeypatch.setattr(concurrency_utils.time, "sleep", lambda _s: None)
    monkeypatch.setattr(concurrency_utils.random, "uniform", lambda _a, _b: 0.0)

    client = _FakeBulkDelete()

    success = client.delete_all_static_routes(
        dry_run=False,
        max_workers=2,
        max_attempts=3,
    )

    assert success is True
    assert client._delete_attempts["r1"] == 2
    assert client._delete_attempts["r2"] == 1


def test_cleanup_compute_outcome_success(monkeypatch):
    """All deletions succeeded → exit 0."""
    monkeypatch.setattr(concurrency_utils.time, "sleep", lambda _s: None)
    monkeypatch.setattr(concurrency_utils.random, "uniform", lambda _a, _b: 0.0)

    client = _FakeBulkDelete()
    client.delete_all_custom_objects("/object/networks", "Address Objects", False, 2, 3)

    code, label = client.compute_outcome()
    assert code == 0
    assert label == "SUCCESS"


def test_cleanup_compute_outcome_partial_failure():
    """Some items deleted, some failed → exit 2."""
    client = _FakeBulkDelete()
    client.stats["deleted"] = 3
    client.stats["failed"] = 2

    code, label = client.compute_outcome()
    assert code == 2
    assert label == "PARTIAL_FAILURE"


def test_cleanup_compute_outcome_all_failed():
    """No items deleted, all failed → exit 3."""
    client = _FakeBulkDelete()
    client.stats["deleted"] = 0
    client.stats["failed"] = 5

    code, label = client.compute_outcome()
    assert code == 3
    assert label == "ALL_FAILED"


# --- validate_endpoints tests ---

class _FakeResponse:
    def __init__(self, status_code, json_data=None):
        self.status_code = status_code
        self._json = json_data or {}

    def json(self):
        return self._json


class _FakeSession:
    """Minimal mock that records GET calls and returns canned responses."""
    def __init__(self, responses=None):
        self.calls = []
        self._responses = responses or {}

    def get(self, url, params=None, timeout=None):
        self.calls.append(url)
        # Return specific response if URL matches, else 200 OK
        for pattern, resp in self._responses.items():
            if pattern in url:
                return resp
        return _FakeResponse(200, {"paging": {"count": 5}})


def test_importer_validate_endpoints_all_ok():
    """All endpoints return 200 → validate_endpoints returns True."""
    client = ftd_api_importer.FTDAPIClient.__new__(ftd_api_importer.FTDAPIClient)
    client.base_url = "https://fake/api/fdm/latest"
    client.session = _FakeSession()

    assert client.validate_endpoints() is True
    # Should have probed 11 endpoints
    assert len(client.session.calls) == 11


def test_importer_validate_endpoints_partial_fail():
    """One endpoint returns 403 → validate_endpoints returns False."""
    client = ftd_api_importer.FTDAPIClient.__new__(ftd_api_importer.FTDAPIClient)
    client.base_url = "https://fake/api/fdm/latest"
    client.session = _FakeSession(responses={
        "/object/networks": _FakeResponse(403),
    })

    assert client.validate_endpoints() is False


def test_cleanup_validate_endpoints_all_ok():
    """All endpoints return 200 → validate_endpoints returns True."""
    client = ftd_api_cleanup.FTDBulkDelete.__new__(ftd_api_cleanup.FTDBulkDelete)
    client.base_url = "https://fake/api/fdm/latest"
    client.session = _FakeSession()

    assert client.validate_endpoints() is True
    assert len(client.session.calls) == 11


def test_cleanup_validate_endpoints_partial_fail():
    """One endpoint returns 500 → validate_endpoints returns False."""
    client = ftd_api_cleanup.FTDBulkDelete.__new__(ftd_api_cleanup.FTDBulkDelete)
    client.base_url = "https://fake/api/fdm/latest"
    client.session = _FakeSession(responses={
        "/object/tcpports": _FakeResponse(500),
    })

    assert client.validate_endpoints() is False


# --- concurrency helper edge-case tests ---

def test_run_with_retry_max_attempts_one(monkeypatch):
    """max_attempts=1 means no retry — one call, immediate result."""
    monkeypatch.setattr(concurrency_utils.time, "sleep", lambda _s: None)
    monkeypatch.setattr(concurrency_utils.random, "uniform", lambda _a, _b: 0.0)

    attempts = {"count": 0}

    def always_fails():
        attempts["count"] += 1
        return False, "HTTP 503 Service Unavailable"

    success, result = concurrency_utils.run_with_retry(always_fails, max_attempts=1)

    assert success is False
    assert attempts["count"] == 1


def test_run_with_retry_non_retryable_fails_immediately(monkeypatch):
    """Non-retryable error should fail on first attempt, not retry."""
    monkeypatch.setattr(concurrency_utils.time, "sleep", lambda _s: None)
    monkeypatch.setattr(concurrency_utils.random, "uniform", lambda _a, _b: 0.0)

    attempts = {"count": 0}

    def non_retryable():
        attempts["count"] += 1
        return False, "HTTP 400 Bad Request - invalid payload"

    success, result = concurrency_utils.run_with_retry(non_retryable, max_attempts=4)

    assert success is False
    assert result == "HTTP 400 Bad Request - invalid payload"
    assert attempts["count"] == 1


def test_run_indexed_thread_pool_empty_list():
    """Empty item list should complete without error."""
    calls = []

    def worker(idx: int, item: str) -> None:
        calls.append(item)

    concurrency_utils.run_indexed_thread_pool(max_workers=4, items=[], worker=worker)

    assert calls == []
