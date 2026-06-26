import csv
import json
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from typing import Any, Protocol
from pathlib import Path
from uuid import UUID
import logging

from src.models import AgentEvalExecution
from src.config.settings import settings

logger = logging.getLogger(__name__)

CSV_FIELDNAMES = [
    "agent_type",
    "agent_model",
    "agent_effort",
    "agent_status",
    "agent_total_score",
    "agent_total_tokens",
    "agent_total_time_taken_seconds",
    "eval_execution_id",
    "eval_number",
    "eval_dir",
    "eval_description",
    "eval_run_count",
    "eval_tags",
    "eval_score",
    "eval_total_tokens",
    "eval_time_taken_seconds",
    "eval_date_executed",
]


def _serialize_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _parse_non_serialisable(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serialisable")


class EvaluationResultsRepository(Protocol):
    def export (self, aees: list[AgentEvalExecution]) -> None:
        ...

class EvaluationResultsService():
    def __init__(self, results_repo: EvaluationResultsRepository):
        self._results_repo = results_repo

    def export(self, aees: list[AgentEvalExecution]) -> None:
        self._results_repo.export(aees=aees) 

class JsonEvaluationResultsRepository():
    def __init__(self, run_dir: Path):
        self._results_file = run_dir / settings.RESULTS_FILENAME

    def export(self, aees: list[AgentEvalExecution]) -> None:
        res = json.dumps([asdict(aee) for aee in aees], default=_parse_non_serialisable, indent=2)
        
        logger.debug(f"exporting results file to {self._results_file}")
        try:
            self._results_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._results_file, "w", encoding="utf-8") as f:
                f.write(res)
        except Exception as e:
            logger.error(f"error writing results json file: {e}")
            return
        logger.debug("results file exported")
        
class CsvEvaluationResultsRepository():
    def __init__(self, run_dir: Path):
        self._results_file = run_dir / settings.CSV_RESULTS_FILENAME

    def export(self, aees: list[AgentEvalExecution]) -> None:
        logger.debug(f"exporting results file to {self._results_file}")
        try:
            self._results_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._results_file, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=CSV_FIELDNAMES,
                    lineterminator="\n",
                )
                writer.writeheader()
                for aee in aees:
                    for eval_execution in aee.evals_executions:
                        writer.writerow(
                            {
                                "agent_type": _serialize_cell(aee.agent_config.agent_type),
                                "agent_model": _serialize_cell(aee.agent_config.agent_model),
                                "agent_effort": _serialize_cell(aee.agent_config.effort),
                                "agent_status": _serialize_cell(aee.status),
                                "agent_total_score": _serialize_cell(aee.total_score),
                                "agent_total_tokens": _serialize_cell(aee.total_tokens),
                                "agent_total_time_taken_seconds": _serialize_cell(
                                    aee.total_time_taken_seconds
                                ),
                                "eval_execution_id": _serialize_cell(eval_execution.id),
                                "eval_number": _serialize_cell(eval_execution.eval.number),
                                "eval_dir": _serialize_cell(eval_execution.eval.eval_dir),
                                "eval_description": _serialize_cell(
                                    eval_execution.eval.description
                                ),
                                "eval_run_count": _serialize_cell(eval_execution.eval.run_count),
                                "eval_tags": json.dumps(eval_execution.eval.tags),
                                "eval_score": _serialize_cell(eval_execution.score),
                                "eval_total_tokens": _serialize_cell(
                                    eval_execution.total_tokens
                                ),
                                "eval_time_taken_seconds": _serialize_cell(
                                    eval_execution.time_taken_seconds
                                ),
                                "eval_date_executed": _serialize_cell(
                                    eval_execution.date_executed
                                ),
                            }
                        )
        except Exception as e:
            logger.error(f"error writing results csv file: {e}")
            return
        logger.debug("results file exported")


if __name__ == "__main__":
    from uuid import uuid4
    from src.models import AgentConfig, Eval, EvalExecution 

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
            status = "pending",
        ) for agent in agents 
    ]

    json_repo = JsonEvaluationResultsRepository(run_dir="./output/tests")
    json_repo.export(agent_evals_to_exec)





    
