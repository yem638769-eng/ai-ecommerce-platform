"""全局配置：环境变量 > .env 文件 > 默认值。"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 应用
    app_env: str = "dev"
    secret_key: str = "dev-secret-change-me"
    access_token_expire_minutes: int = 120
    refresh_token_expire_days: int = 14
    auto_create_tables: bool = True

    # 数据库 / 缓存
    database_url: str = "postgresql+asyncpg://ecommerce:ecommerce@localhost:5432/ecommerce"
    redis_url: str = "redis://localhost:6379/0"

    # LLM
    llm_provider: str = "ollama"  # ollama | openai
    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "qwen2.5:7b"
    ollama_embed_model: str = "nomic-embed-text"
    openai_base_url: str = ""
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o-mini"
    openai_embed_model: str = "text-embedding-3-small"
    embed_dim: int = 768

    # 业务
    payment_mock: bool = True
    order_timeout_minutes: int = 15


settings = Settings()
