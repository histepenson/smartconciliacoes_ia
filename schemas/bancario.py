from typing import Any

from pydantic import BaseModel


class CalcularDiferencasBancarioRequest(BaseModel):
    # Mesmo formato de saida de tools/banco/extrato_bancario.py e
    # tools/banco/razao_banco.py no conciliacao-api.
    extrato: list[dict[str, Any]]
    razao: list[dict[str, Any]]


class CalcularDiferencasBancarioResponse(BaseModel):
    resumo: dict[str, Any]
    movimentos_por_dia: list[dict[str, Any]]
    dias_divergentes: list[dict[str, Any]]
    dias_conciliados: list[dict[str, Any]]
    registros_so_extrato: list[dict[str, Any]]
    registros_so_razao: list[dict[str, Any]]
