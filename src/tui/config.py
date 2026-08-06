from rich.console import Console
from rich import box
from rich.panel import Panel
from rich.text import Text
from rich.table import Table

from blessed import Terminal


from src.config.settings import Settings, settings
from src.helpers.tui import wait_for_keypress

from .styles import PALETTE


PATH_FILE_SETTINGS = [
    "EVAL_CONFIG_DIR",
    "EVALS_DIRS",
    "OUTPUT_DIR",
    "RESULTS_FILENAME",
    "CSV_RESULTS_FILENAME",
]

EXECUTION_SETTINGS = [
    "BASE_IMAGE",
    "MAX_AGENT_CONCURRENCY",
    "HEALTH_CHECK_TIMEOUT_SECONDS",
    "ARRANGE_TIMEOUT_SECONDS",
    "ACT_TIMEOUT_SECONDS",
    "SCORE_TIMEOUT_SECONDS",
]

LOGGING_SETTINGS = [
    "LOG_LEVEL",
    "DOCKER_LOG_LEVEL",
    "URLLIB3_LOG_LEVEL",
]

CREDENTIAL_SETTINGS = [
    "CLAUDE_CODE_OAUTH_TOKEN",
    "COPILOT_GITHUB_TOKEN",
    "GITHUB_TOKEN",
    "AZURE_DEVOPS_PAT",
]


class Config:
    def __init__(self, *, terminal: Terminal, console: Console, app_settings: Settings = settings):
        self._terminal = terminal
        self._console = console
        self._settings = app_settings

    def _build_config_section(
        self, section_name: str, settings_to_display: dict[str, str]
    ) -> Panel:

        grid = Table.grid(padding=(0, 2))
        grid.add_column(justify="right", style=PALETTE["label"], no_wrap=True)
        grid.add_column(style=f"{PALETTE['value']}")
        for label, value in settings_to_display.items():
            grid.add_row(f"{label}:", value)

        return Panel(
            grid,
            title=Text(section_name, style=f"bold {PALETTE['good']}"),
            box=box.ROUNDED,
            border_style=PALETTE["border"],
            padding=(1, 3),
        )

    def display_config(self):
        wait_for_keypress(terminal=self._terminal, render=self._print_config)

    def _print_config(self):
        path_settings = {}
        execution_settings = {}
        logging_settings = {}
        credential_settings = {}

        for cred_setting in CREDENTIAL_SETTINGS:
            credential_settings[cred_setting] = "Not Configured"

        for setting in self._settings:
            if setting[0] in PATH_FILE_SETTINGS:
                path_settings[setting[0]] = str(setting[1])
            if setting[0] in EXECUTION_SETTINGS:
                execution_settings[setting[0]] = str(setting[1])
            if setting[0] in LOGGING_SETTINGS:
                logging_settings[setting[0]] = str(setting[1])
            if setting[0] in CREDENTIAL_SETTINGS and setting[1] != "":
                credential_settings[setting[0]] = "Configured"

        path_panel = self._build_config_section(
            section_name="Path and File Settings", settings_to_display=path_settings
        )
        execution_panel = self._build_config_section(
            section_name="Execution Settings", settings_to_display=execution_settings
        )
        logging_panel = self._build_config_section(
            section_name="Logging Settings", settings_to_display=logging_settings
        )
        credentials_panel = self._build_config_section(
            section_name="Credential Settings", settings_to_display=credential_settings
        )

        grid = Table.grid(padding=(1, 3))
        grid.add_column(justify="left", style=PALETTE["label"], no_wrap=True)
        grid.add_row("These settings can be modified using environment variables")
        grid.add_row(path_panel)
        grid.add_row(execution_panel)
        grid.add_row(logging_panel)
        grid.add_row(credentials_panel)

        self._console.print(grid)


if __name__ == "__main__":
    config = Config(
        terminal=Terminal(),
        console=Console(),
    )
    config.display_config()
