from app.core.observability import init_sentry, scrub_event


def test_sentry_disabled_without_dsn() -> None:
    assert init_sentry("", "local") is False


def test_scrub_removes_emails() -> None:
    event = {"message": "contact a.b@example.com", "extra": {"to": ["x@y.co"]}}
    out = scrub_event(event, None)
    assert "@" not in str(out)
