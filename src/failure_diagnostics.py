"""Opt-in, host-side diagnostics for failed eval attempts."""

import io
import json
import logging
import os
import signal
import tarfile
from datetime import datetime, timezone
from pathlib import Path

from src.helpers.naming import agent_identity
from src.helpers.redaction import redact_secrets

TRACE_ENV = "EVAL_HARNESS_AGENT_SHELL_TRACE_PATH"
TRACE_PATH = "/tmp/eval-harness/agent-shell/agent-shell-trace.log"  # noqa: S108 - container path
_TRACE_FILENAME = Path(TRACE_PATH).name

logger = logging.getLogger(__name__)


def diagnostic_attempt_dir(
    run_dir: Path | None,
    *,
    agent_type: object,
    agent_model: str,
    effort: str | None,
    eval_number: int,
    run_number: int,
    attempt_number: int,
    agent_id: str | None = None,
    capability_profile: str = "base",
) -> Path | None:
    """Return the deterministic host path for one attempt, without creating it."""
    if run_dir is None:
        return None

    variant = agent_id or (None if capability_profile == "base" else capability_profile)
    agent_name = agent_identity(agent_type, agent_model, effort, variant)

    return (
        Path(run_dir)
        / "diagnostics"
        / agent_name
        / f"eval-{eval_number:02d}"
        / f"run-{run_number:02d}"
        / f"attempt-{attempt_number:02d}"
    )


def _signal_name(exit_code: int | None) -> str | None:
    if exit_code is None or not 128 <= exit_code <= 255:
        return None
    try:
        return signal.Signals(exit_code - 128).name
    except ValueError:
        return None


def _secure_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(content)
    os.chmod(path, 0o600)


def _redact_object(value, redactions: tuple[str, ...]):
    if isinstance(value, str):
        return redact_secrets(value, redactions)
    if isinstance(value, dict):
        return {
            redact_secrets(str(key), redactions): _redact_object(item, redactions)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_object(item, redactions) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_object(item, redactions) for item in value)
    return value


def _safe_container_inspect(
    container, redactions: tuple[str, ...] = ()
) -> dict[str, object] | None:
    try:
        container.reload()
    except Exception as error:
        # attrs from container creation may still contain useful state. The caller
        # treats an unavailable inspection as best effort.
        logger.debug("Container reload unavailable: %s", redact_secrets(str(error), redactions))

    attrs = getattr(container, "attrs", None)
    if not isinstance(attrs, dict):
        return None

    result: dict[str, object] = {}
    for source, target in (
        ("Id", "id"),
        ("Name", "name"),
        ("Created", "created"),
        ("Image", "image"),
    ):
        if attrs.get(source) is not None:
            result[target] = _redact_object(attrs[source], redactions)

    state = attrs.get("State")
    if isinstance(state, dict):
        result["state"] = _redact_object(state, redactions)
    return result or None


def _copy_trace(
    container,
    destination: Path,
    redactions: tuple[str, ...] = (),
) -> bool:
    archive_stream, _ = container.get_archive(TRACE_PATH)
    archive = io.BytesIO()
    for chunk in archive_stream:
        archive.write(chunk)
    archive.seek(0)

    with tarfile.open(fileobj=archive, mode="r:*") as tar:
        members = [
            member
            for member in tar.getmembers()
            if member.name in {_TRACE_FILENAME, f"./{_TRACE_FILENAME}"}
        ]
        if len(members) != 1 or not members[0].isreg():
            return False
        source = tar.extractfile(members[0])
        if source is None:
            return False
        trace = source.read().decode("utf-8", errors="replace")
        _secure_write(destination, redact_secrets(trace, redactions).encode())
    return True


def capture_failure_diagnostics(
    *,
    attempt_dir: Path | None,
    phase: str,
    error: BaseException,
    exit_code: int | None,
    timed_out: bool,
    container,
    log: logging.Logger,
    redactions: tuple[str, ...] = (),
) -> bool:
    """Save best-effort diagnostics without ever raising a capture error."""
    if attempt_dir is None:
        return False

    manifest: dict[str, object] = {
        "phase": phase,
        "exception_type": type(error).__name__,
        "exception_message": redact_secrets(str(error), redactions),
        "timed_out": timed_out,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if exit_code is not None:
        manifest["exit_code"] = exit_code
    if signal_name := _signal_name(exit_code):
        manifest["signal"] = signal_name

    try:
        attempt_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(attempt_dir, 0o700)
    except Exception as capture_error:
        log.warning(
            "Could not create failure diagnostics directory %s: %s",
            attempt_dir,
            redact_secrets(str(capture_error), redactions),
        )
        return False

    if container is not None:
        try:
            _copy_trace(container, attempt_dir / _TRACE_FILENAME, redactions)
        except Exception as capture_error:
            # A missing trace is expected when arrange failed before AgentShell ran.
            log.debug(
                "AgentShell trace unavailable for %s: %s",
                attempt_dir,
                redact_secrets(str(capture_error), redactions),
            )

        try:
            inspected = _safe_container_inspect(container, redactions)
            if inspected is not None:
                _secure_write(
                    attempt_dir / "container-inspect.json",
                    (json.dumps(inspected, indent=2) + "\n").encode(),
                )
        except Exception as capture_error:
            log.debug(
                "Container inspection unavailable for %s: %s",
                attempt_dir,
                redact_secrets(str(capture_error), redactions),
            )

    try:
        _secure_write(
            attempt_dir / "failure.json",
            (json.dumps(manifest, indent=2) + "\n").encode(),
        )
    except Exception as capture_error:
        log.warning(
            "Could not save failure diagnostics in %s: %s",
            attempt_dir,
            redact_secrets(str(capture_error), redactions),
        )
        return False

    log.info("Failure diagnostics saved to %s", attempt_dir)
    return True
