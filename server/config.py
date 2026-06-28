from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
load_dotenv(Path(".env.local"), override=True)


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() == "true"


@dataclass(slots=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "maintainerKi")
    app_env: str = os.getenv("APP_ENV", "development")
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    expose_api_docs: bool = _env_bool(
        "EXPOSE_API_DOCS",
        os.getenv("APP_ENV", "development").lower() != "production",
    )
    detailed_public_health: bool = _env_bool(
        "DETAILED_PUBLIC_HEALTH",
        os.getenv("APP_ENV", "development").lower() != "production",
    )
    trusted_hosts: str = os.getenv("TRUSTED_HOSTS", "")
    admin_auth_enabled: bool = _env_bool(
        "ADMIN_AUTH_ENABLED",
        bool(os.getenv("ADMIN_PASSWORD_HASH") or os.getenv("ADMIN_PASSWORD")),
    )
    admin_username: str = os.getenv("ADMIN_USERNAME", "admin")
    admin_password_hash: str = os.getenv("ADMIN_PASSWORD_HASH", "")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "")
    session_secret: str = os.getenv("SESSION_SECRET", "")
    session_not_before_epoch: int = int(os.getenv("SESSION_NOT_BEFORE_EPOCH", "0"))
    session_cookie_name: str = os.getenv("SESSION_COOKIE_NAME", "maintainerki_session")
    session_ttl_seconds: int = int(os.getenv("SESSION_TTL_SECONDS", "43200"))
    session_cookie_secure: bool = _env_bool(
        "SESSION_COOKIE_SECURE",
        os.getenv("APP_ENV", "development").lower() == "production",
    )
    login_rate_limit_attempts: int = int(os.getenv("LOGIN_RATE_LIMIT_ATTEMPTS", "5"))
    login_rate_limit_window_seconds: int = int(
        os.getenv("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "300")
    )
    login_rate_limit_block_seconds: int = int(
        os.getenv("LOGIN_RATE_LIMIT_BLOCK_SECONDS", "900")
    )
    webhook_rate_limit_requests: int = int(os.getenv("WEBHOOK_RATE_LIMIT_REQUESTS", "240"))
    webhook_rate_limit_window_seconds: int = int(
        os.getenv("WEBHOOK_RATE_LIMIT_WINDOW_SECONDS", "60")
    )
    debug_api_enabled: bool = _env_bool(
        "DEBUG_API_ENABLED",
        os.getenv("APP_ENV", "development").lower() == "development",
    )

    github_webhook_secret: str = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    github_app_id: str = os.getenv("GITHUB_APP_ID", "")
    github_private_key_path: str = os.getenv("GITHUB_PRIVATE_KEY_PATH", "")
    github_api_base_url: str = os.getenv("GITHUB_API_BASE_URL", "https://api.github.com")
    github_label_writeback_enabled: bool = (
        os.getenv("GITHUB_LABEL_WRITEBACK_ENABLED", "true").lower() == "true"
    )
    github_auto_create_labels: bool = (
        os.getenv("GITHUB_AUTO_CREATE_LABELS", "true").lower() == "true"
    )
    github_writeback_timeout_seconds: float = float(
        os.getenv("GITHUB_WRITEBACK_TIMEOUT_SECONDS", "30")
    )
    github_duplicate_comments_enabled: bool = (
        os.getenv("GITHUB_DUPLICATE_COMMENTS_ENABLED", "true").lower() == "true"
    )
    monitored_repositories: str = os.getenv("MONITORED_REPOSITORIES", "")

    scorer_provider: str = os.getenv("SCORER_PROVIDER", "mock")
    scorer_timeout_seconds: float = float(os.getenv("SCORER_TIMEOUT_SECONDS", "60"))
    scorer_temperature: float = float(
        os.getenv("SCORER_TEMPERATURE", os.getenv("OLLAMA_TEMPERATURE", "0.1"))
    )
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen3.6:27b")
    ollama_temperature: float = float(os.getenv("OLLAMA_TEMPERATURE", "0.1"))
    ollama_keep_alive: str = os.getenv("OLLAMA_KEEP_ALIVE", "5m")
    mlx_command: str = os.getenv("MLX_COMMAND", "./.venv-mlx/bin/mlx_lm.generate")
    mlx_model_path: str = os.getenv("MLX_MODEL_PATH", "")
    mlx_max_tokens: int = int(os.getenv("MLX_MAX_TOKENS", "300"))
    mlx_use_default_chat_template: bool = (
        os.getenv("MLX_USE_DEFAULT_CHAT_TEMPLATE", "false").lower() == "true"
    )

    database_url: str = os.getenv("DATABASE_URL", "")
    redis_url: str = os.getenv("REDIS_URL", "")
    queue_provider: str = os.getenv("QUEUE_PROVIDER", "celery")
    celery_enabled: bool = os.getenv("CELERY_ENABLED", "true").lower() == "true"
    celery_broker_url: str = os.getenv("CELERY_BROKER_URL", os.getenv("REDIS_URL", ""))
    celery_result_backend: str = os.getenv(
        "CELERY_RESULT_BACKEND", os.getenv("REDIS_URL", "")
    )
    celery_task_always_eager: bool = (
        os.getenv("CELERY_TASK_ALWAYS_EAGER", "false").lower() == "true"
    )

    duplicate_embedding_provider: str = os.getenv(
        "DUPLICATE_EMBEDDING_PROVIDER", "hashing"
    )
    duplicate_embedding_model: str = os.getenv(
        "DUPLICATE_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
    )
    duplicate_similarity_threshold: float = float(
        os.getenv("DUPLICATE_SIMILARITY_THRESHOLD", "0.8")
    )
    duplicate_max_candidates: int = int(os.getenv("DUPLICATE_MAX_CANDIDATES", "3"))
    duplicate_label_name: str = os.getenv(
        "DUPLICATE_LABEL_NAME", "maintainerki:possible-duplicate"
    )
    duplicate_hash_dimensions: int = int(os.getenv("DUPLICATE_HASH_DIMENSIONS", "384"))
    dashboard_allowed_origins: str = os.getenv(
        "DASHBOARD_ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173",
    )
    webhook_retention_days: int = int(os.getenv("WEBHOOK_RETENTION_DAYS", "30"))
    contribution_body_retention_days: int = int(
        os.getenv("CONTRIBUTION_BODY_RETENTION_DAYS", "90")
    )
    feedback_note_retention_days: int = int(os.getenv("FEEDBACK_NOTE_RETENTION_DAYS", "365"))
    suspicious_score_threshold: int = int(os.getenv("SUSPICIOUS_SCORE_THRESHOLD", "70"))
    needs_info_completeness_threshold: int = int(
        os.getenv("NEEDS_INFO_COMPLETENESS_THRESHOLD", "40")
    )
    review_first_threshold: int = int(os.getenv("REVIEW_FIRST_THRESHOLD", "80"))
    worth_a_look_threshold: int = int(os.getenv("WORTH_A_LOOK_THRESHOLD", "55"))

    def monitored_repository_set(self) -> set[str]:
        return {
            item.strip().lower()
            for item in self.monitored_repositories.split(",")
            if item.strip()
        }


settings = Settings()
