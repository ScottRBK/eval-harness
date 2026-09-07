import hashlib
import json
from pathlib import Path
from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit
from agent_shell.models.agent import AgentType
from uuid import UUID
from datetime import datetime

from src.helpers.redaction import redact_secrets


class ResultFormat(StrEnum):
    CSV = "csv"
    JSON = "json"


class AgentEvalStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    UNHEALTHY = "unhealthy"


class EvalExecutionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AgentProvisioning:
    volumes: dict[str, dict[str, str]] = field(default_factory=dict)
    environment: dict[str, str] = field(default_factory=dict)


@dataclass
class DockerRunResult:
    score: float
    time_taken_seconds: float
    total_tokens: int


@dataclass
class Eval:
    number: int
    eval_dir: str
    description: str
    run_count: int
    tags: list[str]


@dataclass
class CapabilityProfile:
    """Capabilities provisioned inside an evaluation container."""

    packages: tuple[str, ...] = ()
    mcp_servers: tuple[dict[str, object], ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.packages and not self.mcp_servers

    def redaction_values(self) -> tuple[str, ...]:
        """Return profile values that must not appear in logs or errors."""
        values = set(self.packages)
        for source in self.packages:
            remote = source[4:] if source.startswith("git:") else source
            parsed = urlsplit(remote)
            has_url_credentials = parsed.password is not None or (
                parsed.username is not None
                and not (parsed.scheme == "ssh" and parsed.username == "git")
            )
            if (
                parsed.scheme in {"https", "http", "ssh", "git"}
                and parsed.netloc
                and has_url_credentials
            ):
                _add_url_redactions(values, remote)
        for server in self.mcp_servers:
            for field_name in ("command", "url", "args", "env", "headers"):
                raw = server.get(field_name)
                if isinstance(raw, dict):
                    values.update(str(value) for value in raw.values() if value)
                elif isinstance(raw, (list, tuple)):
                    values.update(str(value) for value in raw if value)
                elif raw:
                    values.add(str(raw))
            if isinstance(server.get("url"), str):
                _add_url_redactions(values, server["url"])
        return tuple(sorted(values, key=len, reverse=True))

    def manifest(self) -> dict[str, object]:
        """Return a result-safe description without MCP secret values."""
        secrets = {
            value
            for server in self.mcp_servers
            for field_name in ("env", "headers")
            for value in (server.get(field_name, {}) or {}).values()
            if isinstance(value, str) and value
        }

        return {
            "packages": [
                {
                    "source": _redact_package_source(source, secrets),
                    "sha256": hashlib.sha256(source.encode()).hexdigest(),
                }
                for source in self.packages
            ],
            "mcp_servers": [_mcp_manifest(server, secrets) for server in self.mcp_servers],
        }


def _add_url_redactions(values: set[str], raw_url: str) -> None:
    """Add URL components that third-party errors may print separately."""
    parsed = urlsplit(raw_url)
    components = [
        parsed.username,
        parsed.password,
        parsed.path,
        parsed.path.lstrip("/"),
        parsed.query,
        parsed.fragment,
    ]
    components.extend(value for _, value in parse_qsl(parsed.query, keep_blank_values=True))
    if parsed.path:
        components.append(parsed.path.rsplit("/", 1)[-1])
    for component in components:
        if component:
            values.add(component)
            decoded = unquote(component)
            if decoded:
                values.add(decoded)
    if parsed.username or parsed.password:
        repository_path = parsed.path.partition("@")[0]
        values.add(urlunsplit((parsed.scheme, parsed.netloc, repository_path, "", "")))


def _redact_text(value: str, secrets: set[str]) -> str:
    return redact_secrets(value, secrets)


def _redact_package_source(source: str, secrets: set[str]) -> str:
    source = _redact_text(source, secrets)
    prefix = ""
    remote = source
    if source.startswith("git:") and "://" in source[4:]:
        prefix, remote = "git:", source[4:]
    parsed = urlsplit(remote)
    if parsed.scheme in {"https", "http", "ssh", "git"} and parsed.netloc:
        host = parsed.hostname or ""
        try:
            port = parsed.port
        except ValueError:
            port = None
        if port is not None:
            host = f"{host}:{port}"
        remote = urlunsplit((parsed.scheme, host, parsed.path, "", ""))
        return prefix + remote
    return source


def _mcp_manifest_url(url: str) -> tuple[str, str | None]:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    try:
        port = parsed.port
    except ValueError:
        port = None
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if port is not None:
        host = f"{host}:{port}"
    origin = urlunsplit((parsed.scheme, host, "", "", ""))
    path_hash = hashlib.sha256(parsed.path.encode()).hexdigest() if parsed.path else None
    return origin, path_hash


def _mcp_manifest(server: dict[str, object], secrets: set[str]) -> dict[str, object]:
    manifest: dict[str, object] = {
        "name": _redact_text(str(server["name"]), secrets),
        "type": _redact_text(str(server["type"]), secrets),
        "env_keys": sorted((server.get("env", {}) or {}).keys()),
        "header_keys": sorted((server.get("headers", {}) or {}).keys()),
    }
    for field_name in ("command", "url"):
        if value := server.get(field_name):
            if field_name == "url":
                value, path_hash = _mcp_manifest_url(str(value))
                if path_hash is not None:
                    manifest["url_path_sha256"] = path_hash
            else:
                value = _redact_text(str(value), secrets)
            manifest[field_name] = value
    if args := server.get("args"):
        serialized_args = json.dumps(
            [str(arg) for arg in args],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        manifest["args_count"] = len(args)
        manifest["args_sha256"] = hashlib.sha256(serialized_args.encode()).hexdigest()
    return manifest


@dataclass
class AgentConfig:
    agent_type: AgentType
    agent_model: str
    effort: str | None = None
    processing_group: str | None = None
    eval_retries: int = 0
    agent_id: str | None = None
    capability_profile: str = "base"
    capability_manifest: dict[str, object] = field(default_factory=dict)


@dataclass
class EvalExecution:
    id: UUID
    eval: Eval
    agent_config: AgentConfig
    total_tokens: int | None = None
    score: float | None = None
    time_taken_seconds: float | None = None
    date_executed: datetime | None = None
    status: EvalExecutionStatus = EvalExecutionStatus.PENDING
    retries_used: int = 0
    last_error: str | None = None


@dataclass
class AgentEvalExecution:
    agent_config: AgentConfig
    total_score: float
    total_tokens: int
    total_time_taken_seconds: float
    evals_executions: list[EvalExecution]
    status: AgentEvalStatus


@dataclass
class EvalSession:
    session_id: UUID
    evals: list[Eval]
    agents: list[AgentConfig]
    result_format: ResultFormat
    eval_file: str
    run_dir: Path
    capability_profiles: dict[str, CapabilityProfile] = field(default_factory=dict)


@dataclass
class EvalRun:
    eval_runs: list[EvalExecution]
    date_executed: datetime
    agents: list[AgentConfig]
