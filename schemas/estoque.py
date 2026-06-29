from typing import Any

from pydantic import BaseModel


class CalcularDiferencasEstoqueRequest(BaseModel):
    # Mesmo formato de saida de tools/estoque/kardex.py e
    # tools/estoque/razao_estoque.py no conciliacao-api.
    kardex: list[dict[str, Any]]
    razao: list[dict[str, Any]]


class CalcularDiferencasEstoqueResponse(BaseModel):
    resumo: dict[str, Any]
    movimentos_por_grupo: list[dict[str, Any]]
    grupos_divergentes: list[dict[str, Any]]
    grupos_conciliados: list[dict[str, Any]]
