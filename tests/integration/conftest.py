import docker
import pytest


@pytest.fixture(scope="session")
def docker_client():
    """Return a Docker client or fail with the setup action the caller needs."""
    try:
        client = docker.from_env()
        client.ping()
    except docker.errors.DockerException as exc:
        pytest.fail(f"Docker daemon is required for integration tests: {exc}")
    return client


@pytest.fixture
def require_docker_image(docker_client):
    def _require(image: str, build_command: str):
        try:
            docker_client.images.get(image)
        except docker.errors.ImageNotFound:
            pytest.fail(
                f"Docker image {image!r} is required. Build it with: {build_command}"
            )

    return _require


@pytest.fixture
def fake_claude_token(monkeypatch):
    monkeypatch.setattr(
        "src.docker_runner.settings.CLAUDE_CODE_OAUTH_TOKEN",
        "integration-test-token",
    )


@pytest.fixture
def assert_container_removed(docker_client):
    def _assert(container_name: str):
        with pytest.raises(docker.errors.NotFound):
            docker_client.containers.get(container_name)

    return _assert
