import io
import json
import logging
import os
import shlex
import stat
import tarfile
from types import SimpleNamespace

import docker
from urllib.parse import quote

from src.failure_diagnostics import (
    TRACE_PATH,
    capture_failure_diagnostics,
    diagnostic_attempt_dir,
)
from src.helpers.redaction import redact_secrets


def _trace_archive(contents: bytes) -> bytes:
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        info = tarfile.TarInfo("agent-shell-trace.log")
        info.size = len(contents)
        tar.addfile(info, io.BytesIO(contents))
    return archive.getvalue()


def test_diagnostic_attempt_dir_is_deterministic_and_safe(tmp_path):
    # Arrange
    model = "provider/model with spaces"

    # Act
    first = diagnostic_attempt_dir(
        tmp_path,
        agent_type="claude_code",
        agent_model=model,
        effort="high",
        eval_number=7,
        run_number=1,
        attempt_number=1,
    )
    second = diagnostic_attempt_dir(
        tmp_path,
        agent_type="claude_code",
        agent_model=model,
        effort="high",
        eval_number=7,
        run_number=1,
        attempt_number=1,
    )

    # Assert
    assert first == second
    assert first == (
        tmp_path
        / "diagnostics"
        / "claude_code_provider_model_with_spaces_high"
        / "eval-07"
        / "run-01"
        / "attempt-01"
    )


def test_diagnostic_attempt_dir_includes_agent_variant(tmp_path):
    # Arrange / Act
    attempt_dir = diagnostic_attempt_dir(
        tmp_path,
        agent_type="pi",
        agent_model="model",
        effort=None,
        agent_id="with-extension",
        capability_profile="pi-tools",
        eval_number=1,
        run_number=1,
        attempt_number=1,
    )

    # Assert
    assert attempt_dir == (
        tmp_path / "diagnostics" / "pi_model_with-extension" / "eval-01" / "run-01" / "attempt-01"
    )


def test_capture_writes_failure_trace_and_safe_container_inspect(tmp_path):
    # Arrange
    attempt_dir = diagnostic_attempt_dir(
        tmp_path,
        agent_type="claude_code",
        agent_model="model",
        effort=None,
        eval_number=7,
        run_number=1,
        attempt_number=1,
    )
    container = SimpleNamespace(
        attrs={
            "Id": "container-id",
            "Name": "/eval-container",
            "Created": "2026-01-01T00:00:00Z",
            "Image": "image-id",
            "State": {"Status": "exited", "ExitCode": 1},
            "Config": {"Env": ["CLAUDE_CODE_OAUTH_TOKEN=secret"]},
            "Mounts": [{"Source": "/host/workspace", "Destination": "/workspace"}],
        },
        get_archive=lambda path: (iter([_trace_archive(b"Raw event: {'marker': 'seen'}\n")]), {}),
        reload=lambda: None,
    )

    # Act
    saved = capture_failure_diagnostics(
        attempt_dir=attempt_dir,
        phase="act",
        error=RuntimeError("act failed"),
        exit_code=1,
        timed_out=False,
        container=container,
        log=logging.getLogger("test.failure-diagnostics"),
    )

    # Assert
    assert saved is True
    manifest = json.loads((attempt_dir / "failure.json").read_text())
    assert manifest == {
        "phase": "act",
        "exception_type": "RuntimeError",
        "exception_message": "act failed",
        "exit_code": 1,
        "timed_out": False,
        "timestamp": manifest["timestamp"],
    }
    assert (attempt_dir / "agent-shell-trace.log").read_text() == (
        "Raw event: {'marker': 'seen'}\n"
    )
    inspect = json.loads((attempt_dir / "container-inspect.json").read_text())
    assert inspect["id"] == "container-id"
    assert inspect["state"]["ExitCode"] == 1
    assert "Config" not in inspect
    assert "Mounts" not in inspect
    assert "secret" not in (attempt_dir / "container-inspect.json").read_text()
    assert stat.S_IMODE(os.stat(attempt_dir / "failure.json").st_mode) == 0o600
    assert stat.S_IMODE(os.stat(attempt_dir / "agent-shell-trace.log").st_mode) == 0o600


def test_capture_redacts_secret_from_manifest_and_trace(tmp_path):
    # Arrange
    secret = "sentinel-diagnostic-secret"
    attempt_dir = tmp_path / "attempt"
    container = SimpleNamespace(
        attrs={"Id": "container-id", "State": {}},
        get_archive=lambda path: (
            iter([_trace_archive(f"trace contains {secret}".encode())]),
            {},
        ),
        reload=lambda: None,
    )

    # Act
    capture_failure_diagnostics(
        attempt_dir=attempt_dir,
        phase="capabilities",
        error=RuntimeError(f"setup failed with {secret}"),
        exit_code=1,
        timed_out=False,
        container=container,
        log=logging.getLogger("test.failure-diagnostics"),
        redactions=(secret,),
    )

    # Assert
    assert secret not in (attempt_dir / "failure.json").read_text()
    assert secret not in (attempt_dir / "agent-shell-trace.log").read_text()
    assert "[REDACTED]" in (attempt_dir / "agent-shell-trace.log").read_text()


def test_redaction_handles_multiline_and_escaped_secret_values():
    # Arrange
    secret = "first-line\nsecond-line"

    # Act
    escaped = secret.encode("unicode_escape").decode()
    actual = redact_secrets(
        f"raw={secret}; repr={secret!r}; json={escaped!r}",
        (secret,),
    )

    # Assert
    assert secret not in actual
    assert "first-line" not in actual
    assert "second-line" not in actual
    assert actual.count("[REDACTED]") == 3


def test_redaction_handles_json_quotes_and_unicode_escaped_values():
    # Arrange / Act
    for secret in ('quote"secret', "secrét", "both'and\"quotes", "only'quote"):
        escaped = secret.encode("unicode_escape").decode()
        encoded = json.dumps(secret)
        encoded_inner = encoded[1:-1]
        repr_message = repr(f"API_KEY={secret}")
        python_single_escaped = secret.replace("\\", "\\\\").replace("'", "\\'")
        actual = redact_secrets(
            f"raw={secret}; json={encoded}; inner={encoded_inner}; "
            f"unicode={escaped!r}; repr={repr_message}; "
            f'context="API_KEY"={python_single_escaped}',
            (secret,),
        )

        # Assert
        assert secret not in actual
        assert encoded not in actual
        assert encoded_inner not in actual
        assert escaped not in actual
        assert repr_message not in actual
        assert python_single_escaped not in actual


def test_redaction_handles_shell_and_url_encoded_values():
    # Arrange
    secret = "only'quote/value"
    message = f"shell={shlex.quote(secret)} url={quote(secret, safe='')}"

    # Act
    actual = redact_secrets(message, (secret,))

    # Assert
    assert secret not in actual
    assert shlex.quote(secret) not in actual
    assert quote(secret, safe="") not in actual


def test_capture_records_signal_name_and_omits_unknown_exit_code(tmp_path):
    # Arrange
    attempt_dir = tmp_path / "attempt"

    # Act
    capture_failure_diagnostics(
        attempt_dir=attempt_dir,
        phase="act",
        error=TimeoutError("terminated"),
        exit_code=143,
        timed_out=True,
        container=None,
        log=logging.getLogger("test.failure-diagnostics"),
    )
    unknown_attempt = tmp_path / "unknown"
    capture_failure_diagnostics(
        attempt_dir=unknown_attempt,
        phase="provisioning",
        error=RuntimeError("no container"),
        exit_code=None,
        timed_out=False,
        container=None,
        log=logging.getLogger("test.failure-diagnostics"),
    )

    # Assert
    manifest = json.loads((attempt_dir / "failure.json").read_text())
    assert manifest["exit_code"] == 143
    assert manifest["signal"] == "SIGTERM"
    assert manifest["timed_out"] is True
    unknown_manifest = json.loads((unknown_attempt / "failure.json").read_text())
    assert "exit_code" not in unknown_manifest
    assert "signal" not in unknown_manifest


def test_capture_redacts_container_state_and_capture_errors(tmp_path, caplog, monkeypatch):
    # Arrange
    secret = 'quote"secret'
    attempt_dir = tmp_path / "attempt"
    container = SimpleNamespace(
        attrs={"Id": "container-id", "State": {"Error": secret}},
        get_archive=lambda path: (_ for _ in ()).throw(RuntimeError(json.dumps(secret))),
        reload=lambda: None,
    )

    # Act
    with caplog.at_level(logging.DEBUG, logger="src.failure_diagnostics"):
        capture_failure_diagnostics(
            attempt_dir=attempt_dir,
            phase="capabilities",
            error=RuntimeError("setup failed"),
            exit_code=1,
            timed_out=False,
            container=container,
            log=logging.getLogger("src.failure_diagnostics"),
            redactions=(secret,),
        )

    # Assert
    assert secret not in (attempt_dir / "container-inspect.json").read_text()
    assert secret not in caplog.text
    assert "[REDACTED]" in (attempt_dir / "container-inspect.json").read_text()


def test_missing_trace_is_normal_and_does_not_copy_other_files(tmp_path):
    # Arrange
    attempt_dir = tmp_path / "attempt"
    workspace = tmp_path / "workspace-secret.txt"
    workspace.write_text("do not copy")

    def missing_archive(path):
        assert path == TRACE_PATH
        raise docker.errors.NotFound("trace does not exist")

    container = SimpleNamespace(
        attrs={"Id": "container-id", "State": {}},
        get_archive=missing_archive,
        reload=lambda: None,
    )

    # Act
    capture_failure_diagnostics(
        attempt_dir=attempt_dir,
        phase="arrange",
        error=RuntimeError("arrange failed"),
        exit_code=1,
        timed_out=False,
        container=container,
        log=logging.getLogger("test.failure-diagnostics"),
    )

    # Assert
    assert (attempt_dir / "failure.json").is_file()
    assert not (attempt_dir / "agent-shell-trace.log").exists()
    assert not (attempt_dir / "workspace-secret.txt").exists()
    assert not (attempt_dir / "credentials.json").exists()


def test_disabled_capture_creates_no_artifacts(tmp_path):
    # Arrange
    attempt_dir = tmp_path / "attempt"

    # Act
    saved = capture_failure_diagnostics(
        attempt_dir=None,
        phase="act",
        error=RuntimeError("ignored"),
        exit_code=1,
        timed_out=False,
        container=None,
        log=logging.getLogger("test.failure-diagnostics"),
    )

    # Assert
    assert saved is False
    assert not attempt_dir.exists()
