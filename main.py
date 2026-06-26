import argparse
import json
import logging
import signal
import sys
import docker
from uuid import UUID, uuid4
from pathlib import Path

from agent_shell.models.agent import AgentType

from src.config.settings import settings
from src.evals_engine import run_session
from src.logging_config import configure_logging
from src.tui import LiveStatus
from src.repositories.evaluation_results import (
    EvaluationResultsService,
    JsonEvaluationResultsRepository,
    CsvEvaluationResultsRepository,
)
from src.models import (
    AgentConfig,
    AgentEvalExecution,
    AgentEvalStatus,
    Eval,
    EvalSession,
    EvalExecution,
    ResultFormat,
)

logger = logging.getLogger(__name__)

_SESSION_LABEL = "com.eval-harness.session"

def _get_results_service(result_format: ResultFormat, run_dir: Path) -> EvaluationResultsService:
    match result_format:
        case ResultFormat.JSON:
            return EvaluationResultsService(results_repo=JsonEvaluationResultsRepository(run_dir=run_dir))
        case ResultFormat.CSV:
            return EvaluationResultsService(results_repo=CsvEvaluationResultsRepository(run_dir=run_dir))
        case _:
            raise ValueError("Result Format has not been implemented yet")

def _get_results_filename(result_format: ResultFormat) -> str:
    match result_format:
        case ResultFormat.JSON:
            return settings.RESULTS_FILENAME
        case ResultFormat.CSV:
            return settings.CSV_RESULTS_FILENAME
        case _:
            raise ValueError("Result Format has not been implemented yet")

def _cleanup_eval_containers(signum, frame):
    """Kill all eval harness containers on SIGINT/SIGTERM."""
    try:
        client = docker.from_env()
        for container in client.containers.list(
            filters={"label": _SESSION_LABEL}, all=True
        ):
            container.remove(force=True)
            logger.info(f"Cleaned up container {container.name}")
    except Exception as e:
        logger.error(f"Container cleanup failed: {e}")
    raise KeyboardInterrupt()

def _load_evals(eval_file: Path, session_id: UUID) -> EvalSession:
    
    eval_config_str = eval_file.read_text(encoding="utf-8")
    raw = json.loads(eval_config_str)

    return EvalSession(
        session_id=session_id,
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

def _configure_args_parse() -> argparse.ArgumentParser:
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

    parser.add_argument(
        "-rf",
        "--results_format",
        help="output format for results file",
        type=ResultFormat,
        choices=list(ResultFormat),
        default=ResultFormat.JSON,
    )
    
    return parser 


def main():
    print("\n=== Welcome to Agent Eval Harness, an evaluation harness for CLI Agents == \n")

    session_id = uuid4()
    run_dir = configure_logging(session_id=session_id)
    print(f"Evaluation Session ID: {session_id}")
    print(f"Session Output Directory: {run_dir}")
    logger.info(f"Session {session_id} starting")

    signal.signal(signal.SIGINT, _cleanup_eval_containers)
    signal.signal(signal.SIGTERM, _cleanup_eval_containers)

    parser = _configure_args_parse() 
    args = parser.parse_args()

    eval_file = args.eval_file if args.eval_file else "evals.json"

    results_service = _get_results_service(result_format=args.results_format, run_dir=run_dir) 

    print(f"\n::Loading Evaluations from {eval_file}::\n")
    print(f"::Results will be exported to {args.results_format}")

    eval_session = _load_evals(eval_file=Path(eval_file), session_id=session_id)

    evals = eval_session.evals
    agents = eval_session.agents
    agent_eval_executions = [
        AgentEvalExecution(
            agent_config=agent,
            total_score=0,
            total_tokens=0,
            total_time_taken_seconds=0,
            evals_executions=[
                EvalExecution(id=uuid4(), eval=e, agent_config=agent) for e in evals
            ],
            status=AgentEvalStatus.PENDING,
        ) for agent in agents 
    ]

    logger.info("Beginging Evaluation Run")
    with LiveStatus(agent_eval_execs=agent_eval_executions) as live_status:
        failed = run_session(
            agent_eval_executions,
            on_update=lambda: live_status.update(agent_eval_execs=agent_eval_executions),
            max_workers=settings.MAX_AGENT_CONCURRENCY,
            run_dir=run_dir,
            session_id=session_id,
        )

    completed = [
        aee for aee in agent_eval_executions
        if aee.status == AgentEvalStatus.COMPLETED
    ]
    summary = f"{len(completed)} agent(s) completed, {len(failed)} failed"
    logger.info(f"Evaluation run finished: {summary}")
    print(f"\n{summary}")
    for aee in failed:
        print(f"  FAILED: {aee.agent_config.agent_type}-{aee.agent_config.agent_model}")
    
    print(f"saving results file to {run_dir / _get_results_filename(args.results_format)}")
    results_service.export(aees=agent_eval_executions)
    print("results file saved")

    if failed:
        sys.exit(1)
                   
if __name__ == "__main__":
    main()
