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

    LOG_DIR: str = "logs"
    LOG_LEVEL: str = "DEBUG"

settings = Settings()
