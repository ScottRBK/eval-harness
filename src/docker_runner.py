import tempfile
import os
import shutil
import json
import docker
import time
import logging
from pathlib import Path
from agent_shell.models.agent import AgentType, HealthCheckResult

from uuid import UUID

from src.models import AgentProvisioning, CapabilityProfile, DockerRunResult
from src.config.settings import settings
from src.failure_diagnostics import (
    TRACE_ENV,
    TRACE_PATH,
    capture_failure_diagnostics,
)
from src.helpers.naming import agent_identity, safe_name
from src.helpers.redaction import redact_secrets

_SESSION_LABEL = "com.eval-harness.session"
_TOKEN_MARKER = "EVAL_TOTAL_TOKENS="
_AGENT_SHELL_ISOLATION_ENV = "AGENTSHELL_ISOLATION_POLICY"
_PID_NAMESPACE_ISOLATION = "linux-pid-namespace"
_CAPABILITY_SPEC_PATH = "/tmp/eval-harness-capabilities.json"  # noqa: S108 - container path
_CAPABILITY_TIMEOUT_ENV = "CAPABILITY_SETUP_TIMEOUT_SECONDS"
_CONTAINER_NODE_UID = 1000


def _agent_isolation_environment() -> dict[str, str]:
    if not settings.AGENT_PID_NAMESPACE_ISOLATION:
        return {}
    return {_AGENT_SHELL_ISOLATION_ENV: _PID_NAMESPACE_ISOLATION}


def _agent_isolation_container_options() -> dict[str, list[str]]:
    if not settings.AGENT_PID_NAMESPACE_ISOLATION:
        return {}
    return {"security_opt": ["seccomp=unconfined"]}


# Harness-owned agent config, version-controlled. Mounted read-only into the
# container so runs are reproducible and independent of the host's own config.
CONFIG_ROOT = Path(__file__).parent / "docker" / "configs"


def _log_build_events(events, log: logging.Logger, level: int) -> None:
    for event in events:
        message = event.get("stream") or event.get("error") or event.get("status") or ""
        if message := message.strip():
            log.log(level, "[docker build] %s", message)


def build_image(dockerfile: Path, tag: str, log: logging.Logger) -> str:
    """Build an eval-owned image using the Dockerfile's directory as its context."""
    client = docker.from_env()
    log.info("Building eval image %s from %s", tag, dockerfile)
    try:
        _image, build_log = client.images.build(
            path=str(dockerfile.parent),
            dockerfile=dockerfile.name,
            tag=tag,
            rm=True,
            forcerm=True,
        )
    except docker.errors.BuildError as exc:
        _log_build_events(exc.build_log, log, logging.ERROR)
        raise
    _log_build_events(build_log, log, logging.INFO)
    return tag


def _parse_total_tokens(
    buffer: str,
    log: logging.Logger,
    redactions: tuple[str, ...] = (),
) -> int:
    total_tokens = 0
    for line in buffer.splitlines():
        if not line.startswith(_TOKEN_MARKER):
            continue
        raw = line.removeprefix(_TOKEN_MARKER).strip()
        try:
            total_tokens += int(raw)
        except ValueError:
            log.warning(
                "Ignoring malformed token marker line: %r",
                redact_secrets(line, redactions),
            )
    return total_tokens


def _capability_setup_script() -> str:
    """Build a setup script that reads its profile from a private container file."""
    return (
        "import asyncio\n"
        "import json\n"
        "import os\n"
        "import time\n"
        "from pathlib import Path\n"
        "from agent_shell.models.agent import (\n"
        "    AgentType,\n"
        "    MCPServerSpec,\n"
        "    MCPServerType,\n"
        "    PackageSpec,\n"
        ")\n"
        "from agent_shell.shell import AgentShell\n"
        f"CAPABILITY_SPEC_PATH = {_CAPABILITY_SPEC_PATH!r}\n"
        "\n"
        "async def _main():\n"
        "    spec_path = Path(CAPABILITY_SPEC_PATH)\n"
        "    data = json.loads(spec_path.read_text(encoding='utf-8'))\n"
        "    spec_path.write_text('{}', encoding='utf-8')\n"
        "    packages = data['packages']\n"
        "    mcp_servers = data['mcp_servers']\n"
        f"    deadline = time.monotonic() + float(os.environ[{_CAPABILITY_TIMEOUT_ENV!r}])\n"
        "    shell = AgentShell(agent_type=AgentType(os.environ['AGENT_TYPE']))\n"
        "    for source in packages:\n"
        "        remaining = deadline - time.monotonic()\n"
        "        if remaining <= 0:\n"
        "            raise TimeoutError('capability setup budget exhausted')\n"
        "        await shell.add_package(PackageSpec(source=source), timeout=remaining)\n"
        "    for raw in mcp_servers:\n"
        "        spec = dict(raw)\n"
        "        spec['type'] = MCPServerType(spec['type'])\n"
        "        await shell.add_mcp_server(MCPServerSpec(**spec))\n"
        "    if mcp_servers:\n"
        "        configured_names = {server.name for server in await shell.list_mcp_servers()}\n"
        "        requested_names = {server['name'] for server in mcp_servers}\n"
        "        missing = requested_names - configured_names\n"
        "        if missing:\n"
        "            raise RuntimeError(f'MCP registration missing: {sorted(missing)!r}')\n"
        "    print(\n"
        "        f'capabilities configured: {len(packages)} package(s), '\n"
        "        f'{len(mcp_servers)} MCP server(s)'\n"
        "    )\n"
        "\n"
        "asyncio.run(_main())\n"
    )


class DockerRunner:
    def __init__(
        self,
        agent_type: AgentType,
        agent_model: str,
        agent_effort: str | None = None,
        logger: logging.Logger | None = None,
        session_id: UUID | None = None,
        diagnostics_dir: Path | None = None,
        agent_variant: str | None = None,
        capability_profile: CapabilityProfile | None = None,
    ):
        self._agent_type = agent_type
        self._agent_model = agent_model
        self._agent_effort = agent_effort
        self._agent_variant = agent_variant
        self._capability_profile = capability_profile
        # Per-agent logger when the engine injects one; module logger otherwise.
        self._log = logger or logging.getLogger(__name__)
        # Throwaway dirs we create for credentials; deleted after the run.
        self._temp_dirs: list[Path] = []
        self._session_id = session_id
        self._diagnostics_dir = diagnostics_dir

    def _identity(self) -> str:
        return agent_identity(
            self._agent_type,
            self._agent_model,
            self._agent_effort,
            self._agent_variant,
        )

    def _container_name(self, prefix: str) -> str:
        session_suffix = f"_{self._session_id}" if self._session_id is not None else ""
        return safe_name(f"{prefix}_{self._identity()}{session_suffix}")

    def _capability_secrets(self) -> tuple[str, ...]:
        if self._capability_profile is None:
            return ()
        return self._capability_profile.redaction_values()

    @staticmethod
    def _ensure_private_mount_uid() -> None:
        """Fail clearly rather than bind private files unreadable by container user node."""
        getuid = getattr(os, "getuid", None)
        if getuid is not None and getuid() != _CONTAINER_NODE_UID:
            raise RuntimeError(
                "Private Docker mounts require host UID "
                f"{_CONTAINER_NODE_UID}, matching the image's node user"
            )

    def _stage_capability_profile(self) -> dict[str, dict[str, str]]:
        if self._capability_profile is None or self._capability_profile.is_empty:
            return {}
        self._ensure_private_mount_uid()
        staging = Path(tempfile.mkdtemp(prefix="eval-capabilities-"))
        self._temp_dirs.append(staging)
        os.chmod(staging, 0o700)
        spec = staging / "capabilities.json"
        spec.write_text(
            json.dumps(
                {
                    "packages": list(self._capability_profile.packages),
                    "mcp_servers": list(self._capability_profile.mcp_servers),
                }
            ),
            encoding="utf-8",
        )
        os.chmod(spec, 0o600)
        return {str(spec): {"bind": _CAPABILITY_SPEC_PATH, "mode": "rw"}}

    def _staged_mount(self, files: list[Path], container_dir: str) -> dict[str, dict[str, str]]:
        """Copy files into a throwaway dir and bind that dir read-write.

        The agent - and agent_shell, which rewrites opencode.json to inject MCP
        servers - can mutate the mounted files freely. The originals (host
        secrets and the version-controlled repo config) are copies, so they are
        never touched. The temp dir is tracked so the run can delete it after.
        """
        self._ensure_private_mount_uid()
        staging = Path(tempfile.mkdtemp(prefix="eval-mount-"))
        self._temp_dirs.append(staging)
        # The base image runs as the same UID as the host user. Keep staged
        # credentials/configuration private while still allowing that user to read them.
        os.chmod(staging, 0o700)
        for source in files:
            shutil.copy2(source, staging / source.name)
            os.chmod(staging / source.name, 0o600)

        return {str(staging): {"bind": container_dir, "mode": "rw"}}

    def _staged_file_mounts(
        self,
        files: list[Path],
        container_dir: str,
        target_names: list[str] | None = None,
    ) -> dict[str, dict[str, str]]:
        """Bind individual files so image-provided sibling files remain visible."""
        if target_names is not None and len(target_names) != len(files):
            raise ValueError("target_names must match files")
        self._ensure_private_mount_uid()
        staging = Path(tempfile.mkdtemp(prefix="eval-mount-"))
        self._temp_dirs.append(staging)
        os.chmod(staging, 0o700)
        mounts = {}
        for index, source in enumerate(files):
            staged = staging / source.name
            shutil.copy2(source, staged)
            os.chmod(staged, 0o600)
            target_name = target_names[index] if target_names is not None else source.name
            target = f"{container_dir.rstrip('/')}/{target_name}"
            mounts[str(staged)] = {"bind": target, "mode": "rw"}
        return mounts

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
        agent_dir = auth.parent
        files = [auth]
        for name in ("models.json", "models-store.json"):
            candidate = agent_dir / name
            if candidate.is_file():
                files.append(candidate)
        return AgentProvisioning(volumes=self._staged_file_mounts(files, "/home/node/.pi/agent"))

    def _setup_grok(self) -> AgentProvisioning:
        # Grok's installer puts the binary at ~/.grok/bin. Stage auth as a *file*
        # bind so we do not shadow that directory (a dir mount would hide `grok`).
        auth = Path(settings.GROK_CREDENTIALS_LOC).expanduser()
        if not auth.exists():
            raise RuntimeError(f"Grok auth file not found at {auth} (run `grok login` on the host)")
        return AgentProvisioning(
            volumes=self._staged_file_mounts([auth], "/home/node/.grok", target_names=["auth.json"])
        )

    def _setup_cursor(self) -> AgentProvisioning:
        # Cursor accepts either an API key or an OAuth access token from `cursor-agent login`.
        environment = {}
        if settings.CURSOR_API_KEY:
            environment["CURSOR_API_KEY"] = settings.CURSOR_API_KEY
        if settings.CURSOR_AUTH_TOKEN:
            environment["CURSOR_AUTH_TOKEN"] = settings.CURSOR_AUTH_TOKEN
        if not environment:
            raise RuntimeError(
                "Cursor credentials not configured (set EVAL_HARNESS_CURSOR_API_KEY "
                "or EVAL_HARNESS_CURSOR_AUTH_TOKEN)"
            )
        return AgentProvisioning(environment=environment)

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
            case AgentType.GROK:
                return self._setup_grok()
            case AgentType.CURSOR:
                return self._setup_cursor()
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
        container = None
        container_name = self._container_name("eval_harness_health")
        timeout_seconds = settings.HEALTH_CHECK_TIMEOUT_SECONDS
        try:
            prov = self._provision_agent()  # raises on missing creds -> FAILED
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
                    "HEALTH_CHECK_TIMEOUT_SECONDS": str(timeout_seconds),
                    **prov.environment,
                    **_agent_isolation_environment(),
                },
                **_agent_isolation_container_options(),
                detach=True,
                name=container_name,
                labels=labels,
            )

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
            if container is not None:
                try:
                    container.stop(timeout=5)
                except docker.errors.NotFound:
                    pass
                except Exception as cleanup_error:
                    self._log.warning(
                        "Docker health-check stop failed: %s",
                        redact_secrets(str(cleanup_error), self._capability_secrets()),
                    )
                try:
                    container.remove(force=True)
                except docker.errors.NotFound:
                    pass
                except Exception as cleanup_error:
                    self._log.warning(
                        "Docker health-check remove failed: %s",
                        redact_secrets(str(cleanup_error), self._capability_secrets()),
                    )
            else:
                try:
                    orphan = client.containers.get(container_name)
                except docker.errors.NotFound:
                    orphan = None
                except Exception as cleanup_error:
                    self._log.warning(
                        "Docker health-check orphan lookup failed: %s",
                        redact_secrets(str(cleanup_error), self._capability_secrets()),
                    )
                    orphan = None
                if orphan is not None:
                    try:
                        orphan.remove(force=True)
                    except docker.errors.NotFound:
                        pass
                    except Exception as cleanup_error:
                        self._log.warning(
                            "Docker health-check orphan removal failed: %s",
                            redact_secrets(str(cleanup_error), self._capability_secrets()),
                        )
            # probe is a throwaway DockerRunner; clean its staged credential
            # copies so an unhealthy probe doesn't leak secrets on the host.
            for d in self._temp_dirs:
                shutil.rmtree(d, ignore_errors=True)

        safe_buffer = redact_secrets(buffer, self._capability_secrets())
        self._log.info(f"[health] {safe_buffer.strip()}")

        if exit_code in (124, 137):
            raise TimeoutError(f"health timed out after {timeout_seconds}s")
        if exit_code != 0:
            raise RuntimeError(f"health crashed (exit {exit_code})\n{safe_buffer}")

        healthy = exception = None
        for line in safe_buffer.splitlines():
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

        client = None
        container = None
        failure: BaseException | None = None
        phase = "provisioning"
        exit_code: int | None = None
        timed_out = False

        score = 0.0
        total_tokens = 0
        time_start = 0.0
        container_name = self._container_name("eval_harness")

        try:
            client = docker.from_env()
            prov = self._provision_agent()
            prov.volumes.update(self._stage_capability_profile())
            time_start = time.time()
            phase = "container"

            try:
                client.containers.get(container_name).remove(force=True)
            except docker.errors.NotFound:
                pass

            labels = {}
            if self._session_id is not None:
                labels[_SESSION_LABEL] = str(self._session_id)

            environment = {
                "AGENT_TYPE": self._agent_type.value,
                "AGENT_MODEL": self._agent_model,
                "AGENT_EFFORT": self._agent_effort or "",
                "CAPABILITY_SETUP_TIMEOUT_SECONDS": str(settings.CAPABILITY_SETUP_TIMEOUT_SECONDS),
                **({"GH_TOKEN": settings.GITHUB_TOKEN} if settings.GITHUB_TOKEN else {}),
                **({"ADO_PAT": settings.AZURE_DEVOPS_PAT} if settings.AZURE_DEVOPS_PAT else {}),
                **prov.environment,
                **_agent_isolation_environment(),
            }
            if settings.CAPTURE_FAILURE_DIAGNOSTICS:
                environment[TRACE_ENV] = TRACE_PATH

            container = client.containers.run(
                image=image,
                command=["sleep", "infinity"],
                volumes=prov.volumes,
                environment=environment,
                **_agent_isolation_container_options(),
                detach=True,
                name=container_name,
                labels=labels,
            )

            phase_timeouts = {
                "capabilities": settings.CAPABILITY_SETUP_TIMEOUT_SECONDS,
                "arrange": settings.ARRANGE_TIMEOUT_SECONDS,
                "act": settings.ACT_TIMEOUT_SECONDS,
                "score": settings.SCORE_TIMEOUT_SECONDS,
            }
            phase_scripts = [
                ("arrange", arrange_script),
                ("act", act_script),
                ("score", score_script),
            ]
            if self._capability_profile and not self._capability_profile.is_empty:
                phase_scripts.insert(
                    0,
                    ("capabilities", _capability_setup_script()),
                )

            for label, script in phase_scripts:
                phase = label
                exit_code = None
                timed_out = False
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
                            self._log.info(
                                f"[{label}] {redact_secrets(line, self._capability_secrets())}"
                            )
                    if pending.strip():
                        self._log.info(
                            f"[{label}] {redact_secrets(pending, self._capability_secrets())}"
                        )
                except Exception as e:
                    self._log.error(
                        "Error streaming docker response: %s",
                        redact_secrets(str(e), self._capability_secrets()),
                    )
                finally:
                    stream._response.close()

                exit_code = client.api.exec_inspect(exec_id)["ExitCode"]

                if exit_code in (124, 137):
                    timed_out = True
                    self._log.error(f"{label} timed out after {timeout_seconds}s")
                    raise TimeoutError(f"{label} timed out after {timeout_seconds}s")

                if exit_code != 0:
                    safe_buffer = redact_secrets(buffer, self._capability_secrets())
                    self._log.error(
                        f"{label} failed (exit {exit_code})\n"
                        f"--- container output ---\n{safe_buffer}\n"
                        f"--- end container output ---"
                    )
                    raise RuntimeError(f"{label} failed (exit {exit_code})")

                total_tokens += _parse_total_tokens(
                    buffer,
                    self._log,
                    self._capability_secrets(),
                )

                if label == "score":
                    for line in reversed(buffer.splitlines()):
                        if line.startswith("EVAL_SCORE="):
                            raw = line.removeprefix("EVAL_SCORE=")
                            try:
                                score = float(raw)
                            except ValueError as e:
                                safe_line = redact_secrets(line, self._capability_secrets())
                                raise RuntimeError(
                                    f"Malformed score line {safe_line!r}: "
                                    "expected EVAL_SCORE=<float>"
                                ) from e
                            self._log.info(f"Eval Score {score}")
                            break

                self._log.info(f"phase {label} completed")

        except BaseException as error:
            failure = error
            raise
        finally:
            if failure is not None and settings.CAPTURE_FAILURE_DIAGNOSTICS:
                try:
                    capture_failure_diagnostics(
                        attempt_dir=self._diagnostics_dir,
                        phase=phase,
                        error=failure,
                        exit_code=exit_code,
                        timed_out=timed_out,
                        container=container,
                        log=self._log,
                        redactions=self._capability_secrets(),
                    )
                except BaseException as capture_error:
                    self._log.warning(
                        "Failure diagnostics could not be captured: %s",
                        redact_secrets(str(capture_error), self._capability_secrets()),
                    )

            if container is not None:
                try:
                    container.stop(timeout=5)
                except docker.errors.NotFound:
                    pass
                except Exception as cleanup_error:
                    self._log.warning(
                        "Docker container stop failed: %s",
                        redact_secrets(str(cleanup_error), self._capability_secrets()),
                    )
                try:
                    container.remove(force=True)
                except docker.errors.NotFound:
                    pass
                except Exception as cleanup_error:
                    # Never replace the eval failure (or a successful score) with
                    # a teardown error, but do leave an operator-visible warning.
                    self._log.warning(
                        "Docker container remove failed: %s",
                        redact_secrets(str(cleanup_error), self._capability_secrets()),
                    )
            elif client is not None:
                try:
                    orphan = client.containers.get(container_name)
                except docker.errors.NotFound:
                    orphan = None
                except Exception as cleanup_error:
                    self._log.warning(
                        "Docker orphan lookup failed: %s",
                        redact_secrets(str(cleanup_error), self._capability_secrets()),
                    )
                    orphan = None
                if orphan is not None:
                    try:
                        orphan.remove(force=True)
                    except docker.errors.NotFound:
                        pass
                    except Exception as cleanup_error:
                        self._log.warning(
                            "Docker orphan removal failed: %s",
                            redact_secrets(str(cleanup_error), self._capability_secrets()),
                        )
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
