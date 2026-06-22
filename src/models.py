from dataclasses import dataclass 
from agent_shell.models.agent import AgentType
from uuid import UUID
from datetime import datetime 

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

@dataclass
class EvalExecution: 
    id: UUID 
    eval_number: int 
    agent_config: AgentConfig
    total_tokens: float | None = None
    score: float | None = None 
    time_taken_seconds: float | None = None 
    date_executed: datetime | None = None

@dataclass
class AgentEvalExecution:
    agent_config: AgentConfig
    total_score: float 
    total_tokens: float
    total_time_taken_seconds: float
    evals_executions: list[EvalExecution]

@dataclass 
class EvalConfig:
    evals: list[Eval]
    agents: list[AgentConfig]

@dataclass 
class EvalRun:
    eval_runs: list[EvalExecution]
    date_executed: datetime 
    agents: list[AgentConfig]


