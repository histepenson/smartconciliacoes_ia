from fastapi import APIRouter, Depends

from middleware.auth import verificar_api_key
from schemas.financeiro import CalcularDiferencasFinanceiroRequest, CalcularDiferencasFinanceiroResponse
from services import financeiro_service

router = APIRouter(prefix="/v1/financeiro", tags=["Financeiro"], dependencies=[Depends(verificar_api_key)])


@router.post(
    "/diferencas",
    response_model=CalcularDiferencasFinanceiroResponse,
    summary="Diferencas Financeiro x Contabilidade",
)
def calcular(req: CalcularDiferencasFinanceiroRequest):
    return financeiro_service.calcular(req.financeiro, req.contabilidade)
