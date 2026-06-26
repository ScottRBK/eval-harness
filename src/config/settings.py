from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):

    model_config = SettingsConfigDict(
        env_prefix="EVAL_HARNESS_",
        env_file=".env",
        extra="ignore")
    
    CLAUDE_CODE_OAUTH_TOKEN: str = ""
    OPENCODE_CREDENTIALS_LOC: str = "~/.local/share/opencode/auth.json"
    COPILOT_MOUNT: str = ""
    CODEX_MOUNT: str = ""

    OUTPUT_DIR: str = "output"
    LOG_LEVEL: str = "DEBUG"
    DOCKER_LOG_LEVEL: str = "WARNING"
    URLLIB3_LOG_LEVEL: str = "WARNING"

    MAX_AGENT_CONCURRENCY: int = 4 

settings = Settings()
