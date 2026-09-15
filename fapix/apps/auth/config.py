from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthSettings(BaseSettings):
    SECRET_KEY: str = "change-this-secret-key-in-production--bcdef0123456789abcdef"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # Ignores extra environment variables without throwing errors
    )


auth_settings = AuthSettings()