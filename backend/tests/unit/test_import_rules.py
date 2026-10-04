"""R1-003: pure import rules (batch status order, file sniffing, fingerprint)."""

from datetime import date

import pytest

from app.modules.imports import rules


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("received", "queued"),
        ("queued", "parsing"),
        ("parsing", "validating"),
        ("validating", "normalising"),
        ("normalising", "completed"),
        ("received", "parsing"),  # skipping ahead is still forward
        ("parsing", "completed_with_errors"),
        ("received", "rejected"),
        ("validating", "failed"),
    ],
)
def test_r1_003_forward_moves_are_allowed(current: str, target: str) -> None:
    assert rules.batch_transition(current, target).outcome == "ALLOWED"


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("parsing", "queued"),
        ("queued", "received"),
        ("parsing", "parsing"),
        ("normalising", "received"),
        ("completed", "failed"),  # terminal states are locked, even to another terminal state
        ("completed", "received"),
        ("failed", "queued"),
        ("rejected", "completed"),
        ("completed_with_errors", "completed"),
        ("received", "nonsense"),
        ("nonsense", "queued"),
    ],
)
def test_r1_003_backward_same_terminal_and_unknown_moves_are_blocked(
    current: str, target: str
) -> None:
    decision = rules.batch_transition(current, target)
    assert decision.outcome == "BLOCKED"
    assert decision.rule_id == rules.RULE_TRANSITION


def test_r1_003_every_terminal_state_is_locked() -> None:
    for terminal in rules.TERMINAL_STATES:
        for target in rules.STATUSES:
            assert rules.batch_transition(terminal, target).outcome == "BLOCKED"


def test_r1_003_utf8_checker_accepts_text_with_bom_and_split_multibyte_characters() -> None:
    body = "\ufeffmrn,desc\nA1,Café - steel\n".encode()
    checker = rules.Utf8Checker()
    for i in range(0, len(body), 3):  # chunks that cut multi-byte characters in half
        assert checker.feed(body[i : i + 3])
    assert checker.finish()
    assert checker.first_line_has_delimiter()


def test_r1_003_utf8_checker_refuses_nul_bytes_and_invalid_utf8() -> None:
    nul = rules.Utf8Checker()
    assert nul.feed(b"a,b\n1,2\x00\n") is False
    assert nul.finish() is False
    bad = rules.Utf8Checker()
    assert bad.feed(b"a,b\n\xff\xfe\n") is False
    assert bad.finish() is False


def test_r1_003_utf8_checker_refuses_a_cut_off_character_at_the_end_and_empty_input() -> None:
    cut = rules.Utf8Checker()
    assert cut.feed("a,b\né".encode()[:-1])
    assert cut.finish() is False
    assert rules.Utf8Checker().finish() is False


def test_r1_003_header_row_needs_a_delimiter() -> None:
    assert not rules.looks_delimited(b"")
    assert not rules.looks_delimited(b"just one word of text\nsecond line,with,commas\n")
    assert rules.looks_delimited(b"mrn;commodity\n1;2\n")
    assert rules.looks_delimited(b"\xef\xbb\xbfmrn\tcommodity\n")
    for binary in (b"PK\x03\x04\x14\x00\x00\x00", b"%PDF-1.7\n\x00\x01"):
        checker = rules.Utf8Checker()
        assert checker.feed(binary) is False


@pytest.mark.parametrize("code", ["unreadable_header", "x", "a1_b2", "a" * 64])
def test_r1_003_failure_reason_accepts_short_codes(code: str) -> None:
    assert rules.is_failure_code(code)


@pytest.mark.parametrize(
    "text", ["", "Bad cell 'John Smith'", "Has Capital", "a" * 65, "line\nbreak", "dash-ed", "a b"]
)
def test_r1_003_failure_reason_refuses_free_text(text: str) -> None:
    assert not rules.is_failure_code(text)


def test_r1_003_safe_filename_drops_paths_and_control_characters() -> None:
    assert rules.safe_filename("C:\\Users\\x\\report.csv") == "report.csv"
    assert rules.safe_filename("../../etc/passwd") == "passwd"
    assert rules.safe_filename("a\x00b\nc.csv") == "abc.csv"
    assert rules.safe_filename(None) == "upload.csv"
    assert rules.safe_filename("") == "upload.csv"
    assert len(rules.safe_filename("x" * 400)) == 255


def test_r1_003_fingerprint_ignores_order_and_changes_with_any_declared_value() -> None:
    a = {"acquisition_method": "cds_export", "eori": None, "window_start": "2027-01-01"}
    b = {"window_start": "2027-01-01", "eori": None, "acquisition_method": "cds_export"}
    assert rules.request_fingerprint(a) == rules.request_fingerprint(b)
    assert len(rules.request_fingerprint(a)) == 32
    assert rules.request_fingerprint(a) != rules.request_fingerprint(
        {**a, "eori": "GB123456789012"}
    )


def test_r1_003_acquired_on_cannot_be_in_the_future() -> None:
    today = date(2027, 3, 1)
    assert rules.acquired_on_is_valid(None, today)
    assert rules.acquired_on_is_valid(today, today)
    assert not rules.acquired_on_is_valid(date(2027, 3, 2), today)
