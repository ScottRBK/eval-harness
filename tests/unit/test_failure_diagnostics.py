import io
import json
import logging
import os
import stat
import tarfile
from types import SimpleNamespace

import docker

from src.failure_diagnostics import (
    TRACE_PATH,
    capture_failure_diagnostics,
    diagnostic_attempt_dir,
)


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
