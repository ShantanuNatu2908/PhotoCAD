import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
# Load root .env and backend/.env transparently regardless of uvicorn CWD
load_dotenv(_BASE_DIR / ".env", override=False)
load_dotenv(_BASE_DIR / "backend" / ".env", override=False)

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(_BASE_DIR / ".env"), str(_BASE_DIR / "backend" / ".env")),
        extra="ignore",
    )

    PROJECT_NAME: str = "PhotoCAD"
    VERSION: str = "0.1.0"
    API_V1_PREFIX: str = "/api"
    
    # Base paths
    BASE_DIR: Path = _BASE_DIR
    STORAGE_DIR: Path = BASE_DIR / "storage"
    UPLOADS_DIR: Path = STORAGE_DIR / "uploads"
    PROCESSED_DIR: Path = STORAGE_DIR / "processed_edges"
    EXPORTS_DIR: Path = STORAGE_DIR / "cad_exports"
    
    # Database
    DATABASE_URL: str = f"sqlite+aiosqlite:///{STORAGE_DIR.as_posix()}/photocad.db"
    
    # LLM Settings
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    DEFAULT_LLM_MODEL: str = "gemini-2.0-flash"

    @model_validator(mode="after")
    def _resolve_relative_sqlite_url(self) -> "Settings":
        prefix = "sqlite+aiosqlite:///"
        if self.DATABASE_URL.startswith(prefix):
            raw_path = self.DATABASE_URL[len(prefix):]
            # Relative SQLite path (e.g. "storage/photocad.db") -> resolve from monorepo BASE_DIR
            is_abs = raw_path.startswith("/") or (len(raw_path) > 1 and raw_path[1] == ":")
            if not is_abs:
                resolved = (self.BASE_DIR / raw_path).resolve()
                resolved.parent.mkdir(parents=True, exist_ok=True)
                self.DATABASE_URL = f"{prefix}{resolved.as_posix()}"
        return self

settings = Settings()

# Ensure directories exist
settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
settings.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
settings.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
settings.EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
