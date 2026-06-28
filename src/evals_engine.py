import ast
import inspect
import importlib
import keyword
import textwrap
import logging
from queue import Queue, Empty
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from uuid import UUID

from src.models import AgentEvalExecution, AgentEvalStatus
from src.docker_runner import DockerRunner
from src.logging_config import agent_logger

logger = logging.getLogger(__name__)

_AGENT_SHELL_TOKEN_TRACKER = """
try:
    from agent_shell.shell import AgentShell as _EvalHarnessAgentShell
except Exception:
    _EvalHarnessAgentShell = None

if _EvalHarnessAgentShell is not None:
    _eval_harness_original_execute = _EvalHarnessAgentShell.execute

    async def _eval_harness_tracked_execute(self, *args, **kwargs):
        response = await _eval_harness_original_execute(self, *args, **kwargs)
        tokens = response.output_tokens
        try:
            tokens = int(tokens or 0)
        except (TypeError, ValueError):
            tokens = 0
        print(f"EVAL_TOTAL_TOKENS={tokens}")
        return response

    _EvalHarnessAgentShell.execute = _eval_harness_tracked_execute
"""


def run_agent(aee: AgentEvalExecution, progress: Queue, run_dir=None, session_id: UUID | None = None):

    log = logger  # fallback so the except block always has a valid logger

    try:
        log = agent_logger(aee.agent_config, run_dir) if run_dir else logger

        log.info(f"Agent: {aee.agent_config.agent_type}")
        log.info(f"Model: {aee.agent_config.agent_model}")

        aee.status = AgentEvalStatus.PROCESSING
        progress.put("update")

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
                session_id=session_id,
            )

            run_result = docker_runner.docker_run(
                arrange_script=arrange_script,
                act_script=act_script,
                score_script=score_script,
                image=image,
            )

            eval_exec.score = run_result.score
            aee.total_score += run_result.score
            eval_exec.total_tokens = run_result.total_tokens
            aee.total_tokens += run_result.total_tokens
            eval_exec.time_taken_seconds = run_result.time_taken_seconds
            aee.total_time_taken_seconds += run_result.time_taken_seconds
            eval_exec.date_executed = datetime.now()
            progress.put("update")

    except Exception:
        # Mark the agent FAILED, surface it to the live display, then let the
        # exception propagate so run_session can collect it off the future.
        log.exception(f"Agent {aee.agent_config.agent_type}-{aee.agent_config.agent_model} failed")
        aee.status = AgentEvalStatus.FAILED
        progress.put("update")
        raise

    logger.info(
        f"Agent Evaluation Run Complete - total score {aee.total_score} "
        f"- time taken {aee.total_time_taken_seconds} - total tokens {aee.total_tokens}"
    )
    aee.status = AgentEvalStatus.COMPLETED
    progress.put("update")

def _build_processing_chains(aees: list[AgentEvalExecution]) -> list[list[AgentEvalExecution]]:

    chains = []
    groups = {} 

    for aee in aees:
        group = aee.agent_config.processing_group
        if group is None: 
            chains.append([aee])
        elif group in groups:
            chains[groups[group]].append(aee)
        else: 
            groups[group] = len(chains)
            chains.append([aee])

    return chains


def run_session(
    agent_eval_executions: list[AgentEvalExecution],
    on_update: Callable[[], None],
    max_workers: int,
    run_dir=None,
    session_id: UUID | None = None,
) -> list[AgentEvalExecution]:
    """Run every agent/processing group in parallel, one worker thread per agent.
    """
    progress: Queue = Queue()
    chains = _build_processing_chains(aees=agent_eval_executions)

    def _run_chain(chain):
        for aee in chain:
            try:
                run_agent(aee, progress, run_dir, session_id)
            except Exception as e:
                logger.error(
                    f"Agent {aee.agent_config.agent_type}-{aee.agent_config.agent_model} "
                    f"failed: {e!r}"
                )
                   #this is fine because in run agent we are making it as FAILED so can swallow it
                continue

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_run_chain, chain) for chain in chains] 
        while not all(f.done() for f in futures) or not progress.empty():
            try:
                progress.get(timeout=0.1)
            except Empty:
                continue
            on_update()

    return [aee for aee in agent_eval_executions if aee.status == AgentEvalStatus.FAILED]

def _load_eval_class(eval_dir: str):
    module = importlib.import_module(f"src.evals.{eval_dir}")
    class_name = "".join(p.capitalize() for p in eval_dir.split("_"))
    return getattr(module, class_name)

_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

def _extract_method_body(method) -> str:
    src = textwrap.dedent(inspect.getsource(method))
    tree = ast.parse(src)
    fn = next((node for node in tree.body if isinstance(node, _FUNCTION_NODES)), None)
    if fn is None:
        raise ValueError(f"Expected function source for {method!r}")

    if not fn.body:
        return "pass\n"

    if fn.body[0].lineno == fn.lineno:
        parts = []
        for stmt in fn.body:
            segment = ast.get_source_segment(src, stmt)
            if segment is None:
                raise ValueError(f"Could not extract statement source from {method!r}")
            parts.append(segment)
        body = "\n".join(parts)
    else:
        lines = src.splitlines()
        start = fn.body[0].lineno - 1
        body_col = fn.body[0].col_offset

        # Preserve initial comments/blank lines inside the function body; AST
        # only reports executable statements.
        while start > fn.lineno:
            previous = lines[start - 1]
            stripped = previous.strip()
            if stripped and not stripped.startswith("#"):
                break
            if stripped and len(previous) - len(previous.lstrip()) < body_col:
                break
            start -= 1

        body = "\n".join(lines[start:fn.body[-1].end_lineno])

    return textwrap.dedent(body).rstrip() + "\n"


def _render_embedded_values(embedded_values: dict[str, object] | None = None) -> str:
    constants = ""

    for name, value in (embedded_values or {}).items():
        if not name.isidentifier() or keyword.iskeyword(name):
            raise ValueError(f"Invalid embedded value name: {name!r}")
        constants += f"{name} = {value!r}\n"

    return constants


def _method_to_script(method, embedded_values: dict[str, object] | None = None) -> str:
    body = _extract_method_body(method)
    constants = _render_embedded_values(embedded_values)

    indented = textwrap.indent(constants + _AGENT_SHELL_TOKEN_TRACKER + body, "    ")
    return f"import asyncio\nasync def _main():\n{indented}\nasyncio.run(_main())"
