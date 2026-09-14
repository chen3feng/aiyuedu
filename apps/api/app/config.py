from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（apps/api/app/config.py → 上溯三级到 english/）
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "English Learning API"
    database_url: str = "postgresql+psycopg://english:english@localhost:5432/english"
    redis_url: str = "redis://localhost:6379/0"
    wordlist_path: str = str(PROJECT_ROOT / "data" / "wordlists" / "wordlist.csv")
    vocab_log_path: str = str(PROJECT_ROOT / "data" / "logs" / "vocab_sessions.jsonl")
    surface_lemma_path: str = str(PROJECT_ROOT / "data" / "wordlists" / "surface_lemma.json")
    readings_path: str = str(PROJECT_ROOT / "data" / "readings" / "readings.json")
    reading_log_path: str = str(PROJECT_ROOT / "data" / "logs" / "reading_records.jsonl")
    users_path: str = str(PROJECT_ROOT / "data" / "users" / "users.json")
    topics_path: str = str(PROJECT_ROOT / "data" / "topics" / "topics.json")
    sensitive_blacklist_path: str = str(PROJECT_ROOT / "data" / "wordlists" / "sensitive_blacklist.json")
    mwe_path: str = str(PROJECT_ROOT / "data" / "mwe" / "mwe.json")
    ecdict_path: str = str(PROJECT_ROOT / "data" / "wordlists" / "raw" / "stardict.db")
    ai_config_path: str = str(PROJECT_ROOT / "data" / "config" / "ai.json")


settings = Settings()
