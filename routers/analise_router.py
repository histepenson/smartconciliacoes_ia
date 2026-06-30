from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from middleware.auth import verificar_api_key
from schemas.analise import AnalisarDivergenciaRequest, AnalisarDivergenciaResponse
from services import analise_service, ia_service

router = APIRouter(prefix="/v1/analise", tags=["Analise IA"], dependencies=[Depends(verificar_api_key)])


class DiagnosticoNotaSftRequest(BaseModel):
    nf: str
    filial_sft: str = ""
    cliefor_sft: str = ""
    valor_sft: float = 0.0
    carga_id_ct2: int | None = None
    diagnostico: dict[str, Any] = {}


@router.post(
    "/divergencia",
    response_model=AnalisarDivergenciaResponse,
    summary="Diagnostico de por que um grupo nao casou no matching (botao 'Analisar com IA')",
)
def analisar(req: AnalisarDivergenciaRequest):
    diagnostico = analise_service.diagnosticar(
        dominio=req.dominio,
        registros_nao_conciliados_a=req.registros_nao_conciliados_a,
        registros_nao_conciliados_b=req.registros_nao_conciliados_b,
        rotulo_a=req.rotulo_a,
        rotulo_b=req.rotulo_b,
        config=req.config,
        candidatos_brutos_b=req.candidatos_brutos_b,
        contexto=req.contexto,
    )

    explicacao = None
    if req.gerar_explicacao_ia:
        contexto_ia = {**req.contexto, "diagnostico_carga": req.diagnostico_carga} if req.diagnostico_carga else req.contexto
        explicacao = ia_service.gerar_explicacao(diagnostico, contexto_ia, dominio=req.dominio)

    return {"diagnostico": diagnostico, "explicacao": explicacao}


@router.post(
    "/nota-sft",
    summary="Explicar por que uma nota SFT especifica nao casou com o CT2",
)
def diagnosticar_nota_sft(req: DiagnosticoNotaSftRequest):
    explicacao = ia_service.gerar_explicacao_nota(req.diagnostico, {
        "nf": req.nf,
        "filial_sft": req.filial_sft,
        "cliefor_sft": req.cliefor_sft,
        "valor_sft": req.valor_sft,
        "carga_id_ct2": req.carga_id_ct2,
    })
    return {"explicacao": explicacao}
