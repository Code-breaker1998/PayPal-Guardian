from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://guardian:guardian@localhost:5432/guardian"
    frontend_origin: str = "http://localhost:3000"
    demo_agent_origin: str = "http://localhost:8100"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
