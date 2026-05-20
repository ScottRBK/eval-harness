import tempfile, os, shutil
from pathlib import Path 
import docker 

from agent_shell.models.agent import AgentType


class DockerRunner:


    def __init__(self, agent_type: AgentType, agent_model: str):
        self._agent_type = agent_type
        self._agent_model = agent_model

    def _setup_claude_volumes(self) -> dict[str, dict[str, str]]:
        host_claude = Path.home() / ".claude"
        tmp_claude = Path(tempfile.mkdtemp(prefix="eval-claude-"))
        shutil.copy2(host_claude / ".credentials.json", tmp_claude / ".credentials.json")
        os.chmod(tmp_claude / ".credentials.json", 0o644)

        return {str(tmp_claude): {"bind": "/home/node/.claude", "mode": "rw"}}


    def _setup_opencode_volumes(self) -> dict[str, dict[str, str]]:
        host_opencode = Path.home() / ".local" / "share" / "opencode"
        tmp_opencode = Path(tempfile.mkdtemp(prefix="eval-opencode-"))
        shutil.copy2(host_opencode / "auth.json", tmp_opencode / "auth.json")
        os.chmod(tmp_opencode / "auth.json", 0o644)

        return {str(tmp_opencode): {"bind": "/home/node/.local/share/opencode", "mode": "rw"}}


    def _set_up_agent_volumes(self) -> dict[str, dict[str, str]]:
        match self._agent_type:
            case AgentType.CLAUDE_CODE:
                return self._setup_claude_volumes()
            case AgentType.OPENCODE:
                return self._setup_opencode_volumes()
            case _:
                raise NotImplementedError(f"Credential setup not implemented for {self._agent_type}")


    def docker_run(self,
            arrange_script: str,
            act_script: str,
            score_script: str,
    ) -> float:

        client = docker.from_env()
        volumes = self._set_up_agent_volumes()
        container = None

        score = 1.0

        try:
            container = client.containers.run(
                image="eval-harness:latest",
                command=["sleep", "infinity"],
                volumes=volumes,
                environment={
                    "AGENT_TYPE": self._agent_type.value,
                    "AGENT_MODEL": self._agent_model,
                },
                detach=True,
            )

            for label, script in [
                ("arrange", arrange_script),
                ("act", act_script),
                ("score", score_script),
            ]:
                result = container.exec_run(["python", "-c", script])
                output = result.output.decode()
                print(f"--- {label} ---\n{output}")
                if result.exit_code != 0:
                    raise RuntimeError(f"{label} failed (exit {result.exit_code})")

                if label == "score":
                    score = float(output.strip().splitlines()[-1])

        finally:
            if container is not None:
                try:
                    container.stop(timeout=5)
                    container.remove()
                except docker.errors.NotFound:
                    pass
            for host_path in volumes:
                shutil.rmtree(host_path)

        return score 


