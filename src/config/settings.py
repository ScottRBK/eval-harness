from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):

    model_config = SettingsConfigDict(
        env_prefix="EVAL_HARNESS",
        env_file=".env",
        extra="ignore")
    
    CLAUDE_CODE_MOUNT: str = "~/.claude:/root/.claude:ro"
    OPENCODE_MOUNT: str = ""
    COPILOT_MOUNT: str = ""
    GEMINI_MOUNT: str = ""
    CODEX_MOUNT: str = ""

    LOG_FILENAME: str = "eval_harness.log"
    LOG_LEVEL: str = "DEBUG"

settings = Settings()
