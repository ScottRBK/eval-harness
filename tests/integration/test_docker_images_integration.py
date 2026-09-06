"""Integration smoke tests for specialised Docker images."""

import docker
import pytest

pytestmark = pytest.mark.integration


RUST_IMAGE = "eval-harness-rust:latest"
RUST_BUILD_COMMAND = (
    "docker build -t eval-harness-rust:latest -f src/docker/rust/Dockerfile src/docker/"
)
BASE_IMAGE = "eval-harness:latest"
BASE_BUILD_COMMAND = "docker build -t eval-harness:latest -f src/docker/Dockerfile src/docker/"


def test_base_image_has_agent_shell_pid_namespace_policy(require_docker_image, docker_client):
    # Arrange
    require_docker_image(BASE_IMAGE, BASE_BUILD_COMMAND)
    script = """
import importlib.metadata
import os
from agent_shell.models.agent import AgentType
from agent_shell.shell import AgentShell

assert importlib.metadata.version('agent-shell-py') == '0.3.1'
os.environ['AGENTSHELL_ISOLATION_POLICY'] = 'linux-pid-namespace'
shell = AgentShell(agent_type=AgentType.CLAUDE_CODE)
assert type(shell.isolation_policy).__name__ == 'LinuxPidNamespaceIsolation'
print('agent-shell isolation available')
"""

    # Act
    output = docker_client.containers.run(
        image=BASE_IMAGE,
        command=["python", "-c", script],
        remove=True,
        stdout=True,
        stderr=True,
    )

    # Assert
    assert b"agent-shell isolation available" in output


def test_base_image_has_pi_cli(require_docker_image, docker_client):
    """Pi is installed in the same image used by every evaluation."""
    require_docker_image(BASE_IMAGE, BASE_BUILD_COMMAND)

    output = docker_client.containers.run(
        image=BASE_IMAGE,
        command=["pi", "--version"],
        remove=True,
        stdout=True,
        stderr=True,
    )

    assert output


def test_base_image_has_opencode_cli(require_docker_image, docker_client):
    """OpenCode on PATH must be a runnable Linux binary."""
    require_docker_image(BASE_IMAGE, BASE_BUILD_COMMAND)

    try:
        output = docker_client.containers.run(
            image=BASE_IMAGE,
            command=["opencode", "--version"],
            remove=True,
            stdout=True,
            stderr=True,
        )
    except docker.errors.ContainerError as error:
        output = error.stderr or b""

    text = output.decode(errors="replace")
    assert "exec format error" not in text.lower()
    assert "Bun v" in text


def test_rust_image_can_compile_and_run_a_tiny_crate(
    docker_client,
    require_docker_image,
):
    # Arrange
    require_docker_image(RUST_IMAGE, RUST_BUILD_COMMAND)
    container_name = "eval_harness_rust_image_smoke"
    try:
        docker_client.containers.get(container_name).remove(force=True)
    except docker.errors.NotFound:
        pass
    container = docker_client.containers.run(
        image=RUST_IMAGE,
        command=["sleep", "infinity"],
        detach=True,
        name=container_name,
    )

    try:
        # Act
        exit_code, output = container.exec_run(
            [
                "sh",
                "-lc",
                "rustc --version && "
                "cargo --version && "
                "cargo new --bin /tmp/rust-smoke --quiet && "
                "cargo run --quiet --manifest-path /tmp/rust-smoke/Cargo.toml",
            ]
        )
        buffer = output.decode(errors="replace")

        # Assert
        assert exit_code == 0, buffer
        assert "rustc" in buffer
        assert "cargo" in buffer
        assert "Hello, world!" in buffer
    finally:
        try:
            container.stop(timeout=5)
            container.remove()
        except docker.errors.NotFound:
            pass
