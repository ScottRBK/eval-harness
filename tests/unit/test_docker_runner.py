"""Unit tests for DockerRunner.

Hermetic and CI-safe: the docker daemon is mocked (see conftest), staging dirs
are redirected under pytest's ``tmp_path`` so nothing leaks, and ``settings`` is
patched so no host secrets or files are required.
"""

import stat
import tempfile
from pathlib import Path
from unittest import mock

import docker
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

    def test_pi_provisions_auth_volume_not_environment(self, pi_creds):
        # Arrange
        runner = DockerRunner(AgentType.PI, "model")

        # Act
        prov = runner._provision_agent()

        # Assert — Pi authenticates via its staged auth.json, not an env var
        assert prov.environment == {}
        binds = {spec["bind"] for spec in prov.volumes.values()}
        assert "/home/node/.pi/agent" in binds

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

    def test_nonzero_phase_exit_raises_runtimeerror(self, claude_token, make_docker_client):
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
