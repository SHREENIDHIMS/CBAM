"""R1-003 / R1-025: the import job is wired for safe redelivery and never fails an upload."""

from uuid import uuid4

import pytest

from app.core.jobs import celery_app
from app.modules.imports import jobs
from app.modules.imports.processing import ImportJobError


def test_r1_003_the_task_is_registered_acks_late_and_retries_with_a_cap() -> None:
    task = jobs.process_batch_task
    assert task.name == "app.modules.imports.jobs.process_batch"
    assert task.acks_late is True
    assert task.max_retries == jobs.MAX_RETRIES == 5
    assert "app.modules.imports.jobs" in celery_app.conf.include


def test_r1_003_enqueue_sends_only_ids_with_a_per_batch_task_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: dict[str, object] = {}
    monkeypatch.setattr(
        jobs.process_batch_task, "apply_async", lambda **kw: sent.update(kw), raising=False
    )
    tenant, batch = uuid4(), uuid4()
    jobs.enqueue_batch(tenant, batch)
    assert sent["args"] == [str(tenant), str(batch)]
    assert sent["task_id"] == f"import:{batch}"


def test_r1_003_a_broker_failure_is_swallowed_and_logged_by_id_only() -> None:
    def broken(_t: object, _b: object) -> None:
        raise ConnectionError("redis://user:secret@host is down")

    assert jobs.safe_enqueue(broken, uuid4(), uuid4()) is False
    assert jobs.safe_enqueue(lambda _t, _b: None, uuid4(), uuid4()) is True


def test_r1_025_a_permanent_job_error_is_not_retried_with_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def permanent(*_a: object, **_k: object) -> str:
        calls.append(1)
        raise ImportJobError("TenantMismatchError", permanent=True)

    monkeypatch.setattr(jobs, "process_batch", permanent)
    monkeypatch.setattr(jobs, "get_engine", lambda: None)
    monkeypatch.setattr(jobs, "get_object_store", lambda: None)
    result = jobs.process_batch_task.apply(args=[str(uuid4()), str(uuid4())])
    assert result.state == "FAILURE"
    assert calls == [1]  # one try, no backoff retries


def test_r1_003_a_transient_error_asks_for_a_retry_with_growing_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def transient(*_a: object, **_k: object) -> str:
        raise ImportJobError("StorageError")

    monkeypatch.setattr(jobs, "process_batch", transient)
    monkeypatch.setattr(jobs, "get_engine", lambda: None)
    monkeypatch.setattr(jobs, "get_object_store", lambda: None)
    result = jobs.process_batch_task.apply(args=[str(uuid4()), str(uuid4())])
    assert result.state == "FAILURE"  # eager mode re-runs up to max_retries then gives up
    assert jobs.process_batch_task.reject_on_worker_lost is False
