import inspect, textwrap, importlib
import argparse
import json
import logging 
from logging.handlers import TimedRotatingFileHandler 
from uuid import uuid4
from datetime import datetime 
from pathlib import Path

from agent_shell.models.agent import AgentType

from src.config.settings import settings
from src.docker_runner import DockerRunner
from src.tui import LiveStatus
from src.models import (
    Eval,
    EvalConfig,
    AgentConfig,
    AgentEvalExecution,
    EvalExecution,
)

handler = TimedRotatingFileHandler(
    filename=settings.LOG_FILENAME,
    when="midnight",
    interval=1,
    backupCount=3, 
    encoding="utf-8",
)

handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s"))
root_logger = logging.getLogger()
root_logger.addHandler(handler)
root_logger.setLevel(getattr(logging, settings.LOG_LEVEL))

logger = logging.getLogger(__name__)

def _load_evals(eval_file: Path) -> EvalConfig:
    
    eval_config_str = eval_file.read_text(encoding="utf-8")
    raw = json.loads(eval_config_str)

    return EvalConfig(
        evals=[Eval(**e) for e in raw["evals"]],
        agents=[
            AgentConfig(
                agent_type=AgentType(a["agent_type"]),
                agent_model=a["agent_model"],
                effort=a.get("effort") or None
            )
            for a in raw["agents"]
        ],
    )

def load_eval_class(eval_file: str): 
    module = importlib.import_module(f"src.evals.{eval_file}")
    class_name = "".join(p.capitalize() for p in eval_file.split("_"))
    return getattr(module, class_name) 

def method_to_script(method, embedded_values: dict[str, str] | None = None ) -> str:
    src = textwrap.dedent(inspect.getsource(method))
    # need to drop the method signature just so we have the raw body
    body = textwrap.dedent("\n".join(src.split("\n")[1:]))

    constants = ""
    for name, value in (embedded_values or {}).items():
        constants += f"{name} = {value!r}\n"

    indented = textwrap.indent(constants + body, "    ")
    return f"import asyncio\nasync def _main():\n{indented}\nasyncio.run(_main())"


def main():

    parser = argparse.ArgumentParser(
        prog="Agent Evaluation Harness",
        description="Harness for running evaluations against agentic harnesses",
    ) 
    
    parser.add_argument(
        "-ef", 
        "--eval_file", 
        help="path to file containing which evaluations to run",
        type=Path
    )

    args = parser.parse_args()
    eval_file = args.eval_file if args.eval_file else "evals.json"

    print("\n=== Welcome to Agent Eval Harness, an evaluation harness for CLI Agents == \n")
    print(f"\n::Loading Evaluations from {eval_file}::\n")

    evals_config = _load_evals(Path(eval_file))
    evals = evals_config.evals
    agents = evals_config.agents
    agent_eval_executions = [
        AgentEvalExecution(
            agent_config=agent,
            total_score=0,
            total_tokens=0,
            total_time_taken_seconds=0,
            evals_executions=[
                EvalExecution(id=uuid4(), eval=e, agent_config=agent) for e in evals
            ],
            status="pending",
        ) for agent in agents 
    ]
        
    logger.info("Beginging Evaluation Run")
    with LiveStatus(agent_eval_execs=agent_eval_executions) as live_status:
        for aee in agent_eval_executions:
            logger.info(f"Agent: {aee.agent_config.agent_type}")
            logger.info(f"Model: {aee.agent_config.agent_model}")

            aee.status = "processing"
            live_status.update(agent_eval_execs=agent_eval_executions)

            for eval_exec in aee.evals_executions:
                logger.info(f"Loading Evalaution {eval_exec.eval.number} - {eval_exec.eval.description}")
                eval_mod = load_eval_class(eval_exec.eval.eval_dir)

                image = getattr(eval_mod, "image", "eval-harness:latest")

                arrange_script = method_to_script(
                    eval_mod.arrange,
                    embedded_values=getattr(eval_mod, "arrange_embedded_values", {}),
                )
                act_script= method_to_script(
                    eval_mod.act,
                    embedded_values=getattr(eval_mod, "act_embedded_values", {}),
                )
                score_script = method_to_script(
                    eval_mod.score,
                    embedded_values=getattr(eval_mod, "score_embedded_values", {}),
                )

                docker_runner = DockerRunner(
                    agent_type=aee.agent_config.agent_type, 
                    agent_model=aee.agent_config.agent_model,
                )

                score, time_taken = docker_runner.docker_run(
                    arrange_script=arrange_script,
                    act_script=act_script,
                    score_script=score_script,
                    image=image,
                )

                eval_exec.score = score
                aee.total_score += score 
                eval_exec.time_taken_seconds = time_taken 
                aee.total_time_taken_seconds += time_taken 
                eval_exec.date_executed = datetime.now() 
                live_status.update(agent_eval_execs=agent_eval_executions)
                
            aee.status = "completed"
            live_status.update(agent_eval_execs=agent_eval_executions)
            logger.info(f"Agent {aee.agent_config.agent_type}-{aee.agent_config.agent_model} evaluation complete")
            logger.info(f"Total Score: {aee.total_score}")

       
if __name__ == "__main__":
    main()

