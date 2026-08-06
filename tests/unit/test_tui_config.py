from unittest.mock import MagicMock

from rich.console import Console

from src.config.settings import Settings
from src.tui.config import Config


def test_config_renders_read_only_settings_without_secret_values():
    # Arrange
    rendering_console = Console(record=True, width=100)
    console = MagicMock(wraps=rendering_console)
    app_settings = Settings(
        CLAUDE_CODE_OAUTH_TOKEN="secret-token",
        COPILOT_GITHUB_TOKEN="",
        GITHUB_TOKEN="",
        AZURE_DEVOPS_PAT="",
    )
    config = Config(
        terminal=MagicMock(),
        console=console,
        app_settings=app_settings,
    )

    # Act
    config._print_config()

    # Assert
    output = rendering_console.export_text()

    console.print.assert_called_once()
    assert "Path and File Settings" in output
    assert "Execution Settings" in output
    assert "Logging Settings" in output
    assert "Credential Settings" in output

    assert "EVAL_CONFIG_DIR" in output
    assert "MAX_AGENT_CONCURRENCY" in output
    assert "LOG_LEVEL" in output

    assert "CLAUDE_CODE_OAUTH_TOKEN" in output
    assert "Configured" in output
    assert "Not Configured" in output
    assert "secret-token" not in output

    assert output.index("Path and File Settings") < output.index("Execution Settings")
    assert output.index("Execution Settings") < output.index("Logging Settings")
    assert output.index("Logging Settings") < output.index("Credential Settings")
