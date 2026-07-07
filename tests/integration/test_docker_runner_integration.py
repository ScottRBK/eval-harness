"""Integration tests for DockerRunner's real container execution path.

These tests intentionally use the Docker daemon and the built eval-harness image.
They do not call a real agent/provider; the scripts exercise the harness-owned
arrange/act/score lifecycle, stdout parsing, and container cleanup.
"""

import logging

import docker
import pytest
from agent_shell.models.agent import AgentType

from src.docker_runner import DockerRunner

pytestmark = pytest.mark.integration


IMAGE = "eval-harness:latest"
CONTAINER_NAME = "eval_harness_claude_code_integration-model"


def _docker_client_or_fail():
    """Return a Docker client or fail with the setup action the caller needs."""
    try:
        client = docker.from_env()
        client.ping()
    except docker.errors.DockerException as exc:
        pytest.fail(f"Docker daemon is required for integration tests: {exc}")
    return client


def _require_image(client):
    """Fail clearly if the eval-harness image has not been built yet."""
    try:
        client.images.get(IMAGE)
    except docker.errors.ImageNotFound:
        pytest.fail(
            f"Docker image {IMAGE!r} is required. Build it with: "
            "docker build -t eval-harness:latest -f src/docker/Dockerfile src/docker/"
        )


def test_runs_arrange_act_score_inside_real_container(monkeypatch):
    # Arrange
    client = _docker_client_or_fail()
    _require_image(client)
    monkeypatch.setattr(
        "src.docker_runner.settings.CLAUDE_CODE_OAUTH_TOKEN",
        "integration-test-token",
    )

    runner = DockerRunner(
        agent_type=AgentType.CLAUDE_CODE,
        agent_model="integration-model",
        logger=logging.getLogger("integration.docker_runner"),
    )
    arrange_script = r"""
from pathlib import Path
Path('/workspace/integration-marker.txt').write_text('arrange\n')
print('arranged')
"""
    act_script = r"""
from pathlib import Path
path = Path('/workspace/integration-marker.txt')
path.write_text(path.read_text() + 'act\n')
print('acted')
"""
    score_script = r"""
from pathlib import Path
contents = Path('/workspace/integration-marker.txt').read_text()
assert contents == 'arrange\nact\n'
print('EVAL_TOTAL_TOKENS=7')
print('EVAL_SCORE=0.875')
"""

    # Act
    result = runner.docker_run(
        arrange_script=arrange_script,
        act_script=act_script,
        score_script=score_script,
        image=IMAGE,
    )

    # Assert
    assert result.score == pytest.approx(0.875)
    assert result.total_tokens == 7
    assert result.time_taken_seconds > 0
    with pytest.raises(docker.errors.NotFound):
        client.containers.get(CONTAINER_NAME)
