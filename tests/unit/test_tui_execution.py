from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from agent_shell.models.agent import AgentType
from rich.console import Console

from src.models import (
    AgentConfig,
    AgentEvalExecution,
    AgentEvalStatus,
    Eval,
    EvalExecution,
    EvalExecutionStatus,
)
from src.tui.execution import Execution, LiveStatus
from src.tui.styles import PALETTE


def test_execution_expands_home_in_eval_configs_directory(tmp_path, monkeypatch):
    # Arrange
    home = tmp_path / "home"
    configs = home / "configs"
    configs.mkdir(parents=True)
    first = configs / "a.json"
    second = configs / "b.json"
    first.write_text("{}")
    second.write_text("{}")
    (configs / "ignored.txt").write_text("ignored")
    monkeypatch.setenv("HOME", str(home))

    # Act
    execution = Execution(
        terminal=MagicMock(),
        console=MagicMock(),
        app_settings=SimpleNamespace(EVAL_CONFIG_DIR="~/configs"),
    )

    # Assert
    assert execution._eval_configs == [first, second]


@pytest.mark.parametrize("eval_configs", [[], None])
def test_select_eval_config_returns_when_no_configs(tmp_path, eval_configs):
    # Arrange
    console = MagicMock()
    execution = Execution(
        terminal=MagicMock(),
        console=console,
        app_settings=SimpleNamespace(EVAL_CONFIG_DIR=str(tmp_path)),
    )
    execution._eval_configs = eval_configs

    # Act
    with patch("src.tui.execution.wait_for_selection") as wait_for_selection:
        result = execution.select_eval_config()

    # Assert
    assert result is None
    console.print.assert_called_once_with(
        "No evaluation configuration files found",
        style=PALETTE["label"],
    )
    wait_for_selection.assert_not_called()


def test_live_status_reports_eval_retry_progress():
    # Arrange
    agent = AgentConfig(
        agent_type=AgentType.PI,
        agent_model="test-model",
        eval_retries=2,
    )
    eval_exec = EvalExecution(
        id=uuid4(),
        eval=Eval(
            number=7,
            eval_dir="flaky_eval",
            description="flaky",
            run_count=1,
            tags=[],
        ),
        agent_config=agent,
        status=EvalExecutionStatus.RETRYING,
        retries_used=1,
        last_error="RuntimeError: act failed",
    )
    agent_exec = AgentEvalExecution(
        agent_config=agent,
        total_score=0,
        total_tokens=0,
        total_time_taken_seconds=0,
        evals_executions=[eval_exec],
        status=AgentEvalStatus.PROCESSING,
    )
    output = StringIO()
    console = Console(file=output, force_terminal=False, width=120)

    # Act
    console.print(LiveStatus([agent_exec])._render())

    # Assert
    assert "retry e7 1/2" in output.getvalue()


def test_select_eval_config_waits_for_keypress_after_saving_results(tmp_path):
    # Arrange
    console = MagicMock()
    execution = Execution(
        terminal=MagicMock(),
        console=console,
        app_settings=SimpleNamespace(EVAL_CONFIG_DIR=str(tmp_path)),
    )
    config_file = tmp_path / "a.json"
    config_file.write_text("{}")
    execution._eval_configs = [config_file]

    fake_session = SimpleNamespace(run_dir=tmp_path)
    calls: list[str] = []

    # Act
    with (
        patch("src.tui.execution.print"),
        patch("src.tui.execution.wait_for_selection", return_value=0),
        patch("src.tui.execution.build_eval_session", return_value=fake_session),
        patch("src.tui.execution.build_agent_eval_executions", return_value=[]),
        patch("src.tui.execution.LiveStatus"),
        patch("src.tui.execution.run_evals", return_value=[]),
        patch("src.tui.execution.get_results_service") as results_service,
        patch("src.tui.execution.wait_for_keypress") as wait_for_keypress,
    ):
        results_service.return_value.export.side_effect = lambda **_: calls.append("export")
        wait_for_keypress.side_effect = lambda **_: calls.append("pause")

        execution.select_eval_config()

    # Assert
    assert calls == ["export", "pause"]
    wait_for_keypress.assert_called_once()
