import tempfile
import os
import shutil
import docker
import time
import logging
from pathlib import Path
from agent_shell.models.agent import AgentType, HealthCheckResult

from uuid import UUID

from src.models import AgentProvisioning, DockerRunResult
from src.config.settings import settings
from src.helpers.naming import safe_name

_SESSION_LABEL = "com.eval-harness.session"
_TOKEN_MARKER = "EVAL_TOTAL_TOKENS="

# Harness-owned agent config, version-controlled. Mounted read-only into the
# container so runs are reproducible and independent of the host's own config.
CONFIG_ROOT = Path(__file__).parent / "docker" / "configs"


def _parse_total_tokens(buffer: str, log: logging.Logger) -> int:
    total_tokens = 0
    for line in buffer.splitlines():
        if not line.startswith(_TOKEN_MARKER):
            continue
        raw = line.removeprefix(_TOKEN_MARKER).strip()
        try:
            total_tokens += int(raw)
        except ValueError:
            log.warning("Ignoring malformed token marker line: %r", line)
    return total_tokens


class DockerRunner:
    def __init__(
        self,
        agent_type: AgentType,
        agent_model: str,
        agent_effort: str | None = None,
        logger: logging.Logger | None = None,
        session_id: UUID | None = None,
    ):
        self._agent_type = agent_type
        self._agent_model = agent_model
        self._agent_effort = agent_effort
        # Per-agent logger when the engine injects one; module logger otherwise.
        self._log = logger or logging.getLogger(__name__)
        # Throwaway dirs we create for credentials; deleted after the run.
        self._temp_dirs: list[Path] = []
        self._session_id = session_id

    def _staged_mount(self, files: list[Path], container_dir: str) -> dict[str, dict[str, str]]:
        """Copy files into a throwaway dir and bind that dir read-write.

        The agent - and agent_shell, which rewrites opencode.json to inject MCP
        servers - can mutate the mounted files freely. The originals (host
        secrets and the version-controlled repo config) are copies, so they are
        never touched. The temp dir is tracked so the run can delete it after.
        """
        staging = Path(tempfile.mkdtemp(prefix="eval-mount-"))
        # Allow the container node user to traverse the throwaway host bind mount.
        os.chmod(staging, 0o777)  # noqa: S103 - required for cross-UID Docker binds
        for source in files:
            shutil.copy2(source, staging / source.name)
            os.chmod(staging / source.name, 0o644)
        self._temp_dirs.append(staging)

        return {str(staging): {"bind": container_dir, "mode": "rw"}}

    def _setup_codex(self) -> AgentProvisioning:
        auth = Path(settings.CODEX_CREDENTIALS_LOC).expanduser()
        if not auth.exists():
            raise RuntimeError(
                f"Codex auth file not found at {auth} (run `codex login` on the host)"
            )
        return AgentProvisioning(volumes=self._staged_mount([auth], "/home/node/.codex"))

    def _setup_pi(self) -> AgentProvisioning:
        auth = Path(settings.PI_CREDENTIALS_LOC).expanduser()
        if not auth.exists():
            raise RuntimeError(
                f"Pi auth file not found at {auth} (run `pi` then `/login` on the host)"
            )
        return AgentProvisioning(volumes=self._staged_mount([auth], "/home/node/.pi/agent"))

    def _setup_copilot(self) -> AgentProvisioning:
        if not settings.COPILOT_GITHUB_TOKEN:
            raise RuntimeError(
                "COPILOT_GITHUB_TOKEN not configured (set EVAL_HARNESS_COPILOT_GITHUB_TOKEN"
            )
        return AgentProvisioning(
            environment={"COPILOT_GITHUB_TOKEN": settings.COPILOT_GITHUB_TOKEN}
        )

    def _setup_claude_code(self) -> AgentProvisioning:
        if not settings.CLAUDE_CODE_OAUTH_TOKEN:
            raise RuntimeError(
                "CLAUDE_CODE_OAUTH_TOKEN not configured (run `claude setup-token` and set env var)"
            )
        return AgentProvisioning(
            environment={"CLAUDE_CODE_OAUTH_TOKEN": settings.CLAUDE_CODE_OAUTH_TOKEN}
        )

    def _setup_opencode(self) -> AgentProvisioning:
        creds_file = Path(settings.OPENCODE_CREDENTIALS_LOC).expanduser()
        if not creds_file.exists():
            raise RuntimeError(
                f"OpenCode auth file not found at {creds_file} (run `opencode auth login`)"
            )
        credentials = self._staged_mount([creds_file], "/home/node/.local/share/opencode")
        config = self._staged_mount(
            [CONFIG_ROOT / "opencode" / "opencode.json"],
            "/home/node/.config/opencode",
        )
        return AgentProvisioning(volumes=credentials | config)

    def _provision_agent(self) -> AgentProvisioning:
        match self._agent_type:
            case AgentType.CLAUDE_CODE:
                return self._setup_claude_code()
            case AgentType.OPENCODE:
                return self._setup_opencode()
            case AgentType.CODEX:
                return self._setup_codex()
            case AgentType.PI:
                return self._setup_pi()
            case AgentType.COPILOT_CLI:
                return self._setup_copilot()
            case _:
                raise NotImplementedError(f"Agent not implemented for {self._agent_type}")

    def health_check(self, image: str) -> HealthCheckResult:
        """One-shot agent+model probe, run before any eval.

        A model-backend failure (bad model name, missing/quota'd creds, a
        provider 'Unexpected server error') is returned as unhealthy rather
        than raised, so the engine can mark the agent UNHEALTHY and skip it
        without scoring garbage. True infra failures (image missing,
        provisioning raise, in-container crash, timeout) propagate as
        RuntimeError/TimeoutError so the agent is marked FAILED instead —
        those are harness problems, not 'the model is down today'.

        The verdict is read from markers on stdout, not the process exit
        code: agent CLIs (opencode especially) print an error and exit 0 on
        a provider failure, so the script below always exits 0 once it has a
        verdict and only the `timeout` wrapper / a real crash leave non-zero.
        """
        script = (
            "import asyncio, os\n"
            "from agent_shell.shell import AgentShell\n"
            "from agent_shell.models.agent import AgentType\n"
            "\n"
            "async def _main():\n"
            "    shell = AgentShell(agent_type=AgentType(os.environ['AGENT_TYPE']))\n"
            "    try:\n"
            "        r = await shell.health_check(cwd='/tmp', model=os.environ['AGENT_MODEL'],\n"
            "                                  timeout=float(os.environ.get('HEALTH_CHECK_TIMEOUT_SECONDS', '60')))\n"
            "    except Exception as e:\n"
            "        print('HEALTHY=False')\n"
            "        print(f'EXCEPTION={type(e).__name__}: {e}')\n"
            "        return\n"
            "    print(f'HEALTHY={r.healthy}')\n"
            "    if not r.healthy:\n"
            "        print(f\"EXCEPTION={r.exception or ''}\")\n"
            "\n"
            "asyncio.run(_main())\n"
        )

        client = docker.from_env()
        prov = self._provision_agent()  # raises on missing creds -> FAILED
        effort_suffix = f"_{self._agent_effort}" if self._agent_effort else ""
        container_name = safe_name(
            f"eval_harness_health_{self._agent_type.value}_{self._agent_model}{effort_suffix}"
        )
        try:
            client.containers.get(container_name).remove(force=True)
        except docker.errors.NotFound:
            pass

        labels = {}
        if self._session_id is not None:
            labels[_SESSION_LABEL] = str(self._session_id)

        container = client.containers.run(
            image=image,
            command=["sleep", "infinity"],
            volumes=prov.volumes,
            environment={
                "AGENT_TYPE": self._agent_type.value,
                "AGENT_MODEL": self._agent_model,
                "AGENT_EFFORT": self._agent_effort or "",
                "HEALTH_CHECK_TIMEOUT_SECONDS": str(settings.HEALTH_CHECK_TIMEOUT_SECONDS),
                **prov.environment,
            },
            detach=True,
            name=container_name,
            labels=labels,
        )

        try:
            timeout_seconds = settings.HEALTH_CHECK_TIMEOUT_SECONDS
            # `timeout` enforces the wall clock in-container; exec_run blocks
            # until the exec finishes so no client-side streaming loop needed.
            cmd = [
                "timeout",
                "--kill-after=10s",
                str(timeout_seconds),
                "python",
                "-u",
                "-c",
                script,
            ]
            exit_code, output = container.exec_run(cmd)
            buffer = (
                output.decode(errors="replace") if isinstance(output, bytes) else (output or "")
            )
        finally:
            try:
                container.stop(timeout=5)
                container.remove()
            except docker.errors.NotFound:
                pass
            # probe is a throwaway DockerRunner; clean its staged credential
            # copies so an unhealthy probe doesn't leak secrets on the host.
            for d in self._temp_dirs:
                shutil.rmtree(d, ignore_errors=True)
            self._temp_dirs.clear()

        self._log.info(f"[health] {buffer.strip()}")

        if exit_code in (124, 137):
            raise TimeoutError(f"health timed out after {timeout_seconds}s")
        if exit_code != 0:
            raise RuntimeError(f"health crashed (exit {exit_code})\n{buffer}")

        healthy = exception = None
        for line in buffer.splitlines():
            if line.startswith("HEALTHY="):
                healthy = line.removeprefix("HEALTHY=").strip() == "True"
            elif line.startswith("EXCEPTION=") and exception is None:
                exception = line.removeprefix("EXCEPTION=").strip() or None
        return HealthCheckResult(
            healthy=healthy or False,
            exception=exception or "health check produced no HEALTHY= marker",
        )

    def docker_run(
        self,
        arrange_script: str,
        act_script: str,
        score_script: str,
        image: str,
    ) -> DockerRunResult:

        client = docker.from_env()
        prov = self._provision_agent()
        container = None

        score = 0.0
        total_tokens = 0
        time_start = time.time()
        effort_suffix = f"_{self._agent_effort}" if self._agent_effort else ""
        container_name = safe_name(
            f"eval_harness_{self._agent_type.value}_{self._agent_model}{effort_suffix}"
        )

        try:
            client.containers.get(container_name).remove(force=True)
        except docker.errors.NotFound:
            pass

        labels = {}
        if self._session_id is not None:
            labels[_SESSION_LABEL] = str(self._session_id)

        try:
            container = client.containers.run(
                image=image,
                command=["sleep", "infinity"],
                volumes=prov.volumes,
                environment={
                    "AGENT_TYPE": self._agent_type.value,
                    "AGENT_MODEL": self._agent_model,
                    "AGENT_EFFORT": self._agent_effort or "",
                    **({"GH_TOKEN": settings.GITHUB_TOKEN} if settings.GITHUB_TOKEN else {}),
                    **prov.environment,
                },
                detach=True,
                name=container_name,
                labels=labels,
            )

            phase_timeouts = {
                "arrange": settings.ARRANGE_TIMEOUT_SECONDS,
                "act": settings.ACT_TIMEOUT_SECONDS,
                "score": settings.SCORE_TIMEOUT_SECONDS,
            }

            for label, script in [
                ("arrange", arrange_script),
                ("act", act_script),
                ("score", score_script),
            ]:
                timeout_seconds = phase_timeouts[label]
                # future_me: -u to ensure stdout/stderr unbffered
                cmd = [
                    "timeout",
                    "--kill-after=30s",
                    str(timeout_seconds),
                    "python",
                    "-u",
                    "-c",
                    script,
                ]
                exec_id = client.api.exec_create(container.id, cmd)["Id"]
                self._log.info(f"--- {label} phase ---")
                self._log.info("container started")
                stream = client.api.exec_start(exec_id, stream=True)

                buffer = ""
                pending = ""
                try:
                    for chunk in stream:
                        text = chunk.decode(errors="replace")
                        buffer += text
                        pending += text
                        while "\n" in pending:
                            line, pending = pending.split("\n", 1)
                            self._log.info(f"[{label}] {line}")
                    if pending.strip():
                        self._log.info(f"[{label}] {pending}")
                except Exception as e:
                    self._log.error(f"Error streaming docker response: {e}")
                finally:
                    stream._response.close()

                exit_code = client.api.exec_inspect(exec_id)["ExitCode"]

                if exit_code in (124, 137):
                    self._log.error(f"{label} timed out after {timeout_seconds}s")
                    raise TimeoutError(f"{label} timed out after {timeout_seconds}s")

                if exit_code != 0:
                    self._log.error(
                        f"{label} failed (exit {exit_code})\n"
                        f"--- container output ---\n{buffer}\n"
                        f"--- end container output ---"
                    )
                    raise RuntimeError(f"{label} failed (exit {exit_code})")

                total_tokens += _parse_total_tokens(buffer, self._log)

                if label == "score":
                    for line in reversed(buffer.splitlines()):
                        if line.startswith("EVAL_SCORE="):
                            raw = line.removeprefix("EVAL_SCORE=")
                            try:
                                score = float(raw)
                            except ValueError as e:
                                raise RuntimeError(
                                    f"Malformed score line {line!r}: expected EVAL_SCORE=<float>"
                                ) from e
                            self._log.info(f"Eval Score {score}")
                            break

                self._log.info(f"phase {label} completed")

        finally:
            if container is not None:
                try:
                    container.stop(timeout=5)
                    container.remove()
                except docker.errors.NotFound:
                    pass
            # Delete the throwaway staging dirs (credentials + config copies).
            # The repo's version-controlled config is the source, never these.
            for tmp_dir in self._temp_dirs:
                shutil.rmtree(tmp_dir, ignore_errors=True)
        time_taken = time.time() - time_start

        return DockerRunResult(
            score=score,
            time_taken_seconds=time_taken,
            total_tokens=total_tokens,
        )
