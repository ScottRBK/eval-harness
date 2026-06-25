"""Logging setup for an eval run.

Every run gets its own directory under ``OUTPUT_DIR`` (the same place the results
JSON will land). ``session.log`` is the catch-all - every record from every agent
thread, interleaved. Each agent additionally writes to its own ``<label>.log`` via
a dedicated named logger that has that file attached; because those loggers
propagate, their records also reach ``session.log`` for free. Routing is "the
logger you write to owns its file" - no thread-locals, no record filtering.
"""

import logging
from pathlib import Path
from datetime import datetime

from src.config.settings import settings

_FMT = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s"
)


def agent_label(cfg) -> str:
    """Stable per-agent label used for both routing and the log filename."""
    parts = [cfg.agent_type.value, cfg.agent_model]
    if cfg.effort:
        parts.append(cfg.effort)
    return "_".join(parts)


def configure_logging(session_id) -> Path:
    """Create OUTPUT_DIR/<run>/ with a catch-all session log. Returns the run dir."""
    run_dir = Path(settings.OUTPUT_DIR) / f"{datetime.now():%Y%m%d_%H%M%S}_{session_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    handler = logging.FileHandler(run_dir / "session.log", encoding="utf-8")
    handler.setFormatter(_FMT)

    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.LOG_LEVEL))
    root.addHandler(handler)

    logging.getLogger("docker").setLevel(settings.DOCKER_LOG_LEVEL)
    logging.getLogger("urllib3").setLevel(settings.URLLIB3_LOG_LEVEL)
    return run_dir


def agent_logger(cfg, run_dir) -> logging.Logger:
    """A logger that writes to that agent's own file (and bubbles to session.log)."""
    label = agent_label(cfg)
    log = logging.getLogger(f"eval.agent.{label}")
    if not log.handlers:  # idempotent if the agent's worker thread is reused
        handler = logging.FileHandler(Path(run_dir) / f"{label}.log", encoding="utf-8")
        handler.setFormatter(_FMT)
        log.addHandler(handler)
    return log
