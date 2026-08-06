from rich import print, box
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from blessed import Terminal

from .styles import PALETTE
from .execution import Execution
from .config import Config

from src.config.settings import Settings, settings
from src.helpers.tui import wait_for_selection


_options = [
    "Application Settings",
    "Execute Evaluations",
    "Display Results [Not Implemented]",
    "Quit"
]


class Menu:
    def __init__(
        self,
        *,
        terminal: Terminal | None = None,
        console: Console | None = None,
        app_settings: Settings = settings,
    ):
        self._settings = app_settings
        self._terminal = Terminal() if terminal is None else terminal
        self._console = Console() if console is None else console

    def _print_header(self):

        settings_to_display = {
            "Eval Configs Directory": self._settings.EVAL_CONFIG_DIR,
            "Evals Directory": self._settings.EVALS_DIRS,
            "Output Directory": self._settings.OUTPUT_DIR,
        }

        grid = Table.grid(padding=(0, 2))
        grid.add_column(justify="right", style=PALETTE["label"], no_wrap=True)
        grid.add_column(style=f"bold {PALETTE['value']}")
        for label, value in settings_to_display.items():
            grid.add_row(label, value)

        print(
            Panel(
                grid,
                title=Text("AGENT EVAL HARNESS", style=f"bold {PALETTE['accent']}"),
                subtitle=Text(
                    "Main Menu · Select an option (q to exit)",
                    style=f"dim {PALETTE['value']}",
                ),
                box=box.ROUNDED,
                border_style=PALETTE["border"],
                padding=(1, 3),
            )
        )

    def _print_menu(self, selected_idx: int = 0):
        self._console.clear()
        self._print_header()
        for idx, option in enumerate(_options):
            if idx == selected_idx:
                self._console.print(f"> {option}", style=PALETTE["value"])
            else:
                self._console.print(f" {option}", style=PALETTE["label"])

    def _invoke_option(self, selected_idx):
        match selected_idx:
            case 0:
                self._display_settings()
                pass
            case 1:
                self._run_evals()
            case 2:
                # TODO: implement display results
                # self._display_results()
                pass
            case 3:
                pass

    def _display_settings(self):
        config = Config(
            terminal=self._terminal,
            console=self._console,
            app_settings=self._settings
        ) 
        config.display_config()

    def _run_evals(self):
        eval_exec = Execution(
            terminal=self._terminal,
            console=self._console,
            app_settings=self._settings,
        )
        eval_exec.select_eval_config()

    def _display_results(self):
        pass

    def display(self):
        while True:

            selected_idx = wait_for_selection(
                terminal=self._terminal, options_count=len(_options), render=self._print_menu
            )

            if selected_idx is None or selected_idx == 3:
                break
            self._invoke_option(selected_idx)


if __name__ == "__main__":
    console = Console()
    terminal = Terminal()
    menu = Menu(
        terminal=terminal,
        console=console,
        app_settings=settings,
    )
    menu.display()
