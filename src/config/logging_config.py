import logging 
import threading
from pathlib import Path 
from datetime import datetime
from uuid import UUID 

from settings import settings 
from src.models import AgentConfig

_FMT = logging.Formatter("%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s")

def configure_logging(session_id: UUID) -> Path:
    run_dir = Path(settings.OUTPUT_DIR) / "datetime.now():%Y%m%d_%H%M%S}_{session_id}.log"
    run_dir.mkdir(parents=True, exist_ok=True)

    handler = logging.FileHandler(filename=run_dir / "session.log", encoding="utf-8")
    handler.setFormatter(_FMT)

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL))
    root_logger.addHandler(handler)

    logging.getLogger("docker").setLevel(settings.DOCKER_LOG_LEVEL)
    logging.getLogger("urllib3").setLevel(settings.URLLIB3_LOG_LEVEL)

    return run_dir 


