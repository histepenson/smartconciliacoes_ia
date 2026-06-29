from fastapi import APIRouter, Depends

from middleware.auth import verificar_api_key
from schemas.estoque import CalcularDiferencasEstoqueRequest, CalcularDiferencasEstoqueResponse
from services import estoque_service

router = APIRouter(prefix="/v1/estoque", tags=["Estoque"], dependencies=[Depends(verificar_api_key)])


@router.post(
    "/diferencas",
    response_model=CalcularDiferencasEstoqueResponse,
    summary="Diferencas Kardex x Razao de Estoque",
)
def calcular(req: CalcularDiferencasEstoqueRequest):
    return estoque_service.calcular(req.kardex, req.razao)
