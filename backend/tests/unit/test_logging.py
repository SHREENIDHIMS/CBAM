"""R1-043 / docs section 9: structured logs carry IDs and never personal data."""

import json

import structlog

from app.core.logging import bind_context, clear_context, configure_logging


def test_log_line_is_json_with_ids_and_no_personal_data(capsys) -> None:  # type: ignore[no-untyped-def]
    configure_logging("INFO")
    clear_context()
    bind_context(request_id="req-1", tenant_id="t-1", user_id="u-1")
    structlog.get_logger().info(
        "supplier.contacted", supplier_id="s-9", email="a.b@example.com", phone="0123", name="Jo"
    )
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["event"] == "supplier.contacted"
    assert (line["request_id"], line["tenant_id"], line["user_id"]) == ("req-1", "t-1", "u-1")
    assert line["supplier_id"] == "s-9"
    assert line["email"] == line["phone"] == line["name"] == "[redacted]"
    assert "level" in line
    assert "timestamp" in line


def test_pii_inside_message_text_is_masked(capsys) -> None:  # type: ignore[no-untyped-def]
    configure_logging("INFO")
    clear_context()
    structlog.get_logger().info("sent to someone@example.com")
    out = capsys.readouterr().out
    assert "someone@example.com" not in out


def test_ids_bound_in_a_copied_context_reach_the_request_scope() -> None:
    """FastAPI runs sync dependencies in a thread pool with a *copy* of the context."""
    import contextvars
    import threading

    from app.core.logging import current_context, start_request_scope

    clear_context()
    start_request_scope()
    bind_context(request_id="r-1")
    copied = contextvars.copy_context()
    worker = threading.Thread(target=lambda: copied.run(bind_context, tenant_id="t-9"))
    worker.start()
    worker.join()
    assert current_context() == {"request_id": "r-1", "tenant_id": "t-9"}
    clear_context()
