import time
from uuid import uuid4

from rich import print, box
from rich.live import Live
from rich.table import Table
from rich.spinner import Spinner 
from rich.panel import Panel
from rich.text import Text

from src.models import (
    AgentConfig,
    Eval,
    AgentEvalExecution,
    EvalExecution,
    AgentEvalStatus,
)

STATUS_STYLES = {
    AgentEvalStatus.PENDING: "dim #8b93a1",
    AgentEvalStatus.PROCESSING: "#9bbcff",
    AgentEvalStatus.COMPLETED: "bold #4ff3a5",
    AgentEvalStatus.FAILED: "bold #ff6b6b",
}


def print_introduction(intro_text: str):
    print(Panel(intro_text, title="Welcome to Agent Eval Harness, an evaluation harness for CLI Agents"))

class LiveStatus:
    def __init__(
            self, 
            agent_eval_execs: list[AgentEvalExecution]
    ):
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
            header_style="bold #7f8796",
            border_style="#9aa3b2",
        )

        table.add_column("Harness", style="bold white", no_wrap=True)
        table.add_column("Model", style="bold white", no_wrap=True)
        table.add_column("Status")
        table.add_column("Evals Count")
        table.add_column("Total Time (s)")
        table.add_column("Total Tokens")
        table.add_column("Total Score")

        for agent_eval_exec in self._agent_eval_execs:
            evals_completed = sum(1 for e in agent_eval_exec.evals_executions if e.score is not None)
            status = AgentEvalStatus(agent_eval_exec.status)
            if status == AgentEvalStatus.PROCESSING:
                status_cell = Spinner(
                    "arc",
                    text=Text(status.value, style=STATUS_STYLES[status]),
                    style="#82aaff",
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
                f"{agent_eval_exec.total_time_taken_seconds}",
                f"{agent_eval_exec.total_tokens}",
                f"{agent_eval_exec.total_score}",
            )

        return table
            
if __name__ == "__main__":

    agents = [
        AgentConfig(agent_type="opencode", agent_model="llama.cpp ai/qwen3.6-27b"),
        AgentConfig(agent_type="opencode", agent_model="llama.cpp ai/qwen3.6-35b"),
        AgentConfig(agent_type="claude_code", agent_model="haiku"),
    ]

    evals = [
        Eval(number=1,eval_dir="encode_repo_forgetful",description="",run_count=1, tags=["forgetful", "python"]),
        Eval(number=2,eval_dir="inflection_bug_fix",description="",run_count=1, tags=["python", "bugs"]),
        Eval(number=3,eval_dir="mapping_exercise",description="",run_count=1, tags=["python", "ruby"]),
        Eval(number=4,eval_dir="chess_engine",description="",run_count=1, tags=["rust"]),
    ]
    agent_evals_to_exec = [
        AgentEvalExecution(
            agent_config=agent,
            total_score=0,
            total_tokens=0,
            total_time_taken_seconds=0,
            evals_executions=[
                EvalExecution(id=uuid4(), eval=e, agent_config=agent) for e in evals
            ],
            status = AgentEvalStatus.PENDING,
        ) for agent in agents 
    ]

    with LiveStatus(agent_eval_execs=agent_evals_to_exec) as live_status:
        for aee in agent_evals_to_exec: 
            aee.status=AgentEvalStatus.PROCESSING
            for eval_ex in aee.evals_executions:
                eval_ex.score = 1 
                aee.total_score += eval_ex.score
                live_status.update(agent_evals_to_exec) 
                time.sleep(0.5)
            aee.status=AgentEvalStatus.COMPLETED
            live_status.update(agent_evals_to_exec) 
