from enum import StrEnum
from dataclasses import dataclass 
from typing import Container
from uuid import UUID, uuid4
from datetime import datetime 
from src.evals.evaluation_file_protocol import EvaluationFile
from src.config.settings import settings

class GradeType(StrEnum):
    TEST_COUNT="test_count"

class AgentHarness(StrEnum):
    CLAUDE_CODE = "claude_code"
    OPENCODE = "opencode"
    GEMINI_CLI = "gemini_cli"
    COPILOT_CLI = "copilot_cli"
    CODEX = "codex"

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
    agent_harness: AgentHarness 
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

def main():
    
    print("\n=== Welcome to Agent Eval Harness, an evaluation harness for CLI Agents == \n")
    print("\n::Loading Evaluations::\n")

    evals = _load_evals()
    eval_count = 0

    for eval in evals:
        eval_count += 1
        print(f"-> Loading Evalaution {eval_count}")
        print("-----------------------------------")
        print(f"{eval.description}")

        #TODO: Spin docker container 

        #TODO: Call EvalauationFile and collect score

        #TODO: record score against the eval 
        
    


if __name__ == "__main__":
    main()

