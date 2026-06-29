from fastapi import APIRouter, Depends

from middleware.auth import verificar_api_key
from schemas.bancario import CalcularDiferencasBancarioRequest, CalcularDiferencasBancarioResponse
from services import bancario_service

router = APIRouter(prefix="/v1/bancario", tags=["Bancario"], dependencies=[Depends(verificar_api_key)])


@router.post(
    "/diferencas",
    response_model=CalcularDiferencasBancarioResponse,
    summary="Diferencas Extrato Bancario x Razao",
)
def calcular(req: CalcularDiferencasBancarioRequest):
    return bancario_service.calcular(req.extrato, req.razao)
