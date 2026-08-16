import json
from pathlib import Path

import pytest

from src.evals_engine import build_eval_session
from src.models import ResultFormat


EXAMPLE_EVALS_DIR = Path(__file__).resolve().parents[2] / "example_evals"


@pytest.fixture(autouse=True)
def use_repository_example_evals(monkeypatch):
    monkeypatch.setattr("src.evals_engine.settings.EVALS_DIRS", str(EXAMPLE_EVALS_DIR))


def _valid_config() -> dict:
    return {
        "evals": [
            {
                "number": 1,
                "eval_dir": "basic_eval",
                "description": "a valid evaluation",
                "run_count": 1,
                "tags": ["example"],
            }
        ],
        "agents": [
            {
                "agent_type": "copilot_cli",
                "agent_model": "test-model",
            }
        ],
    }


def _write_config(tmp_path: Path, value: object, *, raw: bool = False) -> Path:
    path = tmp_path / "evals.json"
    contents = value if raw else json.dumps(value)
    path.write_text(contents, encoding="utf-8")
    return path


def test_build_eval_session_accepts_valid_config(tmp_path):
    # Arrange
    config_path = _write_config(tmp_path, _valid_config())

    # Act
    session = build_eval_session(config_path, ResultFormat.JSON)

    # Assert
    assert len(session.evals) == 1
    assert len(session.agents) == 1
    assert session.agents[0].eval_retries == 0


def test_build_eval_session_accepts_agent_eval_retries(tmp_path):
    # Arrange
    config = _valid_config()
    config["agents"][0]["eval_retries"] = 2
    config_path = _write_config(tmp_path, config)

    # Act
    session = build_eval_session(config_path, ResultFormat.JSON)

    # Assert
    assert session.agents[0].eval_retries == 2


@pytest.mark.parametrize("value", [-1, True, 1.5, "1"])
def test_build_eval_session_rejects_invalid_agent_eval_retries(tmp_path, value):
    # Arrange
    config = _valid_config()
    config["agents"][0]["eval_retries"] = value
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"agents\[0\].eval_retries.*non-negative integer"):
        build_eval_session(config_path, ResultFormat.JSON)


def test_build_eval_session_reports_invalid_json(tmp_path):
    # Arrange
    config_path = _write_config(tmp_path, "{", raw=True)

    # Act / Assert
    with pytest.raises(ValueError, match="Invalid evaluation configuration.*invalid JSON"):
        build_eval_session(config_path, ResultFormat.JSON)


def test_build_eval_session_reports_missing_top_level_field(tmp_path):
    # Arrange
    config = _valid_config()
    del config["agents"]
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match="missing required field 'agents'"):
        build_eval_session(config_path, ResultFormat.JSON)


def test_build_eval_session_rejects_unknown_agent_field(tmp_path):
    # Arrange
    config = _valid_config()
    config["agents"][0]["unexpected"] = True
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"agents\[0\].*unknown field.*unexpected"):
        build_eval_session(config_path, ResultFormat.JSON)


def test_build_eval_session_reports_invalid_agent_type(tmp_path):
    # Arrange
    config = _valid_config()
    config["agents"][0]["agent_type"] = "not_an_agent"
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"agents\[0\].agent_type"):
        build_eval_session(config_path, ResultFormat.JSON)


def test_build_eval_session_reports_invalid_run_count(tmp_path):
    # Arrange
    config = _valid_config()
    config["evals"][0]["run_count"] = 0
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"evals\[0\].run_count.*positive integer"):
        build_eval_session(config_path, ResultFormat.JSON)


def test_build_eval_session_reports_unknown_eval_directory(tmp_path):
    # Arrange
    config = _valid_config()
    config["evals"][0]["eval_dir"] = "does_not_exist"
    config_path = _write_config(tmp_path, config)

    # Act / Assert
    with pytest.raises(ValueError, match=r"evals\[0\].eval_dir.*not found"):
        build_eval_session(config_path, ResultFormat.JSON)
