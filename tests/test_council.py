import json
import uuid

import agents.council as council


def make_proposal(repo="NATEX", action="foo", autonomy="L1", risk="MEDIUM"):
    return {"repo": repo, "action": action, "autonomy": autonomy, "risk": risk, "id": str(uuid.uuid4())}


def test_evaluate_unknown_repo(monkeypatch):
    p = make_proposal(repo="NONEXISTENT")
    d = council.evaluate(p)
    assert not d["approved"]
    assert "Unknown repo" in d["reason"]


def test_evaluate_invalid_autonomy():
    p = make_proposal(autonomy="BAD")
    d = council.evaluate(p)
    assert not d["approved"]
    assert "Invalid autonomy level" in d["reason"]


def test_evaluate_high_risk_requires_human(monkeypatch):
    # create dummy repo entry
    monkeypatch.setattr(council, "PORTFOLIO", {"repositories": [{"name": "X"}]})
    p = make_proposal(repo="X", risk="HIGH")
    d = council.evaluate(p)
    assert not d["approved"]
    assert d["requires_human"]


def test_evaluate_l3_requires_human(monkeypatch):
    monkeypatch.setattr(council, "PORTFOLIO", {"repositories": [{"name": "X"}]})
    p = make_proposal(repo="X", autonomy="L3")
    d = council.evaluate(p)
    assert not d["approved"]
    assert d["requires_human"]


def test_evaluate_consent(monkeypatch, tmp_path):
    # simulate sensitive action
    monkeypatch.setattr(council, "PORTFOLIO", {"repositories": [{"name": "X"}]})
    council.CONFIG["repos_base"] = str(tmp_path)
    # create repo dir and no consent files
    (tmp_path / "X").mkdir()
    p = make_proposal(repo="X", action="external_api_calls")
    d = council.evaluate(p)
    assert not d["approved"]
    assert d["requires_human"]
    assert "consent" in d["reason"][0].lower()


def test_evaluate_ok(monkeypatch):
    monkeypatch.setattr(council, "PORTFOLIO", {"repositories": [{"name": "X"}]})
    p = make_proposal(repo="X", action="foo", autonomy="L1", risk="MEDIUM")
    d = council.evaluate(p)
    assert d["approved"]
    assert not d["requires_human"]
