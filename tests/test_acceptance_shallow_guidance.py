"""Shallow-history guidance at the public acceptance boundary."""

import subprocess

import pytest
import test_acceptance as fixtures
from agenttalk import acceptance, acceptance_obligations

case = fixtures.case
case_v2 = fixtures.case_v2
git = fixtures.git
open_attempt = fixtures.open_attempt


def test_full_history_plan_reports_shallow_project_mismatch(case_v2, tmp_path, capsys):
    project = case_v2["project"]
    git(project, "commit", "--allow-empty", "-m", "add fixture history")
    case_v2["sha"] = git(project, "rev-parse", "HEAD")
    shallow = tmp_path / "shallow project"
    subprocess.run(
        ["git", "clone", "--quiet", "--depth=1", project.as_uri(), str(shallow)],
        check=True,
        capture_output=True,
    )
    case_v2["project"] = shallow
    capsys.readouterr()
    assert open_attempt(case_v2) != 0
    error = capsys.readouterr().err
    assert "acceptance_project_unverified" in error
    assert error.count("shallow clone") == 1


@pytest.mark.parametrize("boundary", ["freeze", "attach", "resolve", "resolve_id", "inherited"])
def test_shallow_mismatch_at_later_boundaries(case_v2, tmp_path, capsys, monkeypatch, boundary):
    project = case_v2["project"]
    git(project, "commit", "--allow-empty", "-m", "add fixture history")
    case_v2["sha"] = git(project, "rev-parse", "HEAD")
    full = acceptance.verify_project(project, case_v2["sha"])
    shallow = tmp_path / "shallow project"
    subprocess.run(
        ["git", "clone", "--quiet", "--depth=1", project.as_uri(), str(shallow)],
        check=True,
        capture_output=True,
    )
    case_v2["project"] = shallow
    shallow_project = acceptance.verify_project(shallow, case_v2["sha"])
    assert full["roots"] != shallow_project["roots"]
    case_v2["plan"]["project_id"] = acceptance.project_id(shallow_project)
    fixtures.write_json(case_v2["inputs"] / "plan.json", case_v2["plan"])

    original = acceptance.verify_project
    calls = 0

    def changed(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if boundary != "freeze" or calls > 1:
            return dict(result, roots=full["roots"])
        return result

    if boundary == "inherited":
        prior = {"revision": case_v2["sha"], "required_lenses": []}
        old_route = {"attempt_id": "previous", "project": full, "project_id": acceptance.project_id(full)}
        monkeypatch.setattr(
            acceptance_obligations, "sources", lambda *args: [(None, prior, old_route, {"partitions": []})]
        )
        monkeypatch.setattr(acceptance_obligations, "_review_obligations", lambda *args: [])
        record = {"acceptance_route": {"project": shallow_project}}
        with pytest.raises(acceptance.AcceptanceError) as error:
            acceptance_obligations.inherit(case_v2["store"], record, {}, snapshot={"holds": []})
        assert error.value.code == "acceptance_project_unverified"
        output = str(error.value)
        assert "inherited source project identity changed" in output
    elif boundary == "freeze":
        monkeypatch.setattr(acceptance, "verify_project", changed)
        capsys.readouterr()
        assert open_attempt(case_v2) != 0
        output = capsys.readouterr().err
        assert "project changed before freeze" in output
    else:
        assert open_attempt(case_v2) == 0
        if boundary == "attach":
            fixtures.bundle_v2(case_v2)
            monkeypatch.setattr(acceptance, "verify_project", changed)
            capsys.readouterr()
            assert fixtures.attach(case_v2) != 0
            output = capsys.readouterr().err
            assert "project changed before attachment" in output
        else:
            if boundary == "resolve":
                monkeypatch.setattr(acceptance, "verify_project", changed)
            else:
                monkeypatch.setattr(acceptance, "project_id", lambda project: "different")
            capsys.readouterr()
            assert fixtures.command(case_v2, "check", "--id", "attempt", "--json") == 3
            output = capsys.readouterr().out
            expected = "project identity changed" if boundary == "resolve" else "project ID differs"
            assert expected in output
    if boundary != "inherited":
        assert "acceptance_project_unverified" in output
    assert output.count("shallow clone") == 1
