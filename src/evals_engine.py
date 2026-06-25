import textwrap, inspect, importlib
import logging
from queue import Queue, Empty
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from src.models import AgentEvalExecution
from src.docker_runner import DockerRunner
from src.logging_config import agent_logger

logger = logging.getLogger(__name__)


def run_agent(aee: AgentEvalExecution, progress: Queue, run_dir=None):

    # Per-agent logger when running a real session; the module logger otherwise
    # (keeps unit tests filesystem-free). Records still reach session.log.
    log = agent_logger(aee.agent_config, run_dir) if run_dir else logger

    log.info(f"Agent: {aee.agent_config.agent_type}")
    log.info(f"Model: {aee.agent_config.agent_model}")

    aee.status = "processing"
    progress.put("update")

    try:
        for eval_exec in aee.evals_executions:
            log.info(f"Loading Evalaution {eval_exec.eval.number} - {eval_exec.eval.description}")
            eval_mod = _load_eval_class(eval_exec.eval.eval_dir)

            image = getattr(eval_mod, "image", "eval-harness:latest")

            # Small reminder - we split per phase as to ensure we do not get a leak of certain
            # embedded values in to the container, for example answers used in the score phase
            # in bytes on the command line
            arrange_script = _method_to_script(
                eval_mod.arrange,
                embedded_values=getattr(eval_mod, "arrange_embedded_values", {}),
            )
            act_script = _method_to_script(
                eval_mod.act,
                embedded_values=getattr(eval_mod, "act_embedded_values", {}),
            )
            score_script = _method_to_script(
                eval_mod.score,
                embedded_values=getattr(eval_mod, "score_embedded_values", {}),
            )

            docker_runner = DockerRunner(
                agent_type=aee.agent_config.agent_type,
                agent_model=aee.agent_config.agent_model,
                logger=log,
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
            progress.put("update")
    except Exception:
        # Mark the agent FAILED, surface it to the live display, then let the
        # exception propagate so run_session can collect it off the future.
        log.exception(f"Agent {aee.agent_config.agent_type}-{aee.agent_config.agent_model} failed")
        aee.status = "failed"
        progress.put("update")
        raise

    aee.status = "completed"
    progress.put("update")


def run_session(
    agent_eval_executions: list[AgentEvalExecution],
    on_update: Callable[[], None],
    max_workers: int,
    run_dir=None,
) -> list[AgentEvalExecution]:
    """Run every agent concurrently, one worker thread per agent.

    ``on_update`` is invoked on the calling thread once per progress event an
    agent emits — that is where the live display is refreshed. The display is
    injected as a callback so the engine never imports the TUI.

    A failing agent is marked FAILED (by ``run_agent``) and collected rather than
    re-raised, so one agent blowing up never sinks the rest of the session. The
    agents that failed are returned; their exceptions are logged here.
    """
    progress: Queue = Queue()

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(run_agent, aee, progress, run_dir): aee
            for aee in agent_eval_executions
        }

        # Drain progress events until every agent is done and the queue is empty.
        while not all(f.done() for f in futures) or not progress.empty():
            try:
                progress.get(timeout=0.1)
            except Empty:
                continue
            on_update()

    failed = []
    for future, aee in futures.items():
        exc = future.exception()
        if exc is not None:
            logger.error(
                f"Agent {aee.agent_config.agent_type}-{aee.agent_config.agent_model} "
                f"failed: {exc!r}"
            )
            failed.append(aee)
    return failed


def _load_eval_class(eval_dir: str):
    module = importlib.import_module(f"src.evals.{eval_dir}")
    class_name = "".join(p.capitalize() for p in eval_dir.split("_"))
    return getattr(module, class_name)


def _method_to_script(method, embedded_values: dict[str, str] | None = None) -> str:
    src = textwrap.dedent(inspect.getsource(method))
    # need to drop the method signature just so we have the raw body
    body = textwrap.dedent("\n".join(src.split("\n")[1:]))

    constants = ""
    for name, value in (embedded_values or {}).items():
        constants += f"{name} = {value!r}\n"

    indented = textwrap.indent(constants + body, "    ")
    return f"import asyncio\nasync def _main():\n{indented}\nasyncio.run(_main())"
