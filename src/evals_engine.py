import ast
import inspect
import importlib.util
import keyword
import os
import sys
import textwrap
import signal
import logging
import docker
import json

from pathlib import Path
from queue import Queue, Empty
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from datetime import datetime
from uuid import UUID, uuid4
from agent_shell.models.agent import AgentType

from src.models import (
    AgentConfig,
    AgentEvalExecution,
    AgentEvalStatus,
    EvalExecutionStatus,
    Eval,
    EvalExecution,
    EvalSession,
    ResultFormat,
)
from src.docker_runner import DockerRunner, build_image
from src.logging_config import agent_logger, configure_logging
from src.helpers.naming import safe_name
from src.config.settings import settings
from src.evaluation_file_protocol import EvaluationFile
from src.repositories.evaluation_results import (
    EvaluationResultsService,
    JsonEvaluationResultsRepository,
    CsvEvaluationResultsRepository,
)

logger = logging.getLogger(__name__)
_SESSION_LABEL = "com.eval-harness.session"


class EvalImageResolver:
    """Resolve prebuilt images and build each eval-owned Dockerfile once per session."""

    def __init__(self):
        self._built_images: dict[Path, str] = {}
        self._lock = Lock()

    def resolve(self, eval_dir: str, eval_cls, log: logging.Logger) -> str:
        image = getattr(eval_cls, "image", None)
        dockerfile_value = getattr(eval_cls, "dockerfile", None)

        if image and dockerfile_value:
            raise ValueError(f"Eval {eval_dir!r} cannot declare both 'image' and 'dockerfile'")
        if not dockerfile_value:
            return image or settings.BASE_IMAGE

        dockerfile_relative = Path(dockerfile_value)
        if dockerfile_relative.is_absolute():
            raise ValueError(f"Eval {eval_dir!r} Dockerfile path must be relative")

        eval_root = _resolve_eval_file(eval_dir).parent.resolve()
        dockerfile = (eval_root / dockerfile_relative).resolve()
        if not dockerfile.is_relative_to(eval_root):
            raise ValueError(f"Eval {eval_dir!r} Dockerfile must be inside its eval directory")
        if not dockerfile.is_file():
            raise FileNotFoundError(f"Eval {eval_dir!r} Dockerfile not found: {dockerfile}")

        with self._lock:
            if dockerfile not in self._built_images:
                name = safe_name(eval_dir).lower()
                tag = f"eval-harness-fixture-{name}:latest"
                self._built_images[dockerfile] = build_image(dockerfile, tag, log)
            return self._built_images[dockerfile]


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


def _cleanup_eval_containers(signum, frame):
    """Kill all eval harness containers on SIGINT/SIGTERM."""
    try:
        client = docker.from_env()
        for container in client.containers.list(filters={"label": _SESSION_LABEL}, all=True):
            container.remove(force=True)
            logger.info(f"Cleaned up container {container.name}")
    except Exception as e:
        logger.error(f"Container cleanup failed: {e}")
    raise KeyboardInterrupt()


def get_results_filename(result_format: ResultFormat) -> str:
    match result_format:
        case ResultFormat.JSON:
            return settings.RESULTS_FILENAME
        case ResultFormat.CSV:
            return settings.CSV_RESULTS_FILENAME
        case _:
            raise ValueError("Result Format has not been implemented yet")


def get_results_service(result_format: ResultFormat, run_dir: Path) -> EvaluationResultsService:
    match result_format:
        case ResultFormat.JSON:
            return EvaluationResultsService(
                results_repo=JsonEvaluationResultsRepository(run_dir=run_dir)
            )
        case ResultFormat.CSV:
            return EvaluationResultsService(
                results_repo=CsvEvaluationResultsRepository(run_dir=run_dir)
            )
        case _:
            raise ValueError("Result Format has not been implemented yet")


_CONFIG_KEYS = {"evals", "agents"}
_EVAL_KEYS = {"number", "eval_dir", "description", "run_count", "tags"}
_AGENT_KEYS = {"agent_type", "agent_model", "effort", "processing_group", "eval_retries"}


def _configuration_error(eval_file: Path, location: str, message: str) -> ValueError:
    return ValueError(f"Invalid evaluation configuration {eval_file}: {location} {message}")


def _validate_mapping(
    value: object,
    *,
    eval_file: Path,
    location: str,
    required: set[str],
    allowed: set[str],
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise _configuration_error(eval_file, location, "must be an object")

    unknown = sorted(set(value) - allowed)
    if unknown:
        fields = ", ".join(repr(field) for field in unknown)
        raise _configuration_error(eval_file, location, f"contains unknown field(s): {fields}")

    missing = sorted(required - set(value))
    if missing:
        field = missing[0]
        raise _configuration_error(eval_file, location, f"missing required field {field!r}")

    return value


def _validate_non_empty_list(
    value: object,
    *,
    eval_file: Path,
    location: str,
) -> list[object]:
    if not isinstance(value, list):
        raise _configuration_error(eval_file, location, "must be a list")
    if not value:
        raise _configuration_error(eval_file, location, "must not be empty")
    return value


def _validate_string(
    value: object,
    *,
    eval_file: Path,
    location: str,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        qualifier = "" if allow_empty else " non-empty"
        raise _configuration_error(eval_file, location, f"must be a{qualifier} string")
    return value


def _validate_positive_integer(value: object, *, eval_file: Path, location: str) -> int:
    if type(value) is not int or value < 1:
        raise _configuration_error(eval_file, location, "must be a positive integer")
    return value


def _validate_non_negative_integer(value: object, *, eval_file: Path, location: str) -> int:
    if type(value) is not int or value < 0:
        raise _configuration_error(eval_file, location, "must be a non-negative integer")
    return value


def _validate_optional_string(
    value: object,
    *,
    eval_file: Path,
    location: str,
) -> str | None:
    if value is not None and not isinstance(value, str):
        raise _configuration_error(eval_file, location, "must be a string or null")
    return value or None


def _load_eval_config(eval_file: Path) -> tuple[list[Eval], list[AgentConfig]]:
    try:
        raw = json.loads(eval_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise _configuration_error(eval_file, "file", f"contains invalid JSON: {exc.msg}") from exc

    config = _validate_mapping(
        raw,
        eval_file=eval_file,
        location="root",
        required=_CONFIG_KEYS,
        allowed=_CONFIG_KEYS,
    )
    raw_evals = _validate_non_empty_list(
        config["evals"],
        eval_file=eval_file,
        location="evals",
    )
    raw_agents = _validate_non_empty_list(
        config["agents"],
        eval_file=eval_file,
        location="agents",
    )

    evals = []
    for index, raw_eval in enumerate(raw_evals):
        location = f"evals[{index}]"
        data = _validate_mapping(
            raw_eval,
            eval_file=eval_file,
            location=location,
            required=_EVAL_KEYS,
            allowed=_EVAL_KEYS,
        )
        number = _validate_positive_integer(
            data["number"], eval_file=eval_file, location=f"{location}.number"
        )
        eval_dir = _validate_string(
            data["eval_dir"], eval_file=eval_file, location=f"{location}.eval_dir"
        )
        description = _validate_string(
            data["description"],
            eval_file=eval_file,
            location=f"{location}.description",
            allow_empty=True,
        )
        run_count = _validate_positive_integer(
            data["run_count"], eval_file=eval_file, location=f"{location}.run_count"
        )
        tags = data["tags"]
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            raise _configuration_error(
                eval_file,
                f"{location}.tags",
                "must be a list of strings",
            )
        try:
            _resolve_eval_file(eval_dir)
        except FileNotFoundError as exc:
            raise _configuration_error(
                eval_file,
                f"{location}.eval_dir",
                f"{eval_dir!r} was not found in the configured evaluation directories",
            ) from exc
        evals.append(
            Eval(
                number=number,
                eval_dir=eval_dir,
                description=description,
                run_count=run_count,
                tags=tags,
            )
        )

    agents = []
    for index, raw_agent in enumerate(raw_agents):
        location = f"agents[{index}]"
        data = _validate_mapping(
            raw_agent,
            eval_file=eval_file,
            location=location,
            required={"agent_type", "agent_model"},
            allowed=_AGENT_KEYS,
        )
        agent_type_value = _validate_string(
            data["agent_type"],
            eval_file=eval_file,
            location=f"{location}.agent_type",
        )
        try:
            agent_type = AgentType(agent_type_value)
        except ValueError as exc:
            valid_types = ", ".join(agent.value for agent in AgentType)
            raise _configuration_error(
                eval_file,
                f"{location}.agent_type",
                f"must be one of: {valid_types}",
            ) from exc
        agent_model = _validate_string(
            data["agent_model"],
            eval_file=eval_file,
            location=f"{location}.agent_model",
        )
        effort = _validate_optional_string(
            data.get("effort"),
            eval_file=eval_file,
            location=f"{location}.effort",
        )
        processing_group = _validate_optional_string(
            data.get("processing_group"),
            eval_file=eval_file,
            location=f"{location}.processing_group",
        )
        eval_retries = _validate_non_negative_integer(
            data.get("eval_retries", 0),
            eval_file=eval_file,
            location=f"{location}.eval_retries",
        )
        agents.append(
            AgentConfig(
                agent_type=agent_type,
                agent_model=agent_model,
                effort=effort,
                processing_group=processing_group,
                eval_retries=eval_retries,
            )
        )

    return evals, agents


def build_eval_session(
    eval_file: Path,
    result_format: ResultFormat,
) -> EvalSession:
    session_id = uuid4()
    evals, agents = _load_eval_config(eval_file)

    return EvalSession(
        session_id=session_id,
        evals=evals,
        agents=agents,
        eval_file=str(eval_file),
        result_format=result_format,
        run_dir=Path(settings.OUTPUT_DIR) / f"{datetime.now():%Y%m%d_%H%M%S}_{session_id}",
    )


def build_agent_eval_executions(eval_session: EvalSession) -> list[AgentEvalExecution]:

    evals = eval_session.evals
    agents = eval_session.agents
    return [
        AgentEvalExecution(
            agent_config=agent,
            total_score=0,
            total_tokens=0,
            total_time_taken_seconds=0,
            evals_executions=[EvalExecution(id=uuid4(), eval=e, agent_config=agent) for e in evals],
            status=AgentEvalStatus.PENDING,
        )
        for agent in agents
    ]


def _noop_update() -> None:
    pass


def run_evals(
    eval_session: EvalSession,
    agent_eval_executions: list[AgentEvalExecution],
    eval_file: Path,
    on_update: Callable[[], None] | None = None,
) -> list[AgentEvalExecution]:

    with configure_logging(eval_session.run_dir) as run_dir:
        logger.info(f"Session {eval_session.session_id} starting")

        signal.signal(signal.SIGINT, _cleanup_eval_containers)
        signal.signal(signal.SIGTERM, _cleanup_eval_containers)
        logger.info("Beginging Evaluation Run")
        return run_session(
            agent_eval_executions=agent_eval_executions,
            on_update=_noop_update if on_update is None else on_update,
            max_workers=settings.MAX_AGENT_CONCURRENCY,
            run_dir=run_dir,
            session_id=eval_session.session_id,
        )


def run_agent(
    aee: AgentEvalExecution,
    progress: Queue,
    run_dir=None,
    session_id: UUID | None = None,
    image_resolver: EvalImageResolver | None = None,
):

    log = logger

    try:
        log = agent_logger(aee.agent_config, run_dir) if run_dir else logger

        log.info(f"Agent: {aee.agent_config.agent_type}")
        log.info(f"Model: {aee.agent_config.agent_model}")

        aee.status = AgentEvalStatus.PROCESSING
        progress.put("update")

        probe = DockerRunner(
            agent_type=aee.agent_config.agent_type,
            agent_model=aee.agent_config.agent_model,
            agent_effort=aee.agent_config.effort,
            logger=log,
            session_id=session_id,
        )
        health = probe.health_check(image=settings.BASE_IMAGE)
        if not health.healthy:
            aee.status = AgentEvalStatus.UNHEALTHY
            log.error("Agent failed health_check")
            progress.put("update")
            return

        image_resolver = image_resolver or EvalImageResolver()

        for eval_exec in aee.evals_executions:
            log.info(f"Loading Evalaution {eval_exec.eval.number} - {eval_exec.eval.description}")
            eval_mod = _load_eval_class(eval_exec.eval.eval_dir)

            image = image_resolver.resolve(eval_exec.eval.eval_dir, eval_mod, log)

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
                agent_effort=aee.agent_config.effort,
                logger=log,
                session_id=session_id,
            )

            run_count = max(eval_exec.eval.run_count, 1)
            eval_exec.status = EvalExecutionStatus.RUNNING
            run_scores: list[float] = []
            total_tokens = 0
            total_time = 0.0
            for run_number in range(1, run_count + 1):
                if run_count > 1:
                    log.info(f"Run {run_number}/{run_count}")
                for retry_number in range(aee.agent_config.eval_retries + 1):
                    if retry_number > 0:
                        docker_runner = DockerRunner(
                            agent_type=aee.agent_config.agent_type,
                            agent_model=aee.agent_config.agent_model,
                            agent_effort=aee.agent_config.effort,
                            logger=log,
                            session_id=session_id,
                        )
                    try:
                        run_result = docker_runner.docker_run(
                            arrange_script=arrange_script,
                            act_script=act_script,
                            score_script=score_script,
                            image=image,
                        )
                        break
                    except Exception as error:
                        eval_exec.last_error = f"{type(error).__name__}: {error}"
                        if retry_number >= aee.agent_config.eval_retries:
                            eval_exec.status = EvalExecutionStatus.FAILED
                            raise
                        eval_exec.retries_used += 1
                        eval_exec.status = EvalExecutionStatus.RETRYING
                        log.warning(
                            "Eval %s failed: %s. Retrying entire eval (%s/%s)",
                            eval_exec.eval.number,
                            eval_exec.last_error,
                            retry_number + 1,
                            aee.agent_config.eval_retries,
                        )
                        progress.put("update")
                run_scores.append(run_result.score)
                total_tokens += run_result.total_tokens
                total_time += run_result.time_taken_seconds

            eval_exec.score = sum(run_scores) / len(run_scores)
            aee.total_score += eval_exec.score
            eval_exec.total_tokens = total_tokens
            aee.total_tokens += total_tokens
            eval_exec.time_taken_seconds = total_time
            aee.total_time_taken_seconds += total_time
            eval_exec.date_executed = datetime.now()
            eval_exec.status = EvalExecutionStatus.COMPLETED
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
    """Run every agent/processing group in parallel, one worker thread per agent."""
    progress: Queue = Queue()
    chains = _build_processing_chains(aees=agent_eval_executions)
    image_resolver = EvalImageResolver()

    def _run_chain(chain):
        for aee in chain:
            try:
                run_agent(aee, progress, run_dir, session_id, image_resolver)
            except Exception as e:
                logger.error(
                    f"Agent {aee.agent_config.agent_type}-{aee.agent_config.agent_model} "
                    f"failed: {e!r}"
                )
                # this is fine because in run agent we are making it as FAILED so can swallow it
                continue
            if aee.status == AgentEvalStatus.UNHEALTHY:
                logger.error(
                    f"Agent {aee.agent_config.agent_type}-{aee.agent_config.agent_model} "
                    f"skipped as unhealthy before any evals ran"
                )

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_run_chain, chain) for chain in chains]
        while not all(f.done() for f in futures) or not progress.empty():
            try:
                progress.get(timeout=5.0)
            except Empty:
                continue
            on_update()

    return [
        aee
        for aee in agent_eval_executions
        if aee.status in (AgentEvalStatus.FAILED, AgentEvalStatus.UNHEALTHY)
    ]


def _resolve_eval_file(eval_dir: str) -> Path:
    searched = []
    for root in settings.EVALS_DIRS.split(os.pathsep):
        candidate = Path(root).expanduser() / eval_dir / "eval.py"
        if candidate.is_file():
            return candidate
        searched.append(str(candidate))
    raise FileNotFoundError(f"Eval {eval_dir!r} not found. Searched: {', '.join(searched)}")


def _load_eval_class(eval_dir: str):
    eval_file = _resolve_eval_file(eval_dir)
    spec = importlib.util.spec_from_file_location(f"_eval_harness_evals.{eval_dir}", eval_file)
    module = importlib.util.module_from_spec(spec)
    # registered so inspect/dataclasses can resolve the module by name
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    class_name = "".join(p.capitalize() for p in eval_dir.split("_"))
    cls = getattr(module, class_name)
    if not (isinstance(cls, type) and issubclass(cls, EvaluationFile)):
        raise TypeError(f"{class_name} must be a class implementing arrange/act/score")
    return cls


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

        body = "\n".join(lines[start : fn.body[-1].end_lineno])

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
