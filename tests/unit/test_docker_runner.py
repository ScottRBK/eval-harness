"""Unit tests for DockerRunner.

Hermetic and CI-safe: the docker daemon is mocked (see conftest), staging dirs
are redirected under pytest's ``tmp_path`` so nothing leaks, and ``settings`` is
patched so no host secrets or files are required.
"""

import io
import json
import logging
import stat
import tarfile
import tempfile
from pathlib import Path
from unittest import mock
from uuid import uuid4

import docker
import pytest
from agent_shell.models.agent import AgentType

from src.docker_runner import DockerRunner, build_image
from src.failure_diagnostics import TRACE_ENV, TRACE_PATH
from src.models import CapabilityProfile


@pytest.fixture(autouse=True)
def _staging_under_tmp(tmp_path, monkeypatch):
    """Redirect _staged_mount's mkdtemp under tmp_path so every staging dir is
    ephemeral and the suite leaves nothing behind on disk."""
    real_mkdtemp = tempfile.mkdtemp

    def _mkdtemp(*args, **kwargs):
        kwargs.setdefault("dir", str(tmp_path))
        return real_mkdtemp(*args, **kwargs)

    monkeypatch.setattr("src.docker_runner.tempfile.mkdtemp", _mkdtemp)


@pytest.fixture
def claude_token(monkeypatch):
    monkeypatch.setattr("src.docker_runner.settings.CLAUDE_CODE_OAUTH_TOKEN", "tok-abc")
    return "tok-abc"


@pytest.fixture
def opencode_creds(tmp_path, monkeypatch):
    creds = tmp_path / "auth.json"
    creds.write_text("{}")
    monkeypatch.setattr("src.docker_runner.settings.OPENCODE_CREDENTIALS_LOC", str(creds))
    return creds


@pytest.fixture
def codex_creds(tmp_path, monkeypatch):
    creds = tmp_path / "auth.json"
    creds.write_text("{}")
    monkeypatch.setattr("src.docker_runner.settings.CODEX_CREDENTIALS_LOC", str(creds))
    return creds


@pytest.fixture
def pi_creds(tmp_path, monkeypatch):
    creds = tmp_path / "auth.json"
    creds.write_text("{}")
    monkeypatch.setattr("src.docker_runner.settings.PI_CREDENTIALS_LOC", str(creds))
    return creds


@pytest.fixture
def copilot_token(monkeypatch):
    monkeypatch.setattr("src.docker_runner.settings.COPILOT_GITHUB_TOKEN", "tok-copilot")
    return "tok-copilot"


@pytest.fixture
def github_token(monkeypatch):
    monkeypatch.setattr("src.docker_runner.settings.GITHUB_TOKEN", "tok-gh")
    return "tok-gh"


@pytest.fixture
def azure_devops_pat(monkeypatch):
    monkeypatch.setattr("src.docker_runner.settings.AZURE_DEVOPS_PAT", "tok-ado")
    return "tok-ado"


@pytest.fixture
def health_timeout(monkeypatch):
    monkeypatch.setattr("src.docker_runner.settings.HEALTH_CHECK_TIMEOUT_SECONDS", 60)
    return 60


def _fake_exec_run_client(exec_run_result, stale=False):
    """A mock docker client for the ``health_check`` path.

    ``exec_run`` returns ``(exit_code, output_bytes)`` in one shot (no streaming),
    which is the API ``health_check`` uses. ``exec_run_result`` is that tuple.
    Set ``stale=True`` to simulate a same-named container already existing.
    """
    client = mock.Mock()
    if stale:
        client.containers.get.return_value = mock.Mock()
    else:
        client.containers.get.side_effect = docker.errors.NotFound("absent")
    container = mock.Mock()
    container.id = "c"
    container.exec_run.return_value = exec_run_result
    client.containers.run.return_value = container
    client._container = container
    return client


# --------------------------------------------------------------------------- #
# A. fixture image builds
# --------------------------------------------------------------------------- #


class TestBuildImage:
    def test_uses_only_dockerfile_directory_as_build_context(self, tmp_path):
        # Arrange
        image_dir = tmp_path / "eval" / "fixtures" / "image"
        image_dir.mkdir(parents=True)
        dockerfile = image_dir / "Dockerfile"
        dockerfile.write_text("FROM eval-harness:latest\n")
        client = mock.Mock()
        client.images.build.return_value = (mock.Mock(), iter([]))
        log = mock.Mock()

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            result = build_image(dockerfile, "fixture:latest", log)

        # Assert
        assert result == "fixture:latest"
        client.images.build.assert_called_once_with(
            path=str(image_dir),
            dockerfile="Dockerfile",
            tag="fixture:latest",
            rm=True,
            forcerm=True,
        )

    def test_logs_build_output_when_build_fails(self, tmp_path, caplog):
        # Arrange
        import logging

        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("BROKEN\n")
        client = mock.Mock()
        build_log = iter([{"stream": "Step 1 failed\n"}])
        client.images.build.side_effect = docker.errors.BuildError("bad build", build_log)
        log = logging.getLogger("test.fixture-build")

        # Act / Assert
        with caplog.at_level(logging.ERROR, logger="test.fixture-build"):
            with mock.patch("src.docker_runner.docker.from_env", return_value=client):
                with pytest.raises(docker.errors.BuildError):
                    build_image(dockerfile, "fixture:latest", log)
        assert "Step 1 failed" in caplog.text


# --------------------------------------------------------------------------- #
# B. _staged_mount — real filesystem behaviour via tmp_path
# --------------------------------------------------------------------------- #


class TestStagedMount:
    def test_copies_files_into_staging_and_binds_read_write(self, tmp_path):
        # Arrange
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")
        source = tmp_path / "auth.json"
        source.write_text("secret")

        # Act
        volumes = runner._staged_mount([source], "/container/dir")

        # Assert
        assert len(volumes) == 1
        staging, spec = next(iter(volumes.items()))
        assert spec == {"bind": "/container/dir", "mode": "rw"}
        assert (Path(staging) / "auth.json").read_text() == "secret"

    def test_sets_private_mode_on_copied_files(self, tmp_path):
        # Arrange
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")
        source = tmp_path / "auth.json"
        source.write_text("secret")
        source.chmod(0o600)

        # Act
        volumes = runner._staged_mount([source], "/container/dir")

        # Assert
        staging = Path(next(iter(volumes)))
        mode = stat.S_IMODE((staging / "auth.json").stat().st_mode)
        assert mode == 0o600

    def test_tracks_staging_dir_for_cleanup(self, tmp_path):
        # Arrange
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")
        source = tmp_path / "auth.json"
        source.write_text("secret")

        # Act
        volumes = runner._staged_mount([source], "/container/dir")

        # Assert
        staging = Path(next(iter(volumes)))
        assert runner._temp_dirs == [staging]

    def test_tracks_capability_staging_before_write_failure(self, monkeypatch):
        # Arrange
        runner = DockerRunner(
            AgentType.CLAUDE_CODE,
            "model",
            capability_profile=CapabilityProfile(packages=("npm:tools@1.2.3",)),
        )
        monkeypatch.setattr(
            Path,
            "write_text",
            mock.Mock(side_effect=OSError("capability staging failed")),
        )

        # Act / Assert
        with pytest.raises(OSError, match="capability staging failed"):
            runner._stage_capability_profile()
        assert len(runner._temp_dirs) == 1
        assert runner._temp_dirs[0].is_dir()

    def test_private_mounts_reject_unaligned_host_uid(self, monkeypatch, tmp_path):
        # Arrange
        source = tmp_path / "auth.json"
        source.write_text("secret")
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")
        monkeypatch.setattr("src.docker_runner.os.getuid", lambda: 2000)

        # Act / Assert
        with pytest.raises(RuntimeError, match=r"UID.*1000"):
            runner._staged_mount([source], "/container/dir")

    def test_leaves_source_files_untouched(self, tmp_path):
        # Arrange
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")
        source = tmp_path / "auth.json"
        source.write_text("secret")
        source.chmod(0o600)

        # Act
        runner._staged_mount([source], "/container/dir")

        # Assert — original is a copy source, never moved or re-permissioned
        assert source.read_text() == "secret"
        assert stat.S_IMODE(source.stat().st_mode) == 0o600


# --------------------------------------------------------------------------- #
# B. _provision_agent / _setup_* — patched settings
# --------------------------------------------------------------------------- #


class TestProvisionAgent:
    def test_claude_code_provisions_token_as_environment(self, claude_token):
        # Arrange
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act
        prov = runner._provision_agent()

        # Assert
        assert prov.environment == {"CLAUDE_CODE_OAUTH_TOKEN": claude_token}
        assert prov.volumes == {}

    def test_claude_code_without_token_raises(self, monkeypatch):
        # Arrange
        monkeypatch.setattr("src.docker_runner.settings.CLAUDE_CODE_OAUTH_TOKEN", "")
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act / Assert
        with pytest.raises(RuntimeError):
            runner._provision_agent()

    def test_opencode_provisions_volumes_not_environment(self, opencode_creds):
        # Arrange
        runner = DockerRunner(AgentType.OPENCODE, "model")

        # Act
        prov = runner._provision_agent()

        # Assert
        assert prov.environment == {}
        assert prov.volumes

    def test_opencode_volumes_include_credentials_and_config_binds(self, opencode_creds):
        # Arrange
        runner = DockerRunner(AgentType.OPENCODE, "model")

        # Act
        prov = runner._provision_agent()

        # Assert — both the host-secret mount and the repo-config mount present
        binds = {spec["bind"] for spec in prov.volumes.values()}
        assert "/home/node/.local/share/opencode" in binds
        assert "/home/node/.config/opencode" in binds

    def test_opencode_without_auth_file_raises(self, tmp_path, monkeypatch):
        # Arrange — point at a path that does not exist
        monkeypatch.setattr(
            "src.docker_runner.settings.OPENCODE_CREDENTIALS_LOC",
            str(tmp_path / "missing.json"),
        )
        runner = DockerRunner(AgentType.OPENCODE, "model")

        # Act / Assert
        with pytest.raises(RuntimeError):
            runner._provision_agent()

    def test_codex_provisions_auth_volume_not_environment(self, codex_creds):
        # Arrange
        runner = DockerRunner(AgentType.CODEX, "model")

        # Act
        prov = runner._provision_agent()

        # Assert — Codex authenticates via a mounted auth.json, not an env var
        assert prov.environment == {}
        binds = {spec["bind"] for spec in prov.volumes.values()}
        assert "/home/node/.codex" in binds

    def test_codex_without_auth_file_raises(self, tmp_path, monkeypatch):
        # Arrange — point at a path that does not exist
        monkeypatch.setattr(
            "src.docker_runner.settings.CODEX_CREDENTIALS_LOC",
            str(tmp_path / "missing.json"),
        )
        runner = DockerRunner(AgentType.CODEX, "model")

        # Act / Assert
        with pytest.raises(RuntimeError):
            runner._provision_agent()

    def test_grok_provisions_auth_volume_not_environment(self, tmp_path, monkeypatch):
        # Arrange
        auth = tmp_path / "grok" / "grok-prod.json"
        auth.parent.mkdir()
        auth.write_text('{"grok": true}')
        monkeypatch.setattr("src.docker_runner.settings.GROK_CREDENTIALS_LOC", str(auth))
        runner = DockerRunner(AgentType.GROK, "model")

        # Act
        prov = runner._provision_agent()

        # Assert — file bind (not dir) so the image's ~/.grok/bin stays visible
        assert prov.environment == {}
        assert len(prov.volumes) == 1
        staged_path = Path(next(iter(prov.volumes)))
        assert next(iter(prov.volumes.values())) == {
            "bind": "/home/node/.grok/auth.json",
            "mode": "rw",
        }
        assert staged_path.read_text() == '{"grok": true}'

    def test_grok_without_auth_file_raises_clear_error(self, tmp_path, monkeypatch):
        # Arrange
        missing = tmp_path / "missing-grok-auth.json"
        monkeypatch.setattr("src.docker_runner.settings.GROK_CREDENTIALS_LOC", str(missing))
        runner = DockerRunner(AgentType.GROK, "model")

        # Act / Assert
        with pytest.raises(RuntimeError, match=r"Grok auth file not found.*missing-grok-auth"):
            runner._provision_agent()

    def test_pi_provisions_auth_volume_not_environment(self, pi_creds):
        # Arrange
        runner = DockerRunner(AgentType.PI, "model")

        # Act
        prov = runner._provision_agent()

        # Assert — Pi authenticates via its staged auth.json, not an env var
        assert prov.environment == {}
        binds = {spec["bind"] for spec in prov.volumes.values()}
        assert "/home/node/.pi/agent/auth.json" in binds

    def test_pi_mounts_model_files_without_hiding_image_directory(self, tmp_path, monkeypatch):
        # Arrange — auth + custom provider model definitions next to it
        agent_dir = tmp_path / "pi"
        agent_dir.mkdir()
        (agent_dir / "auth.json").write_text("{}")
        (agent_dir / "models.json").write_text('{"providers": {}}')
        (agent_dir / "models-store.json").write_text('{"opencode-go": {}}')
        monkeypatch.setattr(
            "src.docker_runner.settings.PI_CREDENTIALS_LOC",
            str(agent_dir / "auth.json"),
        )
        runner = DockerRunner(AgentType.PI, "model")

        # Act
        prov = runner._provision_agent()

        # Assert — each host file is mounted individually. This preserves any
        # image-baked Pi packages/extensions in the rest of ~/.pi/agent.
        assert prov.environment == {}
        assert len(prov.volumes) == 3
        binds = {spec["bind"] for spec in prov.volumes.values()}
        assert binds == {
            "/home/node/.pi/agent/auth.json",
            "/home/node/.pi/agent/models.json",
            "/home/node/.pi/agent/models-store.json",
        }
        for source in prov.volumes:
            assert Path(source).is_file()

    def test_pi_without_model_files_still_provisions_auth(self, pi_creds):
        # Arrange — host has only auth.json (no custom providers)
        runner = DockerRunner(AgentType.PI, "model")

        # Act
        prov = runner._provision_agent()

        # Assert — still provisions; model files are optional, not required
        assert prov.environment == {}
        assert len(prov.volumes) == 1
        source, mount = next(iter(prov.volumes.items()))
        assert Path(source).name == "auth.json"
        assert mount == {"bind": "/home/node/.pi/agent/auth.json", "mode": "rw"}

    def test_pi_without_auth_file_raises(self, tmp_path, monkeypatch):
        # Arrange — point at a path that does not exist
        monkeypatch.setattr(
            "src.docker_runner.settings.PI_CREDENTIALS_LOC",
            str(tmp_path / "missing.json"),
        )
        runner = DockerRunner(AgentType.PI, "model")

        # Act / Assert
        with pytest.raises(RuntimeError):
            runner._provision_agent()

    def test_cursor_provisions_api_key_as_environment(self, monkeypatch):
        # Arrange
        monkeypatch.setattr("src.docker_runner.settings.CURSOR_API_KEY", "cursor-key")
        monkeypatch.setattr("src.docker_runner.settings.CURSOR_AUTH_TOKEN", "")
        runner = DockerRunner(AgentType.CURSOR, "model")

        # Act
        prov = runner._provision_agent()

        # Assert
        assert prov.environment == {"CURSOR_API_KEY": "cursor-key"}
        assert prov.volumes == {}

    def test_cursor_provisions_auth_token_as_environment(self, monkeypatch):
        # Arrange — OAuth login path (no API key)
        monkeypatch.setattr("src.docker_runner.settings.CURSOR_API_KEY", "")
        monkeypatch.setattr("src.docker_runner.settings.CURSOR_AUTH_TOKEN", "cursor-oauth-token")
        runner = DockerRunner(AgentType.CURSOR, "model")

        # Act
        prov = runner._provision_agent()

        # Assert
        assert prov.environment == {"CURSOR_AUTH_TOKEN": "cursor-oauth-token"}
        assert prov.volumes == {}

    def test_cursor_without_credentials_raises_clear_error(self, monkeypatch):
        # Arrange
        monkeypatch.setattr("src.docker_runner.settings.CURSOR_API_KEY", "")
        monkeypatch.setattr("src.docker_runner.settings.CURSOR_AUTH_TOKEN", "")
        runner = DockerRunner(AgentType.CURSOR, "model")

        # Act / Assert
        with pytest.raises(RuntimeError, match="Cursor credentials not configured"):
            runner._provision_agent()

    def test_copilot_provisions_token_as_environment(self, copilot_token):
        # Arrange
        runner = DockerRunner(AgentType.COPILOT_CLI, "model")

        # Act
        prov = runner._provision_agent()

        # Assert
        assert prov.environment == {"COPILOT_GITHUB_TOKEN": copilot_token}
        assert prov.volumes == {}

    def test_copilot_without_token_raises(self, monkeypatch):
        # Arrange
        monkeypatch.setattr("src.docker_runner.settings.COPILOT_GITHUB_TOKEN", "")
        runner = DockerRunner(AgentType.COPILOT_CLI, "model")

        # Act / Assert
        with pytest.raises(RuntimeError):
            runner._provision_agent()


# --------------------------------------------------------------------------- #
# C. docker_run — mocked docker client
# --------------------------------------------------------------------------- #


class TestDockerRun:
    def test_pid_namespace_isolation_configures_agent_shell_and_docker(
        self, claude_token, make_docker_client, monkeypatch
    ):
        # Arrange
        monkeypatch.setattr("src.docker_runner.settings.AGENT_PID_NAMESPACE_ISOLATION", True)
        client = make_docker_client([("ok", 0), ("ok", 0), ("EVAL_SCORE=1.0", 0)])
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            runner.docker_run("a", "b", "c", "img")

        # Assert
        options = client.containers.run.call_args.kwargs
        assert options["security_opt"] == ["seccomp=unconfined"]
        assert options["environment"]["AGENTSHELL_ISOLATION_POLICY"] == "linux-pid-namespace"

    def test_pid_namespace_isolation_is_absent_by_default(
        self, claude_token, make_docker_client, monkeypatch
    ):
        # Arrange
        monkeypatch.setattr("src.docker_runner.settings.AGENT_PID_NAMESPACE_ISOLATION", False)
        client = make_docker_client([("ok", 0), ("ok", 0), ("EVAL_SCORE=1.0", 0)])
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            runner.docker_run("a", "b", "c", "img")

        # Assert
        options = client.containers.run.call_args.kwargs
        assert "security_opt" not in options
        assert "AGENTSHELL_ISOLATION_POLICY" not in options["environment"]

    def test_passes_phase_timeout_to_docker_exec_command(
        self, claude_token, make_docker_client, monkeypatch
    ):
        # Arrange — distinct values prove each phase gets its configured timeout.
        monkeypatch.setattr("src.docker_runner.settings.ARRANGE_TIMEOUT_SECONDS", 111)
        monkeypatch.setattr("src.docker_runner.settings.ACT_TIMEOUT_SECONDS", 222)
        monkeypatch.setattr("src.docker_runner.settings.SCORE_TIMEOUT_SECONDS", 333)
        client = make_docker_client([("ok", 0), ("ok", 0), ("EVAL_SCORE=1.0", 0)])
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            runner.docker_run("arrange-script", "act-script", "score-script", "img")

        # Assert
        commands = [call.args[1] for call in client.api.exec_create.call_args_list]
        assert commands == [
            [
                "timeout",
                "--kill-after=30s",
                "111",
                "python",
                "-u",
                "-c",
                "arrange-script",
            ],
            [
                "timeout",
                "--kill-after=30s",
                "222",
                "python",
                "-u",
                "-c",
                "act-script",
            ],
            [
                "timeout",
                "--kill-after=30s",
                "333",
                "python",
                "-u",
                "-c",
                "score-script",
            ],
        ]

    def test_configures_capabilities_before_eval_phases(
        self, pi_creds, make_docker_client, monkeypatch
    ):
        # Arrange
        monkeypatch.setattr("src.docker_runner.settings.CAPABILITY_SETUP_TIMEOUT_SECONDS", 444)
        monkeypatch.setattr("src.docker_runner.settings.ARRANGE_TIMEOUT_SECONDS", 111)
        monkeypatch.setattr("src.docker_runner.settings.ACT_TIMEOUT_SECONDS", 222)
        monkeypatch.setattr("src.docker_runner.settings.SCORE_TIMEOUT_SECONDS", 333)
        profile = CapabilityProfile(packages=("npm:@example/tools@1.2.3",))
        client = make_docker_client(
            [
                ("capabilities configured", 0),
                ("arranged", 0),
                ("acted", 0),
                ("EVAL_SCORE=1.0", 0),
            ]
        )
        runner = DockerRunner(
            AgentType.PI,
            "model",
            agent_variant="pi-with-tools",
            capability_profile=profile,
        )

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            result = runner.docker_run("arrange-script", "act-script", "score-script", "img")

        # Assert
        assert result.score == 1.0
        commands = [call.args[1] for call in client.api.exec_create.call_args_list]
        assert [command[0:5] for command in commands] == [
            ["timeout", "--kill-after=30s", "444", "python", "-u"],
            ["timeout", "--kill-after=30s", "111", "python", "-u"],
            ["timeout", "--kill-after=30s", "222", "python", "-u"],
            ["timeout", "--kill-after=30s", "333", "python", "-u"],
        ]
        capability_script = commands[0][-1]
        assert "await shell.add_package(PackageSpec(source=source" in capability_script
        assert "await shell.add_mcp_server" in capability_script
        assert "spec_path.write_text('{}'" in capability_script
        assert "timeout=remaining" in capability_script
        assert (
            client.containers.run.call_args.kwargs["environment"][
                "CAPABILITY_SETUP_TIMEOUT_SECONDS"
            ]
            == "444"
        )
        assert client.containers.run.call_args.kwargs["name"] == (
            "eval_harness_pi_model_pi-with-tools"
        )

    def test_configures_mcp_without_putting_secret_in_exec_command(
        self, opencode_creds, make_docker_client, caplog
    ):
        # Arrange
        secret = "sentinel-mcp-secret"
        profile = CapabilityProfile(
            mcp_servers=(
                {
                    "name": "remote",
                    "type": "stdio",
                    "command": "mcp-server",
                    "env": {"TOKEN": secret},
                },
            )
        )
        client = make_docker_client([(secret, 1), ("ok", 0), ("ok", 0)])
        captured = {}

        def _run(**kwargs):
            captured["name"] = kwargs["name"]
            for source, spec in kwargs["volumes"].items():
                if spec["bind"] == "/tmp/eval-harness-capabilities.json":
                    captured["payload"] = json.loads(Path(source).read_text())
                    captured["mode"] = stat.S_IMODE(Path(source).stat().st_mode)
            return client._container

        client.containers.run.side_effect = _run
        runner = DockerRunner(
            AgentType.OPENCODE,
            "model",
            capability_profile=profile,
        )

        # Act / Assert
        with caplog.at_level(logging.INFO, logger="src.docker_runner"):
            with mock.patch("src.docker_runner.docker.from_env", return_value=client):
                with pytest.raises(RuntimeError, match="capabilities failed"):
                    runner.docker_run("a", "b", "c", "img")

        # The profile is delivered through a private temporary mount, not the
        # Docker exec command or host logs. It is removed during teardown.
        command = client.api.exec_create.call_args.args[1]
        assert secret not in command[-1]
        assert captured["payload"]["mcp_servers"][0]["env"]["TOKEN"] == secret
        assert captured["mode"] == 0o600
        capability_mount = next(
            spec
            for source, spec in client.containers.run.call_args.kwargs["volumes"].items()
            if spec["bind"] == "/tmp/eval-harness-capabilities.json"
        )
        assert capability_mount["mode"] == "rw"
        assert secret not in caplog.text
        assert not any(
            Path(source).exists() for source in client.containers.run.call_args.kwargs["volumes"]
        )

    def test_session_id_disambiguates_container_name(self, claude_token, make_docker_client):
        # Arrange
        session_id = uuid4()
        client = make_docker_client([("ok", 0), ("ok", 0), ("EVAL_SCORE=1.0", 0)])
        runner = DockerRunner(
            AgentType.CLAUDE_CODE,
            "model",
            session_id=session_id,
        )

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            runner.docker_run("a", "b", "c", "img")

        # Assert
        name = client.containers.run.call_args.kwargs["name"]
        assert str(session_id) in name

    def test_passes_empty_agent_effort_env_when_unset(self, claude_token, make_docker_client):
        # Arrange — no effort configured. docker-py turns a None env *value* into a
        # bare key the container inherits (and thus leaves unset), which would make
        # the eval's os.environ["AGENT_EFFORT"] KeyError — so it must coerce to "".
        client = make_docker_client([("ok", 0), ("ok", 0), ("EVAL_SCORE=1.0", 0)])
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            runner.docker_run("a", "b", "c", "img")

        # Assert — the var is present and empty, never absent
        env = client.containers.run.call_args.kwargs["environment"]
        assert env["AGENT_EFFORT"] == ""

    def test_passes_configured_agent_effort_into_container_env(
        self, claude_token, make_docker_client
    ):
        # Arrange — a configured effort must reach the container verbatim so the
        # agent_shell wrapper inside can forward it as the agent's --effort flag
        client = make_docker_client([("ok", 0), ("ok", 0), ("EVAL_SCORE=1.0", 0)])
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model", agent_effort="high")

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            runner.docker_run("a", "b", "c", "img")

        # Assert
        env = client.containers.run.call_args.kwargs["environment"]
        assert env["AGENT_EFFORT"] == "high"

    def test_unset_effort_omits_effort_from_container_name(self, claude_token, make_docker_client):
        # Arrange — regression: a None effort once rendered the literal "_None"
        # suffix (eval_harness_..._model_None) because the f-string stringifies None.
        client = make_docker_client([("ok", 0), ("ok", 0), ("EVAL_SCORE=1.0", 0)])
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            runner.docker_run("a", "b", "c", "img")

        # Assert — clean name, no trailing _None
        name = client.containers.run.call_args.kwargs["name"]
        assert name == "eval_harness_claude_code_model"
        assert "None" not in name

    def test_effort_disambiguates_container_name_for_same_type_and_model(
        self, claude_token, make_docker_client
    ):
        # Arrange — two agents identical but for effort must not share a container
        # name, or concurrent runs would force-remove each other's live container.
        def _name_for(effort):
            client = make_docker_client([("ok", 0), ("ok", 0), ("EVAL_SCORE=1.0", 0)])
            runner = DockerRunner(AgentType.CLAUDE_CODE, "model", agent_effort=effort)
            with mock.patch("src.docker_runner.docker.from_env", return_value=client):
                runner.docker_run("a", "b", "c", "img")
            return client.containers.run.call_args.kwargs["name"]

        # Act
        high = _name_for("high")
        low = _name_for("low")

        # Assert — distinct, and the effort is what distinguishes them
        assert high == "eval_harness_claude_code_model_high"
        assert low == "eval_harness_claude_code_model_low"
        assert high != low

    def test_parses_score_from_last_eval_score_line(self, claude_token, make_docker_client):
        # Arrange — a stale early score and trailing noise must not win
        score_output = "EVAL_SCORE=0.10\nnoise\nEVAL_SCORE=0.85\ntrailing noise"
        client = make_docker_client([("ok", 0), ("ok", 0), (score_output, 0)])
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            result = runner.docker_run("a", "b", "c", "img")

        # Assert
        assert result.score == 0.85
        assert result.time_taken_seconds >= 0

    def test_streams_each_output_line_once_without_raw_chunk_dump(
        self, claude_token, make_docker_client, caplog
    ):
        # Regression: docker_run logged every chunk twice — a raw
        # "docker output: {chunk}" dump AND the same bytes re-split into
        # "[phase] {line}" records — so every line appeared twice in the
        # per-agent log (worst on Copilot, whose stream is token-granular).
        import logging

        # Arrange — a distinctive multi-line phase output
        client = make_docker_client([("alpha\nbravo", 0), ("ok", 0), ("EVAL_SCORE=1.0", 0)])
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act
        with caplog.at_level(logging.INFO, logger="src.docker_runner"):
            with mock.patch("src.docker_runner.docker.from_env", return_value=client):
                runner.docker_run("a", "b", "c", "img")

        # Assert — the raw chunk dump is gone and each line is logged exactly once
        assert "docker output:" not in caplog.text
        assert "[arrange] alpha" in caplog.text
        assert "[arrange] bravo" in caplog.text
        assert caplog.text.count("alpha") == 1
        assert caplog.text.count("bravo") == 1

    def test_score_defaults_to_zero_without_eval_score_line(self, claude_token, make_docker_client):
        # Arrange
        client = make_docker_client([("ok", 0), ("ok", 0), ("no score here\njust logs", 0)])
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            result = runner.docker_run("a", "b", "c", "img")

        # Assert
        assert result.score == 0.0
        assert result.total_tokens == 0

    def test_sums_total_token_markers_across_all_phases(self, claude_token, make_docker_client):
        # Arrange
        client = make_docker_client(
            [
                ("arrange\nEVAL_TOTAL_TOKENS=10", 0),
                ("act\nEVAL_TOTAL_TOKENS=20\nEVAL_TOTAL_TOKENS=5", 0),
                ("EVAL_TOTAL_TOKENS=7\nEVAL_SCORE=1.0", 0),
            ]
        )
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            result = runner.docker_run("a", "b", "c", "img")

        # Assert
        assert result.total_tokens == 42

    def test_ignores_malformed_total_token_markers(self, claude_token, make_docker_client, caplog):
        # Arrange
        client = make_docker_client(
            [
                ("EVAL_TOTAL_TOKENS=not-a-number", 0),
                ("EVAL_TOTAL_TOKENS=7", 0),
                ("EVAL_SCORE=1.0", 0),
            ]
        )
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            result = runner.docker_run("a", "b", "c", "img")

        # Assert
        assert result.total_tokens == 7
        assert "Ignoring malformed token marker line" in caplog.text

    def test_malformed_score_line_raises_friendly_error(self, claude_token, make_docker_client):
        # Arrange — an EVAL_SCORE= line that isn't a number
        client = make_docker_client([("ok", 0), ("ok", 0), ("EVAL_SCORE=pass", 0)])
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act / Assert — friendly error naming the offending line, not a raw ValueError
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            with pytest.raises(RuntimeError, match="EVAL_SCORE=pass"):
                runner.docker_run("a", "b", "c", "img")

    def test_malformed_score_does_not_expose_capability_secret(
        self, opencode_creds, make_docker_client, caplog
    ):
        # Arrange
        secret = "score-secret"
        profile = CapabilityProfile(
            mcp_servers=(
                {
                    "name": "server",
                    "type": "stdio",
                    "command": "server",
                    "env": {"TOKEN": secret},
                },
            )
        )
        client = make_docker_client(
            [("configured", 0), ("arranged", 0), ("acted", 0), (f"EVAL_SCORE={secret}", 0)]
        )
        runner = DockerRunner(AgentType.OPENCODE, "model", capability_profile=profile)

        # Act / Assert
        with caplog.at_level(logging.INFO, logger="src.docker_runner"):
            with mock.patch("src.docker_runner.docker.from_env", return_value=client):
                with pytest.raises(RuntimeError) as error:
                    runner.docker_run("a", "b", "c", "img")

        assert secret not in str(error.value)
        assert secret not in caplog.text

    def test_nonzero_phase_exit_raises_runtimeerror(self, claude_token, make_docker_client):
        # Arrange — arrange phase exits non-zero
        client = make_docker_client([("boom", 1), ("ok", 0), ("EVAL_SCORE=1.0", 0)])
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act / Assert
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            with pytest.raises(RuntimeError):
                runner.docker_run("a", "b", "c", "img")

    def test_captures_failed_attempt_before_container_cleanup(
        self, claude_token, make_docker_client, monkeypatch, tmp_path
    ):
        # Arrange
        monkeypatch.setattr("src.docker_runner.settings.CAPTURE_FAILURE_DIAGNOSTICS", True)
        client = make_docker_client([("boom", 1), ("ok", 0), ("EVAL_SCORE=1.0", 0)])
        archive = io.BytesIO()
        trace = b"Raw event: {'marker': 'before failure'}\n"
        with tarfile.open(fileobj=archive, mode="w") as tar:
            member = tarfile.TarInfo("agent-shell-trace.log")
            member.size = len(trace)
            tar.addfile(member, io.BytesIO(trace))
        client._container.get_archive.return_value = (iter([archive.getvalue()]), {})
        client._container.attrs = {
            "Id": "container-id",
            "Name": "/eval-container",
            "Image": "image-id",
            "State": {"Status": "running", "ExitCode": 0},
            "Config": {"Env": ["CLAUDE_CODE_OAUTH_TOKEN=secret"]},
            "Mounts": [{"Source": "/host/workspace", "Destination": "/workspace"}],
        }
        attempt_dir = tmp_path / "attempt-01"
        runner = DockerRunner(
            AgentType.CLAUDE_CODE,
            "model",
            diagnostics_dir=attempt_dir,
        )

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            with pytest.raises(RuntimeError, match="arrange failed"):
                runner.docker_run("a", "b", "c", "img")

        # Assert
        manifest = json.loads((attempt_dir / "failure.json").read_text())
        assert manifest["phase"] == "arrange"
        assert manifest["exception_type"] == "RuntimeError"
        assert manifest["exit_code"] == 1
        assert (attempt_dir / "agent-shell-trace.log").read_bytes() == trace
        assert "secret" not in (attempt_dir / "container-inspect.json").read_text()
        client._container.get_archive.assert_called_once_with(TRACE_PATH)
        client._container.stop.assert_called_once()
        client._container.remove.assert_called_once()

    def test_container_launch_failure_removes_orphaned_container(
        self, claude_token, make_docker_client
    ):
        # Arrange
        client = make_docker_client([("ok", 0), ("ok", 0), ("EVAL_SCORE=1.0", 0)])
        orphan = mock.Mock()
        get_calls = 0

        def get_container(_name):
            nonlocal get_calls
            get_calls += 1
            if get_calls == 1:
                raise docker.errors.NotFound("absent")
            return orphan

        client.containers.get.side_effect = get_container
        client.containers.run.side_effect = RuntimeError("container startup failed")
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act / Assert
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            with pytest.raises(RuntimeError, match="container startup failed"):
                runner.docker_run("a", "b", "c", "img")
        orphan.remove.assert_called_once_with(force=True)

    def test_container_launch_failure_writes_manifest_without_exit_code(
        self, claude_token, make_docker_client, monkeypatch, tmp_path
    ):
        # Arrange
        monkeypatch.setattr("src.docker_runner.settings.CAPTURE_FAILURE_DIAGNOSTICS", True)
        client = make_docker_client([("ok", 0), ("ok", 0), ("EVAL_SCORE=1.0", 0)])
        client.containers.run.side_effect = RuntimeError("container launch failed")
        runner = DockerRunner(
            AgentType.CLAUDE_CODE,
            "model",
            diagnostics_dir=tmp_path / "container",
        )

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            with pytest.raises(RuntimeError, match="container launch failed"):
                runner.docker_run("a", "b", "c", "img")

        # Assert
        manifest = json.loads((tmp_path / "container" / "failure.json").read_text())
        assert manifest["phase"] == "container"
        assert "exit_code" not in manifest

    def test_provisioning_failure_writes_manifest_without_container(
        self, claude_token, monkeypatch, tmp_path
    ):
        # Arrange
        monkeypatch.setattr("src.docker_runner.settings.CAPTURE_FAILURE_DIAGNOSTICS", True)
        runner = DockerRunner(
            AgentType.CLAUDE_CODE,
            "model",
            diagnostics_dir=tmp_path / "provisioning",
        )
        monkeypatch.setattr(
            runner,
            "_provision_agent",
            mock.Mock(side_effect=RuntimeError("credentials unavailable")),
        )

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=mock.Mock()):
            with pytest.raises(RuntimeError, match="credentials unavailable"):
                runner.docker_run("a", "b", "c", "img")

        # Assert
        manifest = json.loads((tmp_path / "provisioning" / "failure.json").read_text())
        assert manifest["phase"] == "provisioning"
        assert "exit_code" not in manifest
        assert not (tmp_path / "provisioning" / "agent-shell-trace.log").exists()

    def test_timeout_metadata_is_captured(
        self, claude_token, make_docker_client, monkeypatch, tmp_path
    ):
        # Arrange
        monkeypatch.setattr("src.docker_runner.settings.CAPTURE_FAILURE_DIAGNOSTICS", True)
        client = make_docker_client([("timeout", 124), ("ok", 0), ("EVAL_SCORE=1.0", 0)])
        runner = DockerRunner(
            AgentType.CLAUDE_CODE,
            "model",
            diagnostics_dir=tmp_path / "timeout",
        )

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            with pytest.raises(TimeoutError):
                runner.docker_run("a", "b", "c", "img")

        # Assert
        manifest = json.loads((tmp_path / "timeout" / "failure.json").read_text())
        assert manifest["timed_out"] is True
        assert manifest["exit_code"] == 124

    def test_signal_exit_metadata_is_captured(
        self, claude_token, make_docker_client, monkeypatch, tmp_path
    ):
        # Arrange
        monkeypatch.setattr("src.docker_runner.settings.CAPTURE_FAILURE_DIAGNOSTICS", True)
        client = make_docker_client([("terminated", 143), ("ok", 0), ("EVAL_SCORE=1.0", 0)])
        attempt_dir = tmp_path / "signal"
        runner = DockerRunner(
            AgentType.CLAUDE_CODE,
            "model",
            diagnostics_dir=attempt_dir,
        )

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            with pytest.raises(RuntimeError, match="arrange failed"):
                runner.docker_run("a", "b", "c", "img")

        # Assert
        manifest = json.loads((attempt_dir / "failure.json").read_text())
        assert manifest["exit_code"] == 143
        assert manifest["signal"] == "SIGTERM"
        assert manifest["timed_out"] is False

    def test_successful_attempt_leaves_no_diagnostics(
        self, claude_token, make_docker_client, monkeypatch, tmp_path
    ):
        # Arrange
        monkeypatch.setattr("src.docker_runner.settings.CAPTURE_FAILURE_DIAGNOSTICS", True)
        client = make_docker_client([("ok", 0), ("ok", 0), ("EVAL_SCORE=1.0", 0)])
        attempt_dir = tmp_path / "successful-attempt"
        runner = DockerRunner(
            AgentType.CLAUDE_CODE,
            "model",
            diagnostics_dir=attempt_dir,
        )

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            runner.docker_run("a", "b", "c", "img")

        # Assert
        assert not attempt_dir.exists()
        assert client.containers.run.call_args.kwargs["environment"][TRACE_ENV]

    def test_disabled_capture_has_no_handler_configuration_or_artifacts(
        self, claude_token, make_docker_client, monkeypatch, tmp_path
    ):
        # Arrange
        monkeypatch.setattr("src.docker_runner.settings.CAPTURE_FAILURE_DIAGNOSTICS", False)
        client = make_docker_client([("boom", 1), ("ok", 0), ("EVAL_SCORE=1.0", 0)])
        attempt_dir = tmp_path / "disabled-attempt"
        runner = DockerRunner(
            AgentType.CLAUDE_CODE,
            "model",
            diagnostics_dir=attempt_dir,
        )

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            with pytest.raises(RuntimeError):
                runner.docker_run("a", "b", "c", "img")

        # Assert
        assert not attempt_dir.exists()
        assert TRACE_ENV not in client.containers.run.call_args.kwargs["environment"]

    def test_capture_failure_cannot_replace_original_exception(
        self, claude_token, make_docker_client, monkeypatch, tmp_path
    ):
        # Arrange
        monkeypatch.setattr("src.docker_runner.settings.CAPTURE_FAILURE_DIAGNOSTICS", True)
        monkeypatch.setattr(
            "src.docker_runner.capture_failure_diagnostics",
            mock.Mock(side_effect=RuntimeError("diagnostics failed")),
        )
        client = make_docker_client([("boom", 1), ("ok", 0), ("EVAL_SCORE=1.0", 0)])
        runner = DockerRunner(
            AgentType.CLAUDE_CODE,
            "model",
            diagnostics_dir=tmp_path / "capture-error",
        )

        # Act / Assert
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            with pytest.raises(RuntimeError, match="arrange failed"):
                runner.docker_run("a", "b", "c", "img")

    def test_cleanup_runs_when_phase_raises(self, opencode_creds, make_docker_client):
        # Arrange — opencode so provisioning creates staging dirs to clean up
        client = make_docker_client([("boom", 1), ("ok", 0), ("ok", 0)])
        runner = DockerRunner(AgentType.OPENCODE, "model")

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            with pytest.raises(RuntimeError):
                runner.docker_run("a", "b", "c", "img")

        # Assert — staging dirs removed and container torn down despite the failure
        assert runner._temp_dirs
        assert all(not d.exists() for d in runner._temp_dirs)
        client._container.stop.assert_called_once()
        client._container.remove.assert_called_once()

    def test_staging_cleanup_survives_container_cleanup_error(
        self, opencode_creds, make_docker_client, caplog
    ):
        # Arrange
        secret = 'cleanup"secret'
        profile = CapabilityProfile(
            mcp_servers=(
                {
                    "name": "server",
                    "type": "stdio",
                    "command": "server",
                    "env": {"TOKEN": secret},
                },
            )
        )
        client = make_docker_client(
            [("configured", 0), ("ok", 0), ("ok", 0), ("EVAL_SCORE=1.0", 0)]
        )
        client._container.stop.side_effect = RuntimeError(f"stop failed: {secret}")
        runner = DockerRunner(AgentType.OPENCODE, "model", capability_profile=profile)

        # Act
        with caplog.at_level(logging.WARNING, logger="src.docker_runner"):
            with mock.patch("src.docker_runner.docker.from_env", return_value=client):
                result = runner.docker_run("a", "b", "c", "img")

        # Assert — a Docker teardown problem must not strand credential staging dirs
        assert result.score == 1.0
        assert runner._temp_dirs
        assert all(not d.exists() for d in runner._temp_dirs)
        client._container.remove.assert_called_once_with(force=True)
        assert secret not in caplog.text

    def test_stream_response_closed_even_when_streaming_raises(
        self, claude_token, make_docker_client
    ):
        # Arrange — first phase's stream blows up mid-iteration
        client = make_docker_client([("ok", 0), ("ok", 0), ("EVAL_SCORE=1.0", 0)])
        client._streams[0]._raise = True
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            result = runner.docker_run("a", "b", "c", "img")

        # Assert — streaming error is swallowed, every stream is closed, run finishes
        assert result.score == 1.0
        assert all(s._response.close.called for s in client._streams)

    def test_stale_container_removed_before_run(self, claude_token, make_docker_client):
        # Arrange — a stale container exists this time
        client = make_docker_client([("ok", 0), ("ok", 0), ("EVAL_SCORE=1.0", 0)])
        client.containers.get.side_effect = None
        stale = mock.Mock()
        client.containers.get.return_value = stale
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            runner.docker_run("a", "b", "c", "img")

        # Assert — container name is per-agent so parallel runs don't collide
        client.containers.get.assert_called_once_with("eval_harness_claude_code_model")
        stale.remove.assert_called_once_with(force=True)

    def test_missing_stale_container_is_ignored(self, claude_token, make_docker_client):
        # Arrange — default fake client raises NotFound on get
        client = make_docker_client([("ok", 0), ("ok", 0), ("EVAL_SCORE=0.5", 0)])
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            result = runner.docker_run("a", "b", "c", "img")

        # Assert — NotFound swallowed, run proceeds normally
        assert result.score == 0.5

    def test_injects_github_token_as_gh_token_env_when_set(
        self, claude_token, github_token, make_docker_client
    ):
        # Arrange — a configured GitHub token is harness infrastructure, not an
        # agent credential: it must reach every container as GH_TOKEN so arrange()'s
        # git/gh clone can read private repos, whichever agent is under test.
        client = make_docker_client([("ok", 0), ("ok", 0), ("EVAL_SCORE=1.0", 0)])
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            runner.docker_run("a", "b", "c", "img")

        # Assert
        env = client.containers.run.call_args.kwargs["environment"]
        assert env["GH_TOKEN"] == github_token

    def test_omits_gh_token_env_when_github_token_unset(
        self, claude_token, make_docker_client, monkeypatch
    ):
        # Arrange — fail-open: with no token configured, GH_TOKEN must be absent.
        # gh refuses to run with an empty token, and public-repo evals must keep
        # cloning anonymously, so we never inject a blank GH_TOKEN.
        monkeypatch.setattr("src.docker_runner.settings.GITHUB_TOKEN", "")
        client = make_docker_client([("ok", 0), ("ok", 0), ("EVAL_SCORE=1.0", 0)])
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            runner.docker_run("a", "b", "c", "img")

        # Assert
        env = client.containers.run.call_args.kwargs["environment"]
        assert "GH_TOKEN" not in env

    def test_injects_azure_devops_pat_as_ado_pat_env_when_set(
        self, claude_token, azure_devops_pat, make_docker_client
    ):
        # Arrange — mirrors GITHUB_TOKEN/GH_TOKEN for private Azure DevOps clones.
        client = make_docker_client([("ok", 0), ("ok", 0), ("EVAL_SCORE=1.0", 0)])
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            runner.docker_run("a", "b", "c", "img")

        # Assert
        env = client.containers.run.call_args.kwargs["environment"]
        assert env["ADO_PAT"] == azure_devops_pat

    def test_omits_ado_pat_env_when_azure_devops_pat_unset(
        self, claude_token, make_docker_client, monkeypatch
    ):
        # Arrange — blank tokens are omitted, matching GH_TOKEN behaviour.
        monkeypatch.setattr("src.docker_runner.settings.AZURE_DEVOPS_PAT", "")
        client = make_docker_client([("ok", 0), ("ok", 0), ("EVAL_SCORE=1.0", 0)])
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            runner.docker_run("a", "b", "c", "img")

        # Assert
        env = client.containers.run.call_args.kwargs["environment"]
        assert "ADO_PAT" not in env


# --------------------------------------------------------------------------- #
# D. health_check — pre-flight agent/model probe (no streaming daemon)
# --------------------------------------------------------------------------- #


class TestHealthCheck:
    """The pre-flight probe that decides UNHEALTHY vs FAILED before any eval.

    The split lives in how stdout markers vs exit codes map to outcomes:
      - exit 0 + HEALTHY=False   -> HealthCheckResult(healthy=False)    (UNHEALTHY)
      - exit 0 + HEALTHY=True    -> HealthCheckResult(healthy=True)     (run)
      - non-zero / timeout exit  -> raise RuntimeError/TimeoutError      (FAILED)

    H1 guards the regression this whole thing exists for: the deepseek-v4-flash
    case where the agent CLI prints an error and exits 0, which the old exit-code
    gate silently scored as a zero pass. H4 guards the split's other half — a
    real in-container crash must still become FAILED, never get mis-parsed as
    UNHEALTHY.
    """

    def test_pid_namespace_isolation_uses_same_container_options_as_eval(
        self, claude_token, health_timeout, monkeypatch
    ):
        # Arrange
        monkeypatch.setattr("src.docker_runner.settings.AGENT_PID_NAMESPACE_ISOLATION", True)
        client = _fake_exec_run_client((0, b"HEALTHY=True\n"))
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            runner.health_check("img")

        # Assert
        options = client.containers.run.call_args.kwargs
        assert options["security_opt"] == ["seccomp=unconfined"]
        assert options["environment"]["AGENTSHELL_ISOLATION_POLICY"] == "linux-pid-namespace"

    def test_health_startup_failure_cleans_staged_credentials(self, opencode_creds):
        # Arrange
        client = _fake_exec_run_client((0, b"HEALTHY=True\n"))
        orphan = mock.Mock()
        get_calls = 0

        def get_container(_name):
            nonlocal get_calls
            get_calls += 1
            if get_calls == 1:
                raise docker.errors.NotFound("absent")
            return orphan

        client.containers.get.side_effect = get_container
        client.containers.run.side_effect = RuntimeError("container launch failed")
        runner = DockerRunner(AgentType.OPENCODE, "model")

        # Act / Assert
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            with pytest.raises(RuntimeError, match="container launch failed"):
                runner.health_check("img")
        assert runner._temp_dirs
        assert all(not directory.exists() for directory in runner._temp_dirs)
        orphan.remove.assert_called_once_with(force=True)

    def test_unhealthy_verdict_parses_from_markers_and_does_not_raise(
        self, claude_token, health_timeout
    ):
        # Arrange — the deepseek regression: CLI printed an error and exited 0.
        # The verdict is read from stdout markers, not the exit code.
        client = _fake_exec_run_client(
            (0, b"HEALTHY=False\nEXCEPTION=Unexpected server error from provider")
        )
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            result = runner.health_check("img")

        # Assert — returned, not raised; the engine will mark UNHEALTHY and skip
        assert result.healthy is False
        assert "Unexpected server error" in (result.exception or "")

    def test_health_output_redacts_capability_values(self, claude_token, health_timeout, caplog):
        # Arrange
        secret = 'health"secret'
        profile = CapabilityProfile(
            mcp_servers=(
                {
                    "name": "server",
                    "type": "stdio",
                    "command": "server",
                    "env": {"TOKEN": secret},
                },
            )
        )
        client = _fake_exec_run_client((2, f"health failed: {secret}".encode()))
        client._container.stop.side_effect = RuntimeError(f"stop failed: {secret}")
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model", capability_profile=profile)

        # Act / Assert
        with caplog.at_level(logging.INFO, logger="src.docker_runner"):
            with mock.patch("src.docker_runner.docker.from_env", return_value=client):
                with pytest.raises(RuntimeError) as error:
                    runner.health_check("img")
        assert secret not in str(error.value)
        assert secret not in caplog.text

    def test_nonzero_exit_raises_runtimeerror_not_unhealthy(self, claude_token, health_timeout):
        # Arrange — a real in-container crash (import error, asyncio panic). This
        # is a harness problem, not 'the model backend is down today', so it must
        # raise (-> FAILED) rather than return an unhealthy verdict.
        client = _fake_exec_run_client((2, b"Traceback (most recent call last):\n  Boom"))
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act / Assert
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            with pytest.raises(RuntimeError, match="health crashed"):
                runner.health_check("img")
