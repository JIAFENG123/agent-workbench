from functools import lru_cache
from typing import Annotated, Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Agent Workbench"
    environment: str = "dev"
    debug: bool = False
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/workbench"
    database_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 5

    redis_url: str = ""

    jwt_secret: str = "dev-only-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7

    # NoDecode keeps pydantic-settings from JSON-parsing these; the CSV splitting happens in
    # the validator below, which otherwise never runs for values coming from .env.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    embedding_model: str = "nvidia/nemotron-3-embed-1b"
    embedding_dim: int = 2048
    embedding_batch_size: int = 32
    embedding_truncate: str = "END"

    # Reranking lives on a different host from the OpenAI-compatible endpoints. The model id
    # is also part of the path, with dots rewritten as underscores — verified against
    # https://docs.api.nvidia.com/nim/reference/nvidia-llama-nemotron-rerank-vl-1b-v2-infer
    rerank_model: str = "nvidia/llama-nemotron-rerank-vl-1b-v2"
    rerank_base_url: str = "https://ai.api.nvidia.com/v1/retrieval"
    rerank_url: str = ""
    rerank_api_key: str = ""

    llm_model: str = "nvidia/nemotron-3-super-120b-a12b"
    llm_model_fast: str = "nvidia/nemotron-3.5-lightning-30b-a3b"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 2048
    llm_timeout_seconds: float = 120.0
    llm_max_concurrency: int = 4
    llm_max_retries: int = 3

    fallback_enabled: bool = False
    fallback_base_url: str = ""
    fallback_api_key: str = ""
    fallback_model: str = ""

    input_price_per_1m_tokens: float = 0.0
    output_price_per_1m_tokens: float = 0.0
    daily_budget_usd: float = 2.0

    chunk_target_chars: int = 900
    chunk_overlap_chars: int = 150
    retrieval_vector_k: int = 20
    retrieval_bm25_k: int = 20
    retrieval_final_k: int = 6
    rerank_enabled: bool = True

    # Raised well past the old 5 MB so real policy PDFs fit. This only guards the raw read
    # into memory — binary formats extract to far less text than they weigh, so it was a poor
    # proxy for cost to begin with.
    max_upload_bytes: int = 25 * 1024 * 1024
    # A sanity ceiling, not a budget: it bounds row count, HNSW size and embedding calls.
    # 10000 chunks is roughly 7.5 MB of latin text or 22 MB of Chinese, and at ~5 KB a row
    # about 10% of the free 0.5 GB database.
    max_chunks_per_document: int = 10000
    allowed_upload_extensions: Annotated[list[str], NoDecode] = [
        ".txt",
        ".md",
        ".markdown",
        ".pdf",
        ".docx",
        ".csv",
        ".json",
    ]

    agent_max_steps: int = 8

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    @field_validator("cors_origins", "allowed_upload_extensions", mode="before")
    @classmethod
    def _split_csv(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def llm_enabled(self) -> bool:
        return bool(self.nvidia_api_key)

    def validate_runtime(self) -> list[str]:
        """Return a list of configuration problems that would break the app at runtime."""
        problems: list[str] = []
        if not self.nvidia_api_key:
            problems.append("NVIDIA_API_KEY is not set — LLM and embedding calls will fail.")
        if self.environment == "production" and self.jwt_secret == "dev-only-secret-change-me":
            problems.append("JWT_SECRET is still the default value in production.")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()
