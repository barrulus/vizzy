"""Configuration management for Vizzy"""

from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    database_url: str
    nix_config_path: Path
    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = False

    model_config = {
        "env_prefix": "VIZZY_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


settings = Settings()
