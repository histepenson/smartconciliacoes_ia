from fastapi import Header, HTTPException

from core.config import settings


def verificar_api_key(x_api_key: str = Header(default="")) -> None:
    """
    Autenticacao servico-a-servico: conciliacao-api (ou outro chamador) envia
    o header X-API-Key. Se API_KEY nao estiver configurada no ambiente, a
    verificacao e' desabilitada (conveniente em desenvolvimento local).
    """
    if not settings.API_KEY:
        return
    if x_api_key != settings.API_KEY:
        raise HTTPException(401, "X-API-Key invalida ou ausente")
