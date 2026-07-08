"""Integration smoke tests for specialised Docker images."""

import docker
import pytest

pytestmark = pytest.mark.integration


RUST_IMAGE = "eval-harness-rust:latest"
RUST_BUILD_COMMAND = (
    "docker build -t eval-harness-rust:latest -f src/docker/rust/Dockerfile src/docker/"
)


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
