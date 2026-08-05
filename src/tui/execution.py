import time
import logging 
from pathlib import Path
from uuid import uuid4

from rich import print, box
from rich.live import Live
from rich.table import Table
from rich.spinner import Spinner
from rich.panel import Panel
from rich.text import Text
from rich.console import Console 
from blessed import Terminal

from src.models import (
    AgentConfig,
    Eval,
    AgentEvalExecution,
    EvalExecution,
    AgentEvalStatus,
    ResultFormat,
    EvalSession,
)
from src.config.settings import Settings, settings 
from src.helpers.tui import wait_for_selection
from src.evals_engine import (
    get_results_filename,
    run_evals, 
    build_eval_session, 
    build_agent_eval_executions,
    get_results_service,
    get_results_filename,
)
from .styles import PALETTE, STATUS_STYLES

def print_introduction(fields: dict[str, str]):
    grid = Table.grid(padding=(0, 2))
    grid.add_column(justify="right", style=PALETTE["label"], no_wrap=True)
    grid.add_column(style=f"bold {PALETTE['value']}")
    for label, value in fields.items():
        grid.add_row(label, value)

    print(
        Panel(
            grid,
            title=Text("AGENT EVAL HARNESS", style=f"bold {PALETTE['accent']}"),
            subtitle=Text("an evaluation harness for CLI agents", style=f"dim {PALETTE['label']}"),
            box=box.ROUNDED,
            border_style=PALETTE["border"],
            padding=(1, 3),
        )
    )

class Execution():
    def __init__(self, terminal: Terminal, console: Console, app_settings: Settings = settings):
        self._terminal = terminal
        self._console = console
        self._settings = app_settings 
        self._eval_configs = self._load_eval_configs(eval_config=self._settings.EVAL_CONFIG_DIR)

    def _load_eval_configs(self, eval_config: str) -> list[Path]: 
        config_dir = Path(eval_config)

        if not config_dir.is_dir():
            raise ValueError(f"""Invalid evaluation configs directory (env EVAL_HARNESS_EVAL_CONFIG_DIR)
                             {eval_config} is not a directory""")

        return sorted(config_dir.glob("*.json"))

    def _print_header(self): 
        print(
                Panel(
                    "Select a configuration file to begin an evaluation",
                    title=Text("AGENT EVAL HARNESS", style=f"bold {PALETTE['accent']}"),
                    subtitle=Text("Select config", style=f"dim {PALETTE['label']}"),
                    box=box.ROUNDED,
                    border_style=PALETTE["border"],
                    padding=(1, 3),
                )
            )      

    def _print_eval_configs(self, selected_idx: int = 0):
        self._console.clear()
        self._print_header()        
        for idx, config in enumerate(self._eval_configs): 
            if idx == selected_idx:
                self._console.print(f"> {config}", style=PALETTE['value'])
            else:
                self._console.print(f" {config}", style=PALETTE['label'])


    def handle_eval_start(self, eval_session: EvalSession):
        print_introduction({
                    "Session ID": str(eval_session.session_id),
                    "Output Directory": str(eval_session.run_dir),
                    "Evals": eval_session.eval_file,
                    "Results": eval_session.result_format,
                })


    def select_eval_config(self):
        selected_idx = wait_for_selection(
            terminal=self._terminal,
            options_count=len(self._eval_configs),
            render=self._print_eval_configs, 
        )
        if selected_idx is None:
            return None

        selected_config = self._eval_configs[selected_idx]
        path_eval_config = Path(selected_config)
        result_format = ResultFormat.JSON #TODO: Need to retrieve from configuration
    
        eval_session = build_eval_session(eval_file=path_eval_config, result_format=result_format) 
        agent_eval_executions = build_agent_eval_executions(eval_session=eval_session)

        self._console.clear()

        with LiveStatus(agent_eval_execs=agent_eval_executions) as live_status:
            failed = run_evals(
                eval_session=eval_session,
                agent_eval_executions=agent_eval_executions,
                eval_file=path_eval_config,
                on_update=lambda: live_status.update(agent_eval_execs=agent_eval_executions),
                )
            
        logger = logging.getLogger(__name__)
        completed = [aee for aee in agent_eval_executions if aee.status == AgentEvalStatus.COMPLETED]
        summary = f"{len(completed)} agent(s) completed, {len(failed)} failed"
        logger.info(f"Evaluation run finished: {summary}")
        print(f"\n{summary}")
        for aee in failed:
            print(f"  FAILED: {aee.agent_config.agent_type}-{aee.agent_config.agent_model}")

        print(f"saving results file to {eval_session.run_dir / get_results_filename(result_format)}")
        results_service = get_results_service(result_format=result_format, run_dir=eval_session.run_dir)
        results_service.export(aees=agent_eval_executions)
        print("results file saved")


class LiveStatus:
    def __init__(self, agent_eval_execs: list[AgentEvalExecution]):
        self._agent_eval_execs = agent_eval_execs
        self._live = Live(self._render(), refresh_per_second=10)

    def __enter__(self):
        self._live.start()
        return self

    def __exit__(self, *exc):
        self._live.stop()

    def update(self, agent_eval_execs: list[AgentEvalExecution]):
        self._agent_eval_execs = agent_eval_execs
        self._live.update(self._render())

    def _render(self) -> Table:

        table = Table(
            box=box.HORIZONTALS,
            show_edge=False,
            show_lines=True,
            pad_edge=False,
            padding=(0, 2),
            header_style=f"bold {PALETTE['header']}",
            border_style=PALETTE["border"],
        )

        table.add_column("Harness", style="bold white", no_wrap=True)
        table.add_column("Model", style="bold white", no_wrap=True)
        table.add_column("Status")
        table.add_column("Evals Count")
        table.add_column("Total Time (s)")
        table.add_column("Total Tokens")
        table.add_column("Total Score")

        for agent_eval_exec in self._agent_eval_execs:
            evals_completed = sum(
                1 for e in agent_eval_exec.evals_executions if e.score is not None
            )
            status = AgentEvalStatus(agent_eval_exec.status)
            if status == AgentEvalStatus.PROCESSING:
                status_cell = Spinner(
                    "arc",
                    text=Text(status.value, style=STATUS_STYLES[status]),
                    style=PALETTE["accent_alt"],
                )
            else:
                status_cell = Text(status.value, style=STATUS_STYLES[status])

            if agent_eval_exec.agent_config.effort:
                model_name = f"{agent_eval_exec.agent_config.agent_model} ({agent_eval_exec.agent_config.effort})"
            else:
                model_name = agent_eval_exec.agent_config.agent_model

            table.add_row(
                f"{agent_eval_exec.agent_config.agent_type}",
                model_name,
                status_cell,
                f"{evals_completed} / {len(agent_eval_exec.evals_executions)}",
                f"{agent_eval_exec.total_time_taken_seconds:,.2f}",
                f"{agent_eval_exec.total_tokens:,}",
                f"{agent_eval_exec.total_score:.2f}",
            )

        return table


if __name__ == "__main__":
    agents = [
        AgentConfig(agent_type="opencode", agent_model="llama.cpp ai/qwen3.6-27b"),
        AgentConfig(agent_type="opencode", agent_model="llama.cpp ai/qwen3.6-35b"),
        AgentConfig(agent_type="claude_code", agent_model="haiku"),
    ]

    evals = [
        Eval(
            number=1,
            eval_dir="encode_repo_forgetful",
            description="",
            run_count=1,
            tags=["forgetful", "python"],
        ),
        Eval(
            number=2,
            eval_dir="inflection_bug_fix",
            description="",
            run_count=1,
            tags=["python", "bugs"],
        ),
        Eval(
            number=3,
            eval_dir="mapping_exercise",
            description="",
            run_count=1,
            tags=["python", "ruby"],
        ),
        Eval(number=4, eval_dir="chess_engine", description="", run_count=1, tags=["rust"]),
    ]
    agent_evals_to_exec = [
        AgentEvalExecution(
            agent_config=agent,
            total_score=0,
            total_tokens=0,
            total_time_taken_seconds=0,
            evals_executions=[EvalExecution(id=uuid4(), eval=e, agent_config=agent) for e in evals],
            status=AgentEvalStatus.PENDING,
        )
        for agent in agents
    ]

    with LiveStatus(agent_eval_execs=agent_evals_to_exec) as live_status:
        for aee in agent_evals_to_exec:
            aee.status = AgentEvalStatus.PROCESSING
            for eval_ex in aee.evals_executions:
                eval_ex.score = 1
                aee.total_score += eval_ex.score
                live_status.update(agent_evals_to_exec)
                time.sleep(0.5)
            aee.status = AgentEvalStatus.COMPLETED
            live_status.update(agent_evals_to_exec)
