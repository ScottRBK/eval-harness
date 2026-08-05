from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.tui.execution import Execution
from src.tui.styles import PALETTE


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
