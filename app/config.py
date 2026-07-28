"""
Centralized application configuration.
All values can be overridden via environment variables or a .env file.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "OmniGrab"
    ENVIRONMENT: str = "production"  # production | development
    DEBUG: bool = False

    # CORS
    ALLOWED_ORIGINS: list[str] = ["*"]

    # Filesystem
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    TEMP_DIR: Path = BASE_DIR / "downloads_tmp"

    # Limits & housekeeping
    MAX_CONCURRENT_DOWNLOADS: int = 4
    TASK_TTL_SECONDS: int = 60 * 30          # how long a finished task/file survives
    CLEANUP_INTERVAL_SECONDS: int = 60 * 5   # background sweep interval
    MAX_VIDEO_DURATION_SECONDS: int = 60 * 60 * 3  # 3 hours safety cap
    RATE_LIMIT: str = "20/minute"

    # yt-dlp
    COOKIES_FILE: str | None = None          # optional path to cookies.txt for gated content
    SOCKET_TIMEOUT: int = 20

    def ensure_dirs(self) -> None:
        self.TEMP_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
