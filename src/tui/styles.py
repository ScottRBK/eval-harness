
from src.models import AgentEvalStatus

PALETTE = {
    "border": "#9aa3b2",
    "header": "#7f8796",
    "label": "#7f8796",
    "value": "#d7dce5",
    "accent": "#9bbcff",
    "accent_alt": "#82aaff",
    "good": "#4ff3a5",
    "bad": "#ff6b6b",
    "warn": "#ffb454",
    "muted": "#8b93a1",
}

STATUS_STYLES = {
    AgentEvalStatus.PENDING: f"dim {PALETTE['muted']}",
    AgentEvalStatus.PROCESSING: PALETTE["accent"],
    AgentEvalStatus.COMPLETED: f"bold {PALETTE['good']}",
    AgentEvalStatus.UNHEALTHY: f"bold {PALETTE['warn']}",
    AgentEvalStatus.FAILED: f"bold {PALETTE['bad']}",
}
