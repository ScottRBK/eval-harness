import inspect, textwrap, importlib
from enum import StrEnum
from dataclasses import dataclass 
from typing import Container
from uuid import UUID, uuid4
from datetime import datetime 
from pathlib import Path

from agent_shell.models.agent import AgentType

import docker

from src.evals.evaluation_file_protocol import EvaluationFile
from src.config.settings import settings
from src.docker_runner import DockerRunner


class GradeType(StrEnum):
    TEST_COUNT="test_count"

@dataclass
class Eval:
    id: UUID
    number: int
    eval_file: str
    description: str
    run_count: int 
    tags: list[str]

@dataclass 
class AgentConfig:
    agent_type: AgentType
    agent_model: str

@dataclass
class EvalExecution: 
    id: UUID 
    eval_id: UUID 
    agent_config: AgentConfig
    effort: str
    total_tokens: float
    score: float 
    date_executed: datetime

@dataclass 
class EvalRun:
    eval_runs: list[EvalExecution]
    date_executed: datetime 
    agents: list[AgentConfig]

def _load_evals() -> list[Eval]:
    evals = [] 
    #TO:DO Load Evals from a CSV/JSON file 
    first_eval = Eval(
            id=uuid4(),
            number=1,
            eval_file="encode_repo_forgetful",
            description="encode a repo into forgetful and then query forgetful for facts re: it",
            run_count=3,
            tags=["forgetful"]
    )
    evals.append(first_eval)
    return evals

def load_eval_class(eval_file: str): 
    module = importlib.import_module(f"src.evals.{eval_file}")
    class_name = "".join(p.capitalize() for p in eval_file.split("_"))
    return getattr(module, class_name) 

def method_to_script(method) -> str:
    src = textwrap.dedent(inspect.getsource(method))
    # need to drop the method signature just so we have the raw body
    body = "\n".join(src.split("\n")[1:])
    return textwrap.dedent(body)


def main():
    
    print("\n=== Welcome to Agent Eval Harness, an evaluation harness for CLI Agents == \n")
    print("\n::Loading Evaluations::\n")

    evals = _load_evals()
    eval_count = 0
    # agent_type = AgentType.CLAUDE_CODE
    # agent_model = "haiku"
    agent_type = AgentType.OPENCODE
    agent_model = "opencode/big-pickle"

    for eval in evals:
        eval_count += 1
        print(f"-> Loading Evalaution {eval_count}")
        print("-----------------------------------")
        print(f"{eval.description}")
        
        eval_mod = load_eval_class(eval.eval_file)
        script = method_to_script(eval_mod.act)

        docker_runner = DockerRunner(agent_type=agent_type, agent_model=agent_model)
        docker_output = docker_runner.docker_run(script)

       
        #TODO: Spin docker container 
        #TODO: Call EvalauationFile and collect score

        #TODO: record score against the eval 
        

if __name__ == "__main__":
    main()

