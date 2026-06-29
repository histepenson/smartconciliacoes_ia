from fastapi import APIRouter, Depends

from middleware.auth import verificar_api_key
from schemas.analise import AnalisarDivergenciaRequest, AnalisarDivergenciaResponse
from services import analise_service, ia_service

router = APIRouter(prefix="/v1/analise", tags=["Analise IA"], dependencies=[Depends(verificar_api_key)])


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
    )

    explicacao = None
    if req.gerar_explicacao_ia:
        explicacao = ia_service.gerar_explicacao(diagnostico, req.contexto)

    return {"diagnostico": diagnostico, "explicacao": explicacao}
