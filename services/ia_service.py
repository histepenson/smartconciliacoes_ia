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
    "Você é a IA Smart Conciliações. Explique, em português do Brasil correto e "
    "totalmente acentuado (use à, á, â, ã, é, ê, í, ó, ô, õ, ú, ç sempre que a "
    "norma exigir — nunca escreva sem acento), de forma objetiva e técnica, por "
    "que um grupo de lançamentos não casou numa conciliação contábil/fiscal. "
    "Use APENAS os números e causas fornecidos -- nunca invente CFOP, TES, "
    "valores ou notas que não estejam no diagnóstico recebido. Vá direto ao "
    "motivo principal e, quando fizer sentido, sugira a correção (ex.: qual "
    "configuração ajustar). Seja conciso: no máximo 2 parágrafos curtos."
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
    if not settings.OPENAI_API_KEY:
        return _texto_fallback(diagnostico, contexto)

    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        payload = {
            "contexto": contexto,
            "motivos": [m.model_dump() for m in diagnostico.motivos],
            "valor_total_nao_conciliado_a": diagnostico.valor_total_nao_conciliado_a,
            "valor_total_nao_conciliado_b": diagnostico.valor_total_nao_conciliado_b,
        }
        resposta = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            max_tokens=600,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": str(payload)},
            ],
        )
        return (resposta.choices[0].message.content or "").strip() or _texto_fallback(
            diagnostico, contexto
        )
    except Exception:
        logger.exception("Falha ao gerar explicacao via IA Smart Conciliações -- usando fallback determinístico")
        return _texto_fallback(diagnostico, contexto)
