import json

from tools import canary as cli


def test_should_skip_true_when_version_unchanged(tmp_path):
    p = tmp_path / "status.json"
    p.write_text(json.dumps({"copilot_version": "1.2.3"}))
    assert cli.should_skip("1.2.3", str(p)) is True


def test_should_skip_false_when_version_changed(tmp_path):
    p = tmp_path / "status.json"
    p.write_text(json.dumps({"copilot_version": "1.2.3"}))
    assert cli.should_skip("1.3.0", str(p)) is False


def test_should_skip_false_when_no_status_file(tmp_path):
    assert cli.should_skip("1.2.3", str(tmp_path / "missing.json")) is False
