from typing import Annotated

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    # Database
    DATABASE_URL: str


    # JWT
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    REFRESH_TOKEN_EXPIRE_HOURS: int


    # Redis
    REDIS_URL: str


    # Celery
    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str


    # Email
    SMTP_HOST: str
    SMTP_PORT: int
    SMTP_USERNAME: str
    SMTP_PASSWORD: str

    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    ALLOWED_HOSTS: str = "localhost,127.0.0.1,testserver"
    ENVIRONMENT: str = "development"
    RATE_LIMIT_STORAGE_URI: str = "memory://"
    SQLALCHEMY_ECHO: bool = False
    AI_GROQ_API_KEY: str | None = None
    AI_GEMINI_API_KEY: str | None = None
    AI_MISTRAL_API_KEY: str | None = None
    AI_PROVIDER_ORDER: str = "groq,gemini,mistral"
    AI_GROQ_MODEL: str = "openai/gpt-oss-120b"
    AI_GEMINI_MODEL: str = "gemini-3.8-flash"
    AI_MISTRAL_MODEL: str = "mistral-small-latest"
    AI_VECTOR_STORE_PATH: str = "private_files/chroma"
    PRODUCT_SEARCH_SIMILARITY_THRESHOLD: Annotated[float, Field(ge=0.0, le=1.0)] = Field(
        default=0.35,
        validation_alias=AliasChoices(
            "PRODUCT_SEARCH_SIMILARITY_THRESHOLD",
            "product_search_similarity_threshold",
        ),
    )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def allowed_hosts(self) -> list[str]:
        return [host.strip() for host in self.ALLOWED_HOSTS.split(",") if host.strip()]

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if self.ENVIRONMENT.lower() == "production":
            if len(self.JWT_SECRET_KEY.encode("utf-8")) < 32:
                raise ValueError("Production JWT_SECRET_KEY must contain at least 32 bytes.")
            if (
                not self.cors_origins
                or "*" in self.cors_origins
                or self.CORS_ORIGINS.strip()
                == "http://localhost:5173,http://127.0.0.1:5173"
            ):
                raise ValueError("Production CORS_ORIGINS must contain explicit origins.")
            if (
                not self.allowed_hosts
                or "*" in self.allowed_hosts
                or self.ALLOWED_HOSTS.strip() == "localhost,127.0.0.1,testserver"
            ):
                raise ValueError("Production ALLOWED_HOSTS must contain explicit hostnames.")
            if self.RATE_LIMIT_STORAGE_URI.startswith("memory://"):
                raise ValueError("Production rate limiting requires a shared storage backend.")
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",  # The shared .env may contain Locust-only settings.
    )


settings = Settings()