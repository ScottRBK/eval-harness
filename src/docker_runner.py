import tempfile, os, shutil
import docker
import time
import logging 
from pathlib import Path
from agent_shell.models.agent import AgentType

from src.models import AgentProvisioning
from src.config.settings import settings

# Harness-owned agent config, version-controlled. Mounted read-only into the
# container so runs are reproducible and independent of the host's own config.
CONFIG_ROOT = Path(__file__).parent / "docker" / "configs"


class DockerRunner:


    def __init__(self, agent_type: AgentType, agent_model: str, logger: logging.Logger | None = None):
        self._agent_type = agent_type
        self._agent_model = agent_model
        # Per-agent logger when the engine injects one; module logger otherwise.
        self._log = logger or logging.getLogger(__name__)
        # Throwaway dirs we create for credentials; deleted after the run.
        self._temp_dirs: list[Path] = []

    def _staged_mount(
        self, files: list[Path], container_dir: str
    ) -> dict[str, dict[str, str]]:
        """Copy files into a throwaway dir and bind that dir read-write.

        The agent - and agent_shell, which rewrites opencode.json to inject MCP
        servers - can mutate the mounted files freely. The originals (host
        secrets and the version-controlled repo config) are copies, so they are
        never touched. The temp dir is tracked so the run can delete it after.
        """
        staging = Path(tempfile.mkdtemp(prefix="eval-mount-"))
        for source in files:
            shutil.copy2(source, staging / source.name)
            os.chmod(staging / source.name, 0o644)
        self._temp_dirs.append(staging)

        return {str(staging): {"bind": container_dir, "mode": "rw"}}


    def _setup_claude_code(self) -> AgentProvisioning:
        if not settings.CLAUDE_CODE_OAUTH_TOKEN:
            raise RuntimeError("CLAUDE_CODE_OAUTH_TOKEN not configured (run `claude setup-token` and set env var)")
        return AgentProvisioning(environment={"CLAUDE_CODE_OAUTH_TOKEN": settings.CLAUDE_CODE_OAUTH_TOKEN})

    def _setup_opencode(self) -> AgentProvisioning:
        return AgentProvisioning(volumes=self._setup_opencode_volumes())

    def _setup_opencode_volumes(self) -> dict[str, dict[str, str]]:
        credentials = self._staged_mount(
            [Path(settings.OPENCODE_CREDENTIALS_LOC).expanduser()],
            "/home/node/.local/share/opencode",
        )
        config = self._staged_mount(
            [CONFIG_ROOT / "opencode" / "opencode.json"],
            "/home/node/.config/opencode",
        )

        return credentials | config


    def _provision_agent(self) -> AgentProvisioning:
        match self._agent_type:
            case AgentType.CLAUDE_CODE:
                return self._setup_claude_code() 
            case AgentType.OPENCODE:
                return self._setup_opencode() 
            case _:
                raise NotImplementedError(f"Agent not implemented for {self._agent_type}")


    def docker_run(self,
            arrange_script: str,
            act_script: str,
            score_script: str,
            image: str,
   ) -> tuple[float, float]:

        client = docker.from_env()
        prov = self._provision_agent()
        container = None

        score = 0.0
        time_start = time.time()

        try:
            client.containers.get("eval_harness").remove(force=True)
        except docker.errors.NotFound:
            pass

        try:
            container = client.containers.run(
                image=image,
                command=["sleep", "infinity"],
                volumes=prov.volumes,
                environment={
                    "AGENT_TYPE": self._agent_type.value,
                    "AGENT_MODEL": self._agent_model,
                    **prov.environment,
                },
                detach=True,
                name=f"eval_harness_{self._agent_type.value}_{self._agent_model}",
            )

            for label, script in [
                ("arrange", arrange_script),
                ("act", act_script),
                ("score", score_script),
            ]:
                cmd = ["python", "-u","-c", script] # future_me: -u to ensure stdout/stderr unbffered
                exec_id = client.api.exec_create(container.id, cmd)["Id"]
                buffer = ""
                self._log.info(f"--- {label} phase ---")
                self._log.info("container started")
                stream = client.api.exec_start(exec_id, stream=True)

                try:
                    for chunk in stream:
                        text = chunk.decode(errors="replace")
                        #TODO: Need to implement console output inside the live display ... well maybe
                        buffer += text
                except Exception as e:
                    self._log.error(f"Error streaming docker response: {e}")
                finally:
                    stream._response.close()

                exit_code = client.api.exec_inspect(exec_id)["ExitCode"]

                if exit_code != 0:
                    self._log.error(f"{label} failed (exit {exit_code})")
                    raise RuntimeError(f"{label} failed (exit {exit_code})")

                self._log.debug(f"docker output: {buffer}")

                if label == "score":
                    for line in reversed(buffer.splitlines()):
                        if line.startswith("EVAL_SCORE="):
                            raw = line.removeprefix("EVAL_SCORE=")
                            try:
                                score = float(raw)
                            except ValueError as e:
                                raise RuntimeError(f"Malformed score line {line!r}: "
                                    "expected EVAL_SCORE=<float>"
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

        return (score, time_taken) 


