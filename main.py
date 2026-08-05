import argparse
import logging
import sys
from pathlib import Path

from src.evals_engine import (
    run_evals,
    build_eval_session,
    build_agent_eval_executions,
    get_results_service,
    get_results_filename,
)
from src.tui.menu import Menu
from src.models import AgentEvalStatus, ResultFormat

logger = logging.getLogger(__name__)


def _configure_args_parse() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="Agent Evaluation Harness",
        description="Harness for running evaluations against agentic harnesses",
    )

    parser.add_argument(
        "-re",
        "--run_eval",
        help="run evaluations headlessly, requires eval file parameter",
        action="store_true",
    )

    parser.add_argument(
        "-ef", "--eval_file", help="path to file containing which evaluations to run", type=Path
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

    parser = _configure_args_parse()
    args = parser.parse_args()

    if args.run_eval:
        if not args.eval_file:
            parser.error("no evaluation file parameter passed, please use -ef or --eval_file")

        try:
            eval_session = build_eval_session(
                eval_file=args.eval_file, result_format=args.results_format
            )
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        agent_eval_executions = build_agent_eval_executions(eval_session=eval_session)

        failed = run_evals(
            eval_session=eval_session,
            agent_eval_executions=agent_eval_executions,
            eval_file=args.eval_file,
            on_update=None,
        )

        completed = [
            aee for aee in agent_eval_executions if aee.status == AgentEvalStatus.COMPLETED
        ]
        summary = f"{len(completed)} agent(s) completed, {len(failed)} failed"
        logger.info(f"Evaluation run finished: {summary}")
        print(f"\n{summary}")
        for aee in failed:
            print(f"  FAILED: {aee.agent_config.agent_type}-{aee.agent_config.agent_model}")

        print(
            f"saving results file to {eval_session.run_dir / get_results_filename(eval_session.result_format)}"
        )
        results_service = get_results_service(
            result_format=eval_session.result_format, run_dir=eval_session.run_dir
        )
        results_service.export(aees=agent_eval_executions)
        print("results file saved")

        if failed:
            sys.exit(1)
        else:
            sys.exit(0)

    menu = Menu()
    menu.display()


if __name__ == "__main__":
    main()
