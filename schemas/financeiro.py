from typing import Any

from pydantic import BaseModel


class CalcularDiferencasFinanceiroRequest(BaseModel):
    # Cada registro precisa ter pelo menos: codigo, cliente, valor
    # (mesmo formato de saida de tools/financeiro/base.py::normalizar_planilha_financeira
    # e tools/contabilidade.py::normalizar_planilha_contabilidade no conciliacao-api)
    financeiro: list[dict[str, Any]]
    contabilidade: list[dict[str, Any]]


class CalcularDiferencasFinanceiroResponse(BaseModel):
    registros: list[dict[str, Any]]
    resumo: dict[str, Any]
