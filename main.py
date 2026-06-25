import argparse
import json
import logging
import sys
from uuid import UUID, uuid4
from datetime import datetime
from pathlib import Path

from agent_shell.models.agent import AgentType

from src.config.settings import settings
from src.evals_engine import run_session
from src.tui import LiveStatus
from src.models import (
    Eval,
    EvalSession,
    AgentConfig,
    AgentEvalExecution,
    AgentEvalStatus,
    EvalExecution,
)

logger = logging.getLogger(__name__)

def _configure_logging(session_id: UUID) -> str:
    log_dir = Path(settings.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"eval_harness_{datetime.now():%Y%m%d_%H%M%S}_{session_id}.log"

    handler = logging.FileHandler(filename=log_path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s")
    )

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL))

    logging.getLogger("docker").setLevel(settings.DOCKER_LOG_LEVEL)
    logging.getLogger("urllib3").setLevel(settings.URLLIB3_LOG_LEVEL)

    return str(log_path)

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

def main():
    print("\n=== Welcome to Agent Eval Harness, an evaluation harness for CLI Agents == \n")

    session_id = uuid4()
    log_path = _configure_logging(session_id=session_id)
    print(f"Evaluation Session ID: {session_id}")
    print(f"Session Log File Located At: {log_path}")
    logger.info(f"Session {session_id} starting")

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

    print(f"\n::Loading Evaluations from {eval_file}::\n")

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
            status="pending",
        ) for agent in agents 
    ]

    logger.info("Beginging Evaluation Run")
    with LiveStatus(agent_eval_execs=agent_eval_executions) as live_status:
        failed = run_session(
            agent_eval_executions,
            on_update=lambda: live_status.update(agent_eval_execs=agent_eval_executions),
            max_workers=settings.MAX_AGENT_CONCURRENCY,
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

    if failed:
        sys.exit(1)
               
                   
if __name__ == "__main__":
    main()

