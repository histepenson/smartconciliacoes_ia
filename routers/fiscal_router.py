from fastapi import APIRouter, Depends

from middleware.auth import verificar_api_key
from schemas.fiscal import MatchCt2SftRequest, MatchCt2SftResponse
from services import fiscal_service

router = APIRouter(prefix="/v1/fiscal", tags=["Fiscal"], dependencies=[Depends(verificar_api_key)])


@router.post(
    "/match",
    response_model=MatchCt2SftResponse,
    summary="Matching CT2 (razao) x SFT (livro fiscal)",
)
def match(req: MatchCt2SftRequest):
    ct2_resultado, sft_resultado = fiscal_service.match(
        req.ct2_recs, req.sft_recs,
        campo_valor_sft=req.campo_valor_sft,
        campo_valor_ct2=req.campo_valor_ct2,
        tolerancia=req.tolerancia,
    )
    return {"ct2_resultado": ct2_resultado, "sft_resultado": sft_resultado}
