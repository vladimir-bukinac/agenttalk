"""Body-source selection through the public CLI, using isolated stores."""

import io
import pytest

from agenttalk import cli
from agenttalk.store import Store


@pytest.fixture
def body_store(store: Store) -> Store:
    store.set_role("alpha", "lead")
    store.set_operator_facing("alpha")
    store.send(sender="beta", recipient="alpha", kind="question", body="decision?",
               meta={"request_id": "incoming", "needs_operator": True})
    store.send(sender="alpha", recipient="beta", kind="question", body="review?",
               meta={"request_id": "outgoing"})
    return store


BODY_COMMANDS = [
    ["send", "--to", "beta"],
    ["progress"],
    ["rescind", "--to-request", "outgoing"],
    ["escalate", "--to", "beta"],
    ["relay", "operator-answer", "--to-request", "incoming"],
    ["relay", "operator-command", "--to", "beta"],
    ["relay", "result", "--to", "beta", "--result-id", "result"],
    ["relay", "result", "--to", "beta", "--result-id", "result", "--none-needed"],
    ["relay", "result", "--to", "beta", "--request-id", "gone", "--unresolved"],
    ["propose", "--to", "beta"],
    ["task", "--to", "beta"],
    ["broadcast", "--all"],
    ["reply", "--to-request", "incoming"],
    ["reply", "--to-request", "incoming", "--na"],
    ["release", "--to", "beta", "--relay-human"],
    ["request-launch", "--profile", "review", "--skill", "review-code", "--revision", "HEAD"],
]


@pytest.mark.parametrize("command", BODY_COMMANDS, ids=lambda argv: " ".join(argv))
@pytest.mark.parametrize("message", ["note", ""])
@pytest.mark.parametrize("file_source", ["file", "missing", "-"])
def test_message_and_file_refused_without_sending(
    command, message, file_source, body_store, tmp_path, monkeypatch, capsys,
):
    body_file = tmp_path / "brief.txt"
    body_file.write_text("the complete brief", encoding="utf-8")
    source = {"file": str(body_file), "missing": str(tmp_path / "absent.txt"), "-": "-"}[file_source]
    # The revision lookup is unrelated to body selection; no Git process is needed.
    if command[0] == "request-launch":
        monkeypatch.setattr(cli, "_resolve_revision", lambda *_args: ("a" * 40, "commit"))
    monkeypatch.setattr("sys.stdin", None)  # even --file - must be rejected before reading
    argv = [*command, "--from", "alpha", "-m", message, "--file", source]
    if command[0] == "progress":
        argv.extend(["--to-id", body_store.messages_for("alpha")[0].id])
    before = list(body_store.valid_messages())

    rc = cli.main(["--root", str(body_store.root), *argv])

    assert rc == 2
    assert "use either -m or --file, not both" in capsys.readouterr().err
    assert list(body_store.valid_messages()) == before


@pytest.mark.parametrize("source", ["message", "empty", "file", "stdin-file", "stdin"])
def test_single_body_source_preserved(source, store, tmp_path, monkeypatch):
    body_file = tmp_path / "brief.txt"
    body_file.write_text("complete brief", encoding="utf-8")
    argv = {
        "message": ["-m", "complete brief"],
        "empty": ["-m", "", "--allow-empty"],
        "file": ["--file", str(body_file)],
        "stdin-file": ["--file", "-"],
        "stdin": [],
    }[source]
    monkeypatch.setattr("sys.stdin", io.StringIO("complete brief") if "stdin" in source else None)

    rc = cli.main(["--root", str(store.root), "send", "--from", "alpha", "--to", "beta", *argv])

    assert rc == 0
    assert store.messages_for("beta")[-1].body == ("" if source == "empty" else "complete brief")


def test_release_reason_alias_and_file_refused(body_store, tmp_path, capsys):
    body_file = tmp_path / "brief.txt"
    body_file.write_text("full reason", encoding="utf-8")
    before = list(body_store.valid_messages())

    rc = cli.main(["--root", str(body_store.root), "release", "--from", "alpha", "--to", "beta",
                   "--relay-human", "--reason", "note", "--file", str(body_file)])

    assert rc == 2
    assert "use either -m or --file, not both" in capsys.readouterr().err
    assert list(body_store.valid_messages()) == before
