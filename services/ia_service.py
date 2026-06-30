"""
Camada de explicacao em linguagem natural sobre um diagnostico JA CALCULADO
deterministicamente (services/analise_service.py). O modelo nunca recebe a
lista bruta de registros para "descobrir" o problema -- ele so' recebe o
resumo estruturado (causas, descricao, valores) e devolve texto. Isso evita
o risco de alucinacao sobre numeros financeiros: o calculo e' sempre feito
em Python; a IA so' redige.
"""
import logging
from pathlib import Path

from core.config import settings
from schemas.analise import DiagnosticoDivergencia

logger = logging.getLogger(__name__)

_KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"

_KNOWLEDGE_FILES: dict[str, str] = {
    "fiscal": "pre_conferencia.md",
    "nota_sft": "nota_sft.md",
}


def _carregar_conhecimento(dominio: str) -> str:
    nome = _KNOWLEDGE_FILES.get(dominio)
    if not nome:
        return ""
    caminho = _KNOWLEDGE_DIR / nome
    try:
        return caminho.read_text(encoding="utf-8")
    except Exception:
        logger.warning("Nao foi possivel carregar knowledge/%s", nome)
        return ""

_SYSTEM_PROMPT = (
    "Você é a IA Smart Conciliações. Explique, em português do Brasil correto e "
    "totalmente acentuado (use à, á, â, ã, é, ê, í, ó, ô, õ, ú, ç sempre que a "
    "norma exigir — nunca escreva sem acento, e nunca misture palavras em inglês), "
    "de forma objetiva e técnica, por que um grupo de lançamentos não casou numa "
    "conciliação contábil/fiscal. Use APENAS os números e causas fornecidos -- "
    "nunca invente CFOP, TES, valores, contas ou notas que não estejam no "
    "diagnóstico recebido. Vá direto ao motivo principal e, quando fizer sentido, "
    "sugira a correção (ex.: qual configuração ajustar). "
    "Seja extremamente conciso: no máximo 2 frases curtas no total. Não repita a "
    "descrição da causa com outras palavras nem elabore hipóteses sobre o motivo -- "
    "se a causa já é objetiva (ex.: título não contabilizado, lançamento manual, "
    "título encontrado fora do match automático, lançado em outra conta), apenas "
    "confirme o fato em uma frase curta e diga a ação necessária em outra.\n\n"
    "DIAGNÓSTICO DE QUALIDADE DA CARGA (campo diagnostico_carga): Quando o payload "
    "contém 'diagnostico_carga', analise-o PRIMEIRO antes de qualquer outra coisa. "
    "Este campo descreve os parâmetros usados ao carregar os dados do Protheus e "
    "estatísticas dos registros. Verifique os 'alertas' — se houver alertas, eles "
    "indicam a causa raiz mais provável e devem ser mencionados na resposta. "
    "Regras de interpretação:\n"
    "- saldo='3' (Somente Crédito): a carga não trouxe lançamentos de débito — "
    "todos os registros têm debito=0, por isso total_ct2=0. Solução: recarregar com "
    "saldo='2' (Somente Débito).\n"
    "- saldo='1' (Ambos): a carga inclui créditos (debito=0) e débitos. Se pct_debito_zero "
    "for alto, a conta filtrada (conta_de/ate) pode estar trazendo só o lado crédito.\n"
    "- pct_ct2_lp_vazio alto (>80%): os lançamentos não têm LP vinculado no Protheus "
    "(CT2_ORIGEM não bateu com nenhum CT5) — confirme no Protheus se o CT5 está configurado "
    "para o período.\n"
    "- Se total_ct2=0 e qt_ct2=0, mas total_registros_carga>0: nenhum registro da carga "
    "pertence a este LP/grupo — verifique se o ct2_lp corresponde aos LPs cadastrados "
    "no sistema (campo top_ct2_lp mostra os valores reais)."
)


def _texto_fallback(diagnostico: DiagnosticoDivergencia, contexto: dict) -> str:
    alertas = (contexto.get("diagnostico_carga") or {}).get("alertas") or []
    if not diagnostico.motivos:
        if alertas:
            return "Problema na carga: " + " | ".join(alertas)
        return "Nenhuma divergencia encontrada nos registros analisados."
    partes = []
    for m in diagnostico.motivos:
        partes.append(
            f"- {m.causa}: {m.descricao} ({len(m.registros_afetados)} registro(s), "
            f"R$ {m.valor_total_impactado:,.2f})"
        )
    if alertas:
        partes.insert(0, "ALERTA DA CARGA: " + " | ".join(alertas))
    return "Diagnostico:\n" + "\n".join(partes)


def gerar_explicacao_nota(diagnostico: dict, contexto: dict) -> str:
    """
    Gera explicacao em linguagem natural para o diagnostico de uma nota SFT especifica
    que nao casou com o CT2. Mais simples que gerar_explicacao: o diagnostico ja vem
    estruturado pelo backend; a IA so' redige a explicacao final.
    """
    conhecimento = _carregar_conhecimento("nota_sft")
    system_prompt = (
        "Você é a IA Smart Conciliações. Explique, em português do Brasil correto e "
        "totalmente acentuado, de forma objetiva e técnica, por que uma nota fiscal "
        "específica não casou na pré-conferência CT2 × SFT. "
        "Use APENAS as informações do diagnóstico recebido — nunca invente dados, lotes, "
        "contas ou valores que não estejam no campo 'diagnostico'. "
        "Seja extremamente conciso: no máximo 2 frases curtas. A primeira descreve a causa; "
        "a segunda indica a ação recomendada."
    )
    if conhecimento:
        system_prompt += (
            "\n\n---\nBASE DE CONHECIMENTO:\n\n" + conhecimento
        )

    motivo = diagnostico.get("motivo", "")
    alertas = diagnostico.get("alertas") or []
    registros = diagnostico.get("registros") or []
    params = diagnostico.get("parametros_carga") or {}

    if not settings.OPENAI_API_KEY:
        # Fallback deterministico
        if motivo == "ausente_na_carga":
            partes = [f"NF {contexto.get('nf')} nao encontrada na carga CT2 (lote={params.get('lote')})."]
            if alertas:
                partes.append(alertas[0])
            return " ".join(partes)
        if motivo == "encontrado_com_divergencia":
            todos_probs = [p for r in registros for p in r.get("problemas", [])]
            return f"NF encontrada na carga mas com divergencia: {'; '.join(todos_probs[:3]) or 'ver detalhes'}."
        return diagnostico.get("descricao", "Sem informacao suficiente para diagnostico.")

    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        payload = {
            "contexto": contexto,
            "diagnostico": {
                "motivo": motivo,
                "descricao": diagnostico.get("descricao"),
                "alertas": alertas,
                "registros": registros,
                "parametros_carga": params,
            },
        }
        resposta = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            max_tokens=300,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": str(payload)},
            ],
        )
        return (resposta.choices[0].message.content or "").strip()
    except Exception:
        logger.exception("Falha ao gerar explicacao_nota via IA")
        return diagnostico.get("descricao", "")


def gerar_explicacao(diagnostico: DiagnosticoDivergencia, contexto: dict, dominio: str = "") -> str:
    if not settings.OPENAI_API_KEY:
        return _texto_fallback(diagnostico, contexto)

    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.OPENAI_API_KEY)

        conhecimento = _carregar_conhecimento(dominio)
        system_prompt = _SYSTEM_PROMPT
        if conhecimento:
            system_prompt = (
                system_prompt
                + "\n\n---\nBASE DE CONHECIMENTO DO DOMÍNIO (use como referência para "
                "interpretar causas e sugerir ações — não invente informações além do que "
                "está no diagnóstico recebido):\n\n"
                + conhecimento
            )

        payload = {
            "contexto": {k: v for k, v in contexto.items() if k != "diagnostico_carga"},
            "diagnostico_carga": contexto.get("diagnostico_carga") or {},
            "motivos": [m.model_dump() for m in diagnostico.motivos],
            "valor_total_nao_conciliado_a": diagnostico.valor_total_nao_conciliado_a,
            "valor_total_nao_conciliado_b": diagnostico.valor_total_nao_conciliado_b,
        }
        resposta = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            max_tokens=600,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": str(payload)},
            ],
        )
        return (resposta.choices[0].message.content or "").strip() or _texto_fallback(
            diagnostico, contexto
        )
    except Exception:
        logger.exception("Falha ao gerar explicacao via IA Smart Conciliações -- usando fallback determinístico")
        return _texto_fallback(diagnostico, contexto)
