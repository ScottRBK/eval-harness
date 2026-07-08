from dataclasses import dataclass, field
from enum import StrEnum
from agent_shell.models.agent import AgentType
from uuid import UUID
from datetime import datetime


class ResultFormat(StrEnum):
    CSV = "csv"
    JSON = "json"


class AgentEvalStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    UNHEALTHY = "unhealthy"


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
class AgentConfig:
    agent_type: AgentType
    agent_model: str
    effort: str | None = None
    processing_group: str | None = None


@dataclass
class EvalExecution:
    id: UUID
    eval: Eval
    agent_config: AgentConfig
    total_tokens: int | None = None
    score: float | None = None
    time_taken_seconds: float | None = None
    date_executed: datetime | None = None


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


@dataclass
class EvalRun:
    eval_runs: list[EvalExecution]
    date_executed: datetime
    agents: list[AgentConfig]
