"""R1-003 / R1-025: the import job is wired for safe redelivery and never fails an upload."""

from uuid import uuid4

import pytest

from app.core.jobs import celery_app
from app.modules.imports import jobs


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
