"""Environment-backed FuseBench settings."""

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or a local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    typesafe_api_key: str | None = None
    jev_model: str = "jev-latest"
    jev_hard_cap_usd: float = Field(default=1.0, gt=0)
    terra_model: str = "gpt-5.6-terra"
    terra_reasoning_effort: Literal["medium"] = "medium"
    terra_tool_protocol: Literal["dynamic_tools"] = "dynamic_tools"
    fusebench_artifact_dir: Path = Path("artifacts")
    fusebench_log_level: str = "INFO"


def get_settings() -> Settings:
    """Return settings without caching secrets in module globals."""

    return Settings()
