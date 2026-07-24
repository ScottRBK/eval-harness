"""Integration tests for eval-engine method extraction into real Docker runs."""

from queue import Queue
from uuid import uuid4

import docker
import pytest
from agent_shell.models.agent import AgentType, HealthCheckResult

from src.evals_engine import run_agent
from src.models import (
    AgentConfig,
    AgentEvalExecution,
    AgentEvalStatus,
    Eval,
    EvalExecution,
)

pytestmark = pytest.mark.integration


IMAGE = "eval-harness:latest"
BUILD_COMMAND = "docker build -t eval-harness:latest -f src/docker/Dockerfile src/docker/"


EVAL_SOURCE = r"""
class IntegrationEval:
    image = "eval-harness:latest"
    score_embedded_values = {
        "EXPECTED_CONTENTS": "arrange\nact\n",
    }

    async def arrange(self):
        from pathlib import Path
        Path("/workspace/engine-marker.txt").write_text("arrange\n")
        print("arranged by eval engine")

    async def act(self):
        from pathlib import Path
        path = Path("/workspace/engine-marker.txt")
        path.write_text(path.read_text() + "act\n")
        print("acted by eval engine")

    async def score(self):
        from pathlib import Path
        contents = Path("/workspace/engine-marker.txt").read_text()
        assert contents == EXPECTED_CONTENTS
        print("EVAL_TOTAL_TOKENS=13")
        print("EVAL_SCORE=0.625")
"""


FIXTURE_IMAGE_EVAL_SOURCE = r"""
class FixtureImageEval:
    dockerfile = "fixtures/image/Dockerfile"

    async def arrange(self):
        from pathlib import Path
        assert Path("/fixture-image-marker").read_text().strip() == "fixture image"
        assert Path("/fixture-visible.txt").read_text().strip() == "visible"
        assert not Path("/fixture-hidden.txt").exists()

    async def act(self):
        pass

    async def score(self):
        print("EVAL_SCORE=1.0")
"""

FIXTURE_DOCKERFILE = """\
FROM eval-harness:latest
USER root
RUN printf 'fixture image\\n' > /fixture-image-marker
COPY visible.txt /fixture-visible.txt
USER node
"""


def test_run_agent_extracts_eval_methods_and_runs_them_in_real_container(
    tmp_path,
    monkeypatch,
    require_docker_image,
    fake_claude_token,
    assert_container_removed,
):
    # Arrange
    require_docker_image(IMAGE, BUILD_COMMAND)
    eval_dir = tmp_path / "integration_eval"
    eval_dir.mkdir()
    (eval_dir / "eval.py").write_text(EVAL_SOURCE)
    monkeypatch.setattr("src.evals_engine.settings.EVALS_DIRS", str(tmp_path))
    monkeypatch.setattr(
        "src.evals_engine.DockerRunner.health_check",
        lambda self, image: HealthCheckResult(healthy=True),
    )

    agent_config = AgentConfig(
        agent_type=AgentType.CLAUDE_CODE,
        agent_model="engine-integration",
    )
    eval_config = Eval(
        number=1,
        eval_dir="integration_eval",
        description="Tiny integration eval",
        run_count=1,
        tags=[],
    )
    eval_execution = EvalExecution(
        id=uuid4(),
        eval=eval_config,
        agent_config=agent_config,
    )
    agent_execution = AgentEvalExecution(
        agent_config=agent_config,
        total_score=0,
        total_tokens=0,
        total_time_taken_seconds=0,
        evals_executions=[eval_execution],
        status=AgentEvalStatus.PENDING,
    )

    # Act
    run_agent(agent_execution, Queue())

    # Assert
    assert agent_execution.status == AgentEvalStatus.COMPLETED
    assert agent_execution.total_score == pytest.approx(0.625)
    assert agent_execution.total_tokens == 13
    assert agent_execution.total_time_taken_seconds > 0
    assert eval_execution.score == pytest.approx(0.625)
    assert eval_execution.total_tokens == 13
    assert eval_execution.time_taken_seconds > 0
    assert eval_execution.date_executed is not None
    assert_container_removed("eval_harness_claude_code_engine-integration")


def test_run_agent_builds_and_uses_eval_fixture_dockerfile(
    tmp_path,
    monkeypatch,
    require_docker_image,
    docker_client,
    fake_claude_token,
    assert_container_removed,
):
    # Arrange
    require_docker_image(IMAGE, BUILD_COMMAND)
    eval_dir = tmp_path / "fixture_image_eval"
    image_dir = eval_dir / "fixtures" / "image"
    image_dir.mkdir(parents=True)
    (eval_dir / "eval.py").write_text(FIXTURE_IMAGE_EVAL_SOURCE)
    (image_dir / "Dockerfile").write_text(FIXTURE_DOCKERFILE)
    (image_dir / "visible.txt").write_text("visible\n")
    (eval_dir / "fixtures" / "hidden.txt").write_text("hidden\n")
    monkeypatch.setattr("src.evals_engine.settings.EVALS_DIRS", str(tmp_path))
    monkeypatch.setattr(
        "src.evals_engine.DockerRunner.health_check",
        lambda self, image: HealthCheckResult(healthy=True),
    )

    agent_config = AgentConfig(
        agent_type=AgentType.CLAUDE_CODE,
        agent_model="fixture-image-integration",
    )
    eval_config = Eval(
        number=1,
        eval_dir="fixture_image_eval",
        description="Fixture image integration eval",
        run_count=1,
        tags=[],
    )
    eval_execution = EvalExecution(
        id=uuid4(),
        eval=eval_config,
        agent_config=agent_config,
    )
    agent_execution = AgentEvalExecution(
        agent_config=agent_config,
        total_score=0,
        total_tokens=0,
        total_time_taken_seconds=0,
        evals_executions=[eval_execution],
        status=AgentEvalStatus.PENDING,
    )

    try:
        # Act
        run_agent(agent_execution, Queue())

        # Assert
        assert agent_execution.status == AgentEvalStatus.COMPLETED
        assert eval_execution.score == pytest.approx(1.0)
        assert_container_removed("eval_harness_claude_code_fixture-image-integration")
    finally:
        try:
            docker_client.images.remove(
                "eval-harness-fixture-fixture_image_eval:latest",
                force=True,
            )
        except docker.errors.ImageNotFound:
            pass
