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


class _FakeImporterClient:
    def __init__(self):
        self.stats = {
            "address_objects_created": 0,
            "address_objects_failed": 0,
            "address_objects_skipped": 0,
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


class _FakeBulkDelete(ftd_api_cleanup.FTDBulkDelete):
    def __init__(self):
        super().__init__(host="dummy", username="user", password="pass", debug=False)
        self._delete_attempts = {}

    def get_all_objects(self, endpoint: str):
        return [
            {"id": "1", "name": "obj-retry", "isSystemDefined": False},
            {"id": "2", "name": "obj-ok", "isSystemDefined": False},
            {"id": "sys-1", "name": "sys-obj", "isSystemDefined": True},
        ]

    def delete_object(self, endpoint: str, object_id: str):
        count = self._delete_attempts.get(object_id, 0)
        self._delete_attempts[object_id] = count + 1

        if object_id == "1" and count == 0:
            return False, "HTTP 429 Too Many Requests"
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
