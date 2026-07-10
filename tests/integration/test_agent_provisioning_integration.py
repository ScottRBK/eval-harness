"""Integration tests for agent credential/env provisioning inside real containers."""

import logging

import pytest
from agent_shell.models.agent import AgentType

from src.docker_runner import DockerRunner
from src.helpers.naming import safe_name

pytestmark = pytest.mark.integration


IMAGE = "eval-harness:latest"
BUILD_COMMAND = "docker build -t eval-harness:latest -f src/docker/Dockerfile src/docker/"


PROVISIONING_PROBES = [
    (
        AgentType.CLAUDE_CODE,
        "provision-claude",
        """
import os
assert os.environ['AGENT_TYPE'] == 'claude_code'
assert os.environ['AGENT_MODEL'] == 'provision-claude'
assert os.environ['CLAUDE_CODE_OAUTH_TOKEN'] == 'fake-claude-token'
print('claude provisioning visible')
""",
    ),
    (
        AgentType.COPILOT_CLI,
        "provision-copilot",
        """
import os
assert os.environ['AGENT_TYPE'] == 'copilot_cli'
assert os.environ['AGENT_MODEL'] == 'provision-copilot'
assert os.environ['COPILOT_GITHUB_TOKEN'] == 'fake-copilot-token'
print('copilot provisioning visible')
""",
    ),
    (
        AgentType.CODEX,
        "provision-codex",
        """
from pathlib import Path
assert Path('/home/node/.codex/auth.json').read_text() == '{"codex": true}'
print('codex provisioning visible')
""",
    ),
    (
        AgentType.PI,
        "provision-pi",
        """
from pathlib import Path
credentials = Path('/home/node/.pi/agent/auth.json')
assert credentials.read_text() == '{"pi": true}'
print('pi provisioning visible')
""",
    ),
    (
        AgentType.OPENCODE,
        "provision-opencode",
        """
from pathlib import Path
credentials = Path('/home/node/.local/share/opencode/auth.json')
config = Path('/home/node/.config/opencode/opencode.json')
assert credentials.read_text() == '{"opencode": true}'
assert config.is_file()
print('opencode provisioning visible')
""",
    ),
]


@pytest.mark.parametrize(
    ("agent_type", "model", "probe_script"),
    PROVISIONING_PROBES,
    ids=[agent.value for agent, _model, _script in PROVISIONING_PROBES],
)
def test_agent_provisioning_is_visible_inside_real_container(
    tmp_path,
    monkeypatch,
    require_docker_image,
    assert_container_removed,
    agent_type,
    model,
    probe_script,
):
    # Arrange
    require_docker_image(IMAGE, BUILD_COMMAND)
    codex_auth = tmp_path / "codex" / "auth.json"
    pi_auth = tmp_path / "pi" / "auth.json"
    opencode_auth = tmp_path / "opencode" / "auth.json"
    codex_auth.parent.mkdir()
    pi_auth.parent.mkdir()
    opencode_auth.parent.mkdir()
    codex_auth.write_text('{"codex": true}')
    pi_auth.write_text('{"pi": true}')
    opencode_auth.write_text('{"opencode": true}')
    monkeypatch.setattr(
        "src.docker_runner.settings.CLAUDE_CODE_OAUTH_TOKEN",
        "fake-claude-token",
    )
    monkeypatch.setattr(
        "src.docker_runner.settings.COPILOT_GITHUB_TOKEN",
        "fake-copilot-token",
    )
    monkeypatch.setattr(
        "src.docker_runner.settings.CODEX_CREDENTIALS_LOC",
        str(codex_auth),
    )
    monkeypatch.setattr(
        "src.docker_runner.settings.PI_CREDENTIALS_LOC",
        str(pi_auth),
    )
    monkeypatch.setattr(
        "src.docker_runner.settings.OPENCODE_CREDENTIALS_LOC",
        str(opencode_auth),
    )
    runner = DockerRunner(
        agent_type=agent_type,
        agent_model=model,
        logger=logging.getLogger("integration.agent_provisioning"),
    )

    # Act
    result = runner.docker_run(
        arrange_script="print('arranged')",
        act_script=probe_script,
        score_script="print('EVAL_SCORE=1')",
        image=IMAGE,
    )

    # Assert
    assert result.score == 1
    assert all(not tmp_dir.exists() for tmp_dir in runner._temp_dirs)
    container_name = safe_name(f"eval_harness_{agent_type.value}_{model}")
    assert_container_removed(container_name)
