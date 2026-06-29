# core/config.py
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configuracoes da aplicacao."""

    # Aplicacao
    APP_NAME: str = "SmartConciliacoes IA"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"

    # Autenticacao servico-a-servico (conciliacao-api chama esta API com esse header)
    API_KEY: str = ""

    # IA (Claude) -- opcional. Sem chave, o diagnostico continua funcionando,
    # so' nao gera a explicacao em linguagem natural (fica so' o estruturado).
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-6"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """Retorna instancia cacheada das configuracoes."""
    return Settings()


settings = get_settings()
