"""A reset between staging and publication must leave no message or claim."""

import contextlib
import os
import threading

import pytest

from agenttalk import cli
from agenttalk.store import Store


@pytest.mark.parametrize("archive", [False, True])
@pytest.mark.parametrize("config_locked", [False, True])
@pytest.mark.parametrize("requeue", [False, True])
def test_staged_send_reset_refuses_without_order_or_claim(tmp_path, monkeypatch, archive, config_locked, requeue):
    store = Store(tmp_path)
    store.init(["alpha", "beta"])
    original = store.send(sender="alpha", recipient="beta", body="before reset")
    reached, resume = threading.Event(), threading.Event()
    seam = "_message_publication_lock" if config_locked else "_retirement_lock"
    real_lock = getattr(store, seam)
    outcome = {}

    @contextlib.contextmanager
    def gated_lock(*args, **kwargs):
        if threading.current_thread() is sender:
            reached.set()
            assert resume.wait(30), "reset did not release sender"
        with real_lock(*args, **kwargs):
            yield

    def send():
        try:
            outcome["sent"] = store.send(
                sender="alpha",
                recipient="beta",
                body="staged",
                _config_locked=config_locked,
                _requeue_source=("beta", original.id) if requeue else None,
            )
        except Exception as exc:
            outcome["error"] = exc

    monkeypatch.setattr(store, seam, gated_lock)
    sender = threading.Thread(target=send)
    sender.start()
    try:
        assert reached.wait(30), "sender did not stage its payload"
        assert len(list(store.messages_dir.glob(".*.pending"))) == 1
        store.reset(archive=archive)
        assert not list(store.messages_dir.glob(".*.pending"))
    finally:
        resume.set()
        sender.join(30)
    assert not sender.is_alive()
    # Check durable state before the error text, so a late refusal cannot pass.
    assert not store._requeue_state_path("beta", original.id).exists()
    assert not store._message_publication_order_path.exists()
    assert store.validated_messages_with_problems() == ([], [])
    assert "sent" not in outcome
    assert isinstance(outcome.get("error"), OSError)
    assert str(outcome["error"]) == (
        "the store was reset while this message was waiting to be published; nothing was published; send it again"
    )
    retry = store.send(sender="alpha", recipient="beta", body="retry")
    messages, problems = store.validated_messages_with_problems()
    assert [message.id for message in messages] == [retry.id]
    assert problems == []
    assert store._read_message_publication_order()["messages"] == {retry.id: 1}


def test_send_oserror_keeps_exit_code_two(tmp_path, monkeypatch, capsys):
    Store(tmp_path).init(["alpha", "beta"])

    def refuse(self, **kwargs):
        raise OSError("the store was reset; nothing was published; send it again")

    monkeypatch.setattr(Store, "send", refuse)
    assert cli.main(["--root", str(tmp_path), "send", "--from", "alpha", "--to", "beta", "-m", "hello"]) == 2
    assert "nothing was published; send it again" in capsys.readouterr().err


@pytest.mark.parametrize("change", ["replacement", "unreadable"])
def test_staged_payload_changed_refuses_before_publication(tmp_path, monkeypatch, change):
    store = Store(tmp_path)
    store.init(["alpha", "beta"])
    real_lock, real_lstat = store._retirement_lock, os.lstat
    staged = []

    @contextlib.contextmanager
    def change_payload():
        (pending,) = store.messages_dir.glob(".*.pending")
        staged.append(pending)
        if change == "replacement":
            pending.rename(pending.with_suffix(".held"))
            pending.write_text("replacement must survive cleanup", encoding="utf-8")
        else:

            def unreadable(path, *args, **kwargs):
                if path == pending:
                    raise PermissionError("staged file cannot be inspected")
                return real_lstat(path, *args, **kwargs)

            monkeypatch.setattr(os, "lstat", unreadable)
        with real_lock():
            yield

    monkeypatch.setattr(store, "_retirement_lock", change_payload)
    with pytest.raises(OSError, match="nothing was published; send it again"):
        store.send(sender="alpha", recipient="beta", body="staged")
    assert not store._message_publication_order_path.exists()
    assert not list(store.messages_dir.glob("*.json"))
    if change == "replacement":
        assert staged[0].read_text(encoding="utf-8") == "replacement must survive cleanup"
