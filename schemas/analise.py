from typing import Any, Literal

from pydantic import BaseModel


class AnalisarDivergenciaRequest(BaseModel):
    dominio: Literal["fiscal", "financeiro", "bancario", "estoque", "impostos"]

    # Contexto livre para exibicao na explicacao (ex.: lp_codigo, descricao,
    # status, total_ct2, total_sft, diferenca -- o que o chamador ja tiver
    # calculado sobre o grupo/periodo em analise).
    contexto: dict[str, Any] = {}

    # Os dois lados que NAO casaram no matching (ex.: ct2_detalhes/sft_detalhes
    # com matched=False, ou so_extrato/so_razao, ou so_kardex/so_razao).
    registros_nao_conciliados_a: list[dict[str, Any]] = []
    registros_nao_conciliados_b: list[dict[str, Any]] = []
    rotulo_a: str = "Lado A"
    rotulo_b: str = "Lado B"

    # Regras de filtro/configuracao usadas no matching (ex.: cfops, tes_codes,
    # especies incluir/excluir do LP, no caso fiscal) -- usado pelo
    # diagnostico determinístico do dominio fiscal para apontar
    # "CFOP fora da lista configurada" etc. Opcional para os outros dominios.
    config: dict[str, Any] = {}

    # Registros candidatos SEM o filtro de matching aplicado (ex.: o registro
    # do SFT que existe de fato mas foi excluido do conjunto candidato por
    # nao bater o CFOP configurado). Permite ao diagnostico fiscal reproduzir
    # exatamente a investigacao manual: "a nota existe, so' nao entrou no
    # conjunto candidato por causa do CFOP X". Opcional.
    candidatos_brutos_b: list[dict[str, Any]] = []

    # Estatisticas e parametros da carga CT2 -- detecta problemas estruturais
    # (saldo errado, ct2_lp vazio, lote restrictivo) que causam total_ct2=0
    # mesmo com registros presentes. Opcional.
    diagnostico_carga: dict[str, Any] = {}

    gerar_explicacao_ia: bool = True


class MotivoDivergencia(BaseModel):
    causa: str
    descricao: str
    registros_afetados: list[dict[str, Any]] = []
    valor_total_impactado: float = 0.0


class DiagnosticoDivergencia(BaseModel):
    motivos: list[MotivoDivergencia]
    valor_total_nao_conciliado_a: float
    valor_total_nao_conciliado_b: float


class AnalisarDivergenciaResponse(BaseModel):
    diagnostico: DiagnosticoDivergencia
    explicacao: str | None = None
