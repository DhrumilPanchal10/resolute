from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = Field(
        default="postgresql+psycopg://resolute:resolute@localhost:5432/resolute"
    )

    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0")

    # LLM model names (never hardcode — always read from config)
    model_small: str = Field(default="gemini/gemini-1.5-flash")
    model_strong: str = Field(default="gemini/gemini-1.5-pro")
    model_judge: str = Field(default="gemini/gemini-1.5-pro")

    # LLM provider API keys
    gemini_api_key: str = Field(default="")
    groq_api_key: str = Field(default="")

    # Auth — Clerk OIDC
    clerk_secret_key: str = Field(default="")
    clerk_jwks_url: str = Field(default="")

    # Tracing — Langfuse / Phoenix via OTLP
    otlp_endpoint: str = Field(default="")
    langfuse_public_key: str = Field(default="")
    langfuse_secret_key: str = Field(default="")

    # GitHub (issue collection + github MCP server)
    github_token: str = Field(default="")

    # Stripe (test mode only)
    stripe_secret_key: str = Field(default="sk_test_")

    # Offline mode: set OFFLINE=1 in CI / unit tests
    offline: bool = Field(default=False)

    # Per-run LLM budget ceiling (USD)
    budget_usd_max: float = Field(default=0.10)


settings: Settings = Settings()
