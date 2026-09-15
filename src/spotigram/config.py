from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from spotigram.access import ADMIN_HANDLE, HARDCODED_ADMIN_ID


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str = ""
    telegram_admin_ids: str = str(HARDCODED_ADMIN_ID)
    telegram_api_id: str = ""
    telegram_api_hash: str = ""
    telegram_bot_api_url: str = ""
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    spotify_redirect_uri: str = "http://127.0.0.1:8888/callback"
    spotigram_secret: str = ""
    max_concurrent_jobs: int = 2
    max_parallel_tracks: int = 3
    max_tracks_per_job: int = 200
    warn_tracks: int = 40
    zip_max_mb: int = 1900
    admin_handle: str = ADMIN_HANDLE
    data_dir: Path = Path("data")
    oauth_host: str = "0.0.0.0"
    oauth_port: int = 8888

    @property
    def admin_ids(self) -> list[int]:
        ids: list[int] = []
        for part in self.telegram_admin_ids.split(","):
            part = part.strip()
            if part:
                ids.append(int(part))
        if HARDCODED_ADMIN_ID not in ids:
            ids.insert(0, HARDCODED_ADMIN_ID)
        return ids

    @property
    def zip_max_bytes(self) -> int:
        return self.zip_max_mb * 1024 * 1024

    @property
    def db_path(self) -> Path:
        return self.data_dir / "spotigram.db"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def uses_local_bot_api(self) -> bool:
        return bool(self.telegram_bot_api_url.strip())

    @property
    def bot_api_base(self) -> str:
        return self.telegram_bot_api_url.rstrip("/") + "/bot"

    @property
    def bot_api_file_base(self) -> str:
        return self.telegram_bot_api_url.rstrip("/") + "/file/bot"


def load_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.jobs_dir.mkdir(parents=True, exist_ok=True)
    return settings
