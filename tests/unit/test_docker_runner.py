"""Unit tests for DockerRunner.

Hermetic and CI-safe: the docker daemon is mocked (see conftest), staging dirs
are redirected under pytest's ``tmp_path`` so nothing leaks, and ``settings`` is
patched so no host secrets or files are required.
"""

import stat
import tempfile
from pathlib import Path
from unittest import mock

import pytest
from agent_shell.models.agent import AgentType

from src.docker_runner import DockerRunner


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
    monkeypatch.setattr(
        "src.docker_runner.settings.OPENCODE_CREDENTIALS_LOC", str(creds)
    )
    return creds


# --------------------------------------------------------------------------- #
# A. _staged_mount — real filesystem behaviour via tmp_path
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

    def test_sets_mode_0o644_on_copied_files(self, tmp_path):
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
        assert mode == 0o644

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

    def test_opencode_volumes_include_credentials_and_config_binds(
        self, opencode_creds
    ):
        # Arrange
        runner = DockerRunner(AgentType.OPENCODE, "model")

        # Act
        volumes = runner._setup_opencode_volumes()

        # Assert — both the host-secret mount and the repo-config mount present
        binds = {spec["bind"] for spec in volumes.values()}
        assert "/home/node/.local/share/opencode" in binds
        assert "/home/node/.config/opencode" in binds


# --------------------------------------------------------------------------- #
# C. docker_run — mocked docker client
# --------------------------------------------------------------------------- #


class TestDockerRun:
    def test_parses_score_from_last_eval_score_line(
        self, claude_token, make_docker_client
    ):
        # Arrange — a stale early score and trailing noise must not win
        score_output = "EVAL_SCORE=0.10\nnoise\nEVAL_SCORE=0.85\ntrailing noise"
        client = make_docker_client([("ok", 0), ("ok", 0), (score_output, 0)])
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            score, elapsed = runner.docker_run("a", "b", "c", "img")

        # Assert
        assert score == 0.85
        assert elapsed >= 0

    def test_score_defaults_to_zero_without_eval_score_line(
        self, claude_token, make_docker_client
    ):
        # Arrange
        client = make_docker_client(
            [("ok", 0), ("ok", 0), ("no score here\njust logs", 0)]
        )
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            score, _ = runner.docker_run("a", "b", "c", "img")

        # Assert
        assert score == 0.0

    def test_malformed_score_line_raises_friendly_error(
        self, claude_token, make_docker_client
    ):
        # Arrange — an EVAL_SCORE= line that isn't a number
        client = make_docker_client([("ok", 0), ("ok", 0), ("EVAL_SCORE=pass", 0)])
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act / Assert — friendly error naming the offending line, not a raw ValueError
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            with pytest.raises(RuntimeError, match="EVAL_SCORE=pass"):
                runner.docker_run("a", "b", "c", "img")

    def test_nonzero_phase_exit_raises_runtimeerror(
        self, claude_token, make_docker_client
    ):
        # Arrange — arrange phase exits non-zero
        client = make_docker_client([("boom", 1), ("ok", 0), ("EVAL_SCORE=1.0", 0)])
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act / Assert
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            with pytest.raises(RuntimeError):
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

    def test_stream_response_closed_even_when_streaming_raises(
        self, claude_token, make_docker_client
    ):
        # Arrange — first phase's stream blows up mid-iteration
        client = make_docker_client([("ok", 0), ("ok", 0), ("EVAL_SCORE=1.0", 0)])
        client._streams[0]._raise = True
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            score, _ = runner.docker_run("a", "b", "c", "img")

        # Assert — streaming error is swallowed, every stream is closed, run finishes
        assert score == 1.0
        assert all(s._response.close.called for s in client._streams)

    def test_stale_container_removed_before_run(
        self, claude_token, make_docker_client
    ):
        # Arrange — a stale container exists this time
        client = make_docker_client([("ok", 0), ("ok", 0), ("EVAL_SCORE=1.0", 0)])
        client.containers.get.side_effect = None
        stale = mock.Mock()
        client.containers.get.return_value = stale
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            runner.docker_run("a", "b", "c", "img")

        # Assert
        client.containers.get.assert_called_once_with("eval_harness")
        stale.remove.assert_called_once_with(force=True)

    def test_missing_stale_container_is_ignored(
        self, claude_token, make_docker_client
    ):
        # Arrange — default fake client raises NotFound on get
        client = make_docker_client([("ok", 0), ("ok", 0), ("EVAL_SCORE=0.5", 0)])
        runner = DockerRunner(AgentType.CLAUDE_CODE, "model")

        # Act
        with mock.patch("src.docker_runner.docker.from_env", return_value=client):
            score, _ = runner.docker_run("a", "b", "c", "img")

        # Assert — NotFound swallowed, run proceeds normally
        assert score == 0.5
