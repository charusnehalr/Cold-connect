from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # --- Required secrets ---
    telegram_bot_token: str
    groq_api_key: str

    # --- Service URLs ---
    mcp_server_url: str = "http://localhost:8080/mcp"

    # --- Paths ---
    data_dir: Path = Path("./data")
    log_dir: Path = Path("./logs")
    log_level: str = "INFO"

    # --- LinkedIn limits ---
    linkedin_message_char_limit: int = 300
    mcp_call_delay_seconds: float = 2.0
    mcp_call_timeout_seconds: int = 30
    max_people_per_company: int = 5
    max_retries: int = 2

    # --- Pipeline limits ---
    pipeline_timeout_seconds: int = 180

    # --- Groq models ---
    groq_model_light: str = "llama-3.1-8b-instant"
    groq_model_heavy: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    groq_light_max_input_tokens: int = 2000

    # --- Tracker ---
    followup_days_threshold: int = 5

    @property
    def tracker_path(self) -> Path:
        return self.data_dir / "tracker.json"

    @property
    def user_config_path(self) -> Path:
        return self.data_dir / "user_config.json"


settings = Settings()
