"""
Camada de explicacao em linguagem natural sobre um diagnostico JA CALCULADO
deterministicamente (services/analise_service.py). O modelo nunca recebe a
lista bruta de registros para "descobrir" o problema -- ele so' recebe o
resumo estruturado (causas, descricao, valores) e devolve texto. Isso evita
o risco de alucinacao sobre numeros financeiros: o calculo e' sempre feito
em Python; a IA so' redige.
"""
import logging

from core.config import settings
from schemas.analise import DiagnosticoDivergencia

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Voce explica, em portugues do Brasil, de forma objetiva e tecnica, por que um "
    "grupo de lancamentos nao casou numa conciliacao contabil/fiscal. Use APENAS os "
    "numeros e causas fornecidos -- nunca invente CFOP, TES, valores ou notas que nao "
    "estejam no diagnostico recebido. Va direto ao motivo principal e, quando fizer "
    "sentido, sugira a correcao (ex.: qual configuracao ajustar). Seja conciso: no "
    "maximo 2 paragrafos curtos."
)


def _texto_fallback(diagnostico: DiagnosticoDivergencia, contexto: dict) -> str:
    if not diagnostico.motivos:
        return "Nenhuma divergencia encontrada nos registros analisados."
    partes = []
    for m in diagnostico.motivos:
        partes.append(
            f"- {m.causa}: {m.descricao} ({len(m.registros_afetados)} registro(s), "
            f"R$ {m.valor_total_impactado:,.2f})"
        )
    return "Diagnostico:\n" + "\n".join(partes)


def gerar_explicacao(diagnostico: DiagnosticoDivergencia, contexto: dict) -> str:
    if not settings.ANTHROPIC_API_KEY:
        return _texto_fallback(diagnostico, contexto)

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        payload = {
            "contexto": contexto,
            "motivos": [m.model_dump() for m in diagnostico.motivos],
            "valor_total_nao_conciliado_a": diagnostico.valor_total_nao_conciliado_a,
            "valor_total_nao_conciliado_b": diagnostico.valor_total_nao_conciliado_b,
        }
        resposta = client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=600,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": str(payload)}],
        )
        return "".join(
            bloco.text for bloco in resposta.content if getattr(bloco, "type", "") == "text"
        ).strip() or _texto_fallback(diagnostico, contexto)
    except Exception:
        logger.exception("Falha ao gerar explicacao via Claude -- usando fallback determinístico")
        return _texto_fallback(diagnostico, contexto)
