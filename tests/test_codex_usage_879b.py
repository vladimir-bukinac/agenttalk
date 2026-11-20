import pytest

from agenttalk.cli import _usage_limit_notice_body
from agenttalk.supervisor import _usage_limit_park_row, supervisor_agent_assessment


@pytest.mark.parametrize("window", [None, "five_hour"])
def test_supervisor_preserves_codex_provider_and_recheck_wake(window):
    view = {
        "present": True,
        "state": "parked",
        "provider": "codex",
        "window": window,
        "reset_epoch": None,
        "wake_epoch": 1788948000,
    }
    row = _usage_limit_park_row(view)
    assert row["provider"] == "codex"
    assert row["wake_epoch"] == 1788948000
    assert row["reset_epoch"] is None
    assessment = supervisor_agent_assessment("beta", {"usage_limit_park": view}, None)
    assert assessment["usage_limit_park"]["provider"] == "codex"
    assert assessment["usage_limit_park"]["wake_epoch"] == 1788948000


def test_supervisor_does_not_pass_unknown_provider_or_extra_data():
    row = _usage_limit_park_row({"present": True, "provider": "unexpected", "secret": "not-a-field"})
    assert row.get("provider") is None
    assert "secret" not in row


@pytest.mark.parametrize("window", [None, "five_hour"])
def test_codex_recheck_notice_does_not_claim_confirmed_limit_is_only_possible(window):
    text = _usage_limit_notice_body(
        {"agent": "beta", "msg_id": "m1", "usage_limit": {"provider": "codex", "recheck": True, "window": window}}
    )
    assert "Codex" in text and "30 minutes" in text
    assert "possible Codex usage limit" not in text


def test_claude_notice_is_unchanged():
    text = _usage_limit_notice_body({"agent": "beta", "msg_id": "m1", "usage_limit": {}})
    assert "Claude" in text and "started" in text
