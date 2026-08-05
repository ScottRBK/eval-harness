import json
import sys
from pathlib import Path

import pytest

import main as app
from src.models import AgentEvalStatus, ResultFormat


@pytest.fixture
def eval_config(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(
        "src.evals_engine.settings.EVALS_DIRS",
        str(Path(__file__).resolve().parents[2] / "example_evals"),
    )
    config = tmp_path / "evals.json"
    config.write_text(
        json.dumps(
            {
                "evals": [
                    {
                        "number": 1,
                        "eval_dir": "basic_eval",
                        "description": "test evaluation",
                        "run_count": 1,
                        "tags": [],
                    }
                ],
                "agents": [
                    {
                        "agent_type": "copilot_cli",
                        "agent_model": "test-model",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return config


def _fake_run_evals(monkeypatch, status: AgentEvalStatus, failed: bool):
    calls = {}

    def run_evals(*, eval_session, agent_eval_executions, eval_file, on_update):
        calls.update(
            {
                "eval_session": eval_session,
                "agent_eval_executions": agent_eval_executions,
                "eval_file": eval_file,
                "on_update": on_update,
            }
        )
        for agent_eval_execution in agent_eval_executions:
            agent_eval_execution.status = status
        return agent_eval_executions if failed else []

    monkeypatch.setattr(app, "run_evals", run_evals)
    return calls


def test_run_eval_completes_and_exports_results(
    monkeypatch, capsys, eval_config: Path, tmp_path: Path
):
    # Arrange
    output_dir = tmp_path / "output"
    monkeypatch.setattr("src.evals_engine.settings.OUTPUT_DIR", str(output_dir))
    calls = _fake_run_evals(monkeypatch, AgentEvalStatus.COMPLETED, failed=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--run_eval", "--eval_file", str(eval_config)],
    )

    # Act
    with pytest.raises(SystemExit) as exit_info:
        app.main()

    # Assert
    assert exit_info.value.code == 0
    assert calls["eval_file"] == eval_config
    assert calls["on_update"] is None
    assert calls["eval_session"].result_format == ResultFormat.JSON

    results_file = calls["eval_session"].run_dir / "results.json"
    assert results_file.is_file()
    results = json.loads(results_file.read_text(encoding="utf-8"))
    assert results[0]["status"] == AgentEvalStatus.COMPLETED.value

    output = capsys.readouterr().out
    assert "1 agent(s) completed, 0 failed" in output
    assert "results file saved" in output


def test_run_eval_reports_failures_and_exits_nonzero(
    monkeypatch, capsys, eval_config: Path, tmp_path: Path
):
    # Arrange
    output_dir = tmp_path / "output"
    monkeypatch.setattr("src.evals_engine.settings.OUTPUT_DIR", str(output_dir))
    calls = _fake_run_evals(monkeypatch, AgentEvalStatus.FAILED, failed=True)
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--run_eval", "--eval_file", str(eval_config)],
    )

    # Act
    with pytest.raises(SystemExit) as exit_info:
        app.main()

    # Assert
    assert exit_info.value.code == 1
    assert calls["eval_session"].run_dir.joinpath("results.json").is_file()

    output = capsys.readouterr().out
    assert "0 agent(s) completed, 1 failed" in output
    assert "FAILED: copilot_cli-test-model" in output


def test_run_eval_requires_an_eval_file(monkeypatch, capsys):
    # Arrange
    monkeypatch.setattr(sys, "argv", ["main.py", "--run_eval"])

    # Act
    with pytest.raises(SystemExit) as exit_info:
        app.main()

    # Assert
    assert exit_info.value.code == 2
    assert "no evaluation file parameter passed" in capsys.readouterr().err


def test_run_eval_reports_invalid_configuration_without_traceback(monkeypatch, capsys, tmp_path):
    # Arrange
    config_path = tmp_path / "invalid-evals.json"
    config_path.write_text("{", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--run_eval", "--eval_file", str(config_path)],
    )

    # Act
    with pytest.raises(SystemExit) as exit_info:
        app.main()

    # Assert
    assert exit_info.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "Invalid evaluation configuration" in output.err
    assert "invalid JSON" in output.err
    assert "Traceback" not in output.err
