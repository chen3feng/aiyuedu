from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（apps/api/app/config.py → 上溯三级到 english/）
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "English Learning API"
    wordlist_path: str = str(PROJECT_ROOT / "data" / "wordlists" / "wordlist.csv")
    vocab_log_path: str = str(PROJECT_ROOT / "data" / "logs" / "vocab_sessions.jsonl")
    surface_lemma_path: str = str(PROJECT_ROOT / "data" / "wordlists" / "surface_lemma.json")
    readings_path: str = str(PROJECT_ROOT / "data" / "readings" / "readings.json")
    reading_log_path: str = str(PROJECT_ROOT / "data" / "logs" / "reading_records.jsonl")
    users_path: str = str(PROJECT_ROOT / "data" / "users" / "users.json")
    accounts_path: str = str(PROJECT_ROOT / "data" / "users" / "accounts.json")
    sessions_path: str = str(PROJECT_ROOT / "data" / "users" / "sessions.json")
    notebooks_path: str = str(PROJECT_ROOT / "data" / "notebooks" / "notebooks.json")
    vocab_tests_path: str = str(PROJECT_ROOT / "data" / "vocab_tests" / "vocab_tests.json")
    # CAT 题库的标定参数（可选）。不存在时按词频 rank 作为难度先验。
    vocab_cat_items_path: str = str(PROJECT_ROOT / "data" / "calibration" / "vocab_cat_items.json")
    topics_path: str = str(PROJECT_ROOT / "data" / "topics" / "topics.json")
    sensitive_blacklist_path: str = str(PROJECT_ROOT / "data" / "wordlists" / "sensitive_blacklist.json")
    mwe_path: str = str(PROJECT_ROOT / "data" / "mwe" / "mwe.json")
    ecdict_path: str = str(PROJECT_ROOT / "data" / "wordlists" / "raw" / "stardict.db")
    ai_config_path: str = str(PROJECT_ROOT / "data" / "config" / "ai.json")
    writings_path: str = str(PROJECT_ROOT / "data" / "writings" / "writings.json")
    collections_dir: str = str(PROJECT_ROOT / "data" / "collections")
    collections_index: str = str(PROJECT_ROOT / "data" / "collections" / "_index.json")
    # 词汇量测试算法开关：classic（固定分层抽样）| eudic（自适应 EAP）|
    # cat（词频题库 CAT）。前端可在开始测试时用 algo 参数覆盖。
    vocab_algo: str = "classic"
    # 后台管理（admin app，8001）口令：用户名固定 admin。
    # 部署/局域网使用务必通过环境变量 ADMIN_PASSWORD 覆盖默认值。
    admin_password: str = "changeme"


settings = Settings()
