"""Integration tests for DockerRunner's real container execution path.

These tests intentionally use the Docker daemon and the built eval-harness image.
They do not call a real agent/provider; the scripts exercise the harness-owned
arrange/act/score lifecycle, stdout parsing, and container cleanup.
"""

import logging

import pytest
from agent_shell.models.agent import AgentType

from src.docker_runner import DockerRunner

pytestmark = pytest.mark.integration


IMAGE = "eval-harness:latest"
BUILD_COMMAND = "docker build -t eval-harness:latest -f src/docker/Dockerfile src/docker/"


def _runner(model: str) -> DockerRunner:
    return DockerRunner(
        agent_type=AgentType.CLAUDE_CODE,
        agent_model=model,
        logger=logging.getLogger("integration.docker_runner"),
    )


def test_runs_arrange_act_score_inside_real_container(
    require_docker_image,
    fake_claude_token,
    assert_container_removed,
):
    # Arrange
    require_docker_image(IMAGE, BUILD_COMMAND)
    runner = _runner("integration-model")
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
    assert_container_removed("eval_harness_claude_code_integration-model")


def test_timeout_removes_real_container(
    monkeypatch,
    require_docker_image,
    fake_claude_token,
    assert_container_removed,
):
    # Arrange
    require_docker_image(IMAGE, BUILD_COMMAND)
    monkeypatch.setattr(
        "src.docker_runner.settings.ARRANGE_TIMEOUT_SECONDS",
        1,
    )
    runner = _runner("integration-timeout")

    # Act / Assert
    with pytest.raises(TimeoutError, match="arrange timed out"):
        runner.docker_run(
            arrange_script="import time\ntime.sleep(5)",
            act_script="print('should not run')",
            score_script="print('EVAL_SCORE=1')",
            image=IMAGE,
        )
    assert_container_removed("eval_harness_claude_code_integration-timeout")


def test_failed_phase_removes_real_container(
    require_docker_image,
    fake_claude_token,
    assert_container_removed,
):
    # Arrange
    require_docker_image(IMAGE, BUILD_COMMAND)
    runner = _runner("integration-failure")

    # Act / Assert
    with pytest.raises(RuntimeError, match="act failed"):
        runner.docker_run(
            arrange_script="print('arranged')",
            act_script="raise RuntimeError('boom')",
            score_script="print('EVAL_SCORE=1')",
            image=IMAGE,
        )
    assert_container_removed("eval_harness_claude_code_integration-failure")
