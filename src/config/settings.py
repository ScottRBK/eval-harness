from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EVAL_HARNESS_", env_file=".env", extra="ignore")

    CLAUDE_CODE_OAUTH_TOKEN: str = ""
    OPENCODE_CREDENTIALS_LOC: str = "~/.local/share/opencode/auth.json"
    CODEX_CREDENTIALS_LOC: str = "~/.codex/auth.json"
    PI_CREDENTIALS_LOC: str = "~/.pi/agent/auth.json"
    COPILOT_GITHUB_TOKEN: str = ""
    GITHUB_TOKEN: str = ""

    OUTPUT_DIR: str = "output"
    RESULTS_FILENAME: str = "results.json"
    CSV_RESULTS_FILENAME: str = "results.csv"
    LOG_LEVEL: str = "DEBUG"
    DOCKER_LOG_LEVEL: str = "WARNING"
    URLLIB3_LOG_LEVEL: str = "WARNING"

    ### Evaluation Run Configuration ###
    EVALS_DIRS: str = "example_evals"  # os.pathsep-separated eval roots, searched in order
    BASE_IMAGE: str = "eval-harness:latest"
    MAX_AGENT_CONCURRENCY: int = 4
    HEALTH_CHECK_TIMEOUT_SECONDS: int = 3 * 60
    ARRANGE_TIMEOUT_SECONDS: int = 60 * 60
    ACT_TIMEOUT_SECONDS: int = 60 * 60
    SCORE_TIMEOUT_SECONDS: int = 10 * 60


settings = Settings()
