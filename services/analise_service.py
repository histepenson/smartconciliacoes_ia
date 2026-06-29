"""
Diagnostico deterministico de divergencias de conciliacao.

Reproduz, em codigo, a investigacao manual feita sobre um grupo/LP sem
matching: dado o que NAO casou de cada lado, aponta a causa mais provavel
(CFOP/TES/Especie fora da config, registro realmente ausente do outro lado,
ou divergencia pura de valor) -- sem depender de IA generativa para o
calculo. A camada de IA (services/ia_service.py) so' transforma esse
diagnostico estruturado em texto explicativo; o numero nunca vem do modelo.
"""
import re
from typing import Any

from schemas.analise import DiagnosticoDivergencia, MotivoDivergencia

# Mesmo padrao usado em tools/fiscal/match_ct2_sft.py para extrair o numero
# da NF/CT-e de historicos de razao como "DEVOLUCAO COMPRA NFE 2202566".
_NF_HISTORICO_RE = re.compile(r"(?:NFE?|CTE)\.?\s*(\d+)", re.IGNORECASE)

_CHAVES_VALOR = ("valor", "valcont", "debito", "credito", "entrada", "saida")


def _valor_registro(registro: dict[str, Any]) -> float:
    for chave in _CHAVES_VALOR:
        if chave in registro and registro[chave] not in (None, ""):
            try:
                return float(registro[chave])
            except (TypeError, ValueError):
                continue
    return 0.0


def _nf_normalizada(valor: Any) -> str:
    return re.sub(r"^0+(?=\d)", "", str(valor or "").strip())


def _extrair_nf_historico(historico: str) -> str | None:
    m = _NF_HISTORICO_RE.search(historico or "")
    return _nf_normalizada(m.group(1)) if m else None


def _diagnostico_fiscal(
    registros_a: list[dict],
    candidatos_brutos_b: list[dict],
    config: dict[str, Any],
) -> list[MotivoDivergencia]:
    cfops_inc = {str(c).strip() for c in (config.get("cfops") or [])}
    cfops_exc = {str(c).strip() for c in (config.get("cfops_excluir") or [])}
    tes_inc = {str(t).strip() for t in (config.get("tes_codes") or [])}
    tes_exc = {str(t).strip() for t in (config.get("tes_codes_excluir") or [])}
    especies_inc = {str(e).strip() for e in (config.get("especies") or [])}
    especies_exc = {str(e).strip() for e in (config.get("especies_excluir") or [])}

    candidatos_por_nf: dict[str, list[dict]] = {}
    for c in candidatos_brutos_b:
        nf = _nf_normalizada(c.get("nf"))
        if nf:
            candidatos_por_nf.setdefault(nf, []).append(c)

    grupos: dict[str, dict] = {}  # causa -> {descricao, registros, valor}

    def _registrar(causa: str, descricao: str, registro: dict, valor: float):
        g = grupos.setdefault(causa, {"descricao": descricao, "registros": [], "valor": 0.0})
        g["registros"].append(registro)
        g["valor"] = round(g["valor"] + valor, 2)

    for reg in registros_a:
        nf = _extrair_nf_historico(reg.get("historico", ""))
        valor = _valor_registro(reg)
        candidatos = candidatos_por_nf.get(nf, []) if nf else []

        if not candidatos:
            _registrar(
                "registro_ausente",
                "Nao ha registro correspondente no outro lado (nota realmente nao existe la, "
                "ou esta fora do periodo/filtro da carga).",
                reg, valor,
            )
            continue

        candidato = candidatos[0]
        cfop = str(candidato.get("cfop") or "").strip()
        tes = str(candidato.get("tes") or "").strip()
        especie = str(candidato.get("especie") or "").strip()

        cfop_fora = bool(cfops_inc) and not any(c in cfop for c in cfops_inc)
        cfop_excluido = bool(cfops_exc) and any(c in cfop for c in cfops_exc)
        tes_fora = bool(tes_inc) and not any(t in tes for t in tes_inc)
        tes_excluido = bool(tes_exc) and any(t in tes for t in tes_exc)
        especie_fora = bool(especies_inc) and not any(e in especie for e in especies_inc)
        especie_excluida = bool(especies_exc) and any(e in especie for e in especies_exc)

        if cfop_fora or cfop_excluido:
            _registrar(
                "cfop_nao_configurado",
                f"CFOP {cfop} nao esta na lista de CFOPs configurada para este LP/grupo "
                "(ou esta na lista de exclusao).",
                reg, valor,
            )
        elif tes_fora or tes_excluido:
            _registrar(
                "tes_nao_configurado",
                f"TES {tes} nao esta na lista de TES configurada para este LP/grupo "
                "(ou esta na lista de exclusao).",
                reg, valor,
            )
        elif especie_fora or especie_excluida:
            _registrar(
                "especie_nao_configurada",
                f"Especie {especie} nao esta na lista de especies configurada para este "
                "LP/grupo (ou esta na lista de exclusao).",
                reg, valor,
            )
        else:
            valor_candidato = _valor_registro(candidato)
            _registrar(
                "valor_divergente",
                "O registro correspondente existe e passa nos filtros configurados, mas o "
                f"valor diverge (lado A={valor:.2f}, lado B={valor_candidato:.2f}).",
                reg, valor,
            )

    return [
        MotivoDivergencia(
            causa=causa, descricao=g["descricao"],
            registros_afetados=g["registros"], valor_total_impactado=g["valor"],
        )
        for causa, g in grupos.items()
    ]


_DESCRICOES_FINANCEIRO = {
    "SO_FINANCEIRO": "Existe titulo no Financeiro para este codigo, mas nenhum lancamento "
                      "correspondente foi encontrado no Razao Contabil.",
    "SO_CONTABILIDADE": "Existe lancamento no Razao Contabil para este codigo, mas nenhum "
                         "titulo correspondente foi encontrado no Financeiro.",
    "DIVERGENTE_VALOR": "O codigo tem lancamentos nos dois lados, mas a soma dos valores nao coincide.",
}


def _diagnostico_financeiro(registros_a: list[dict]) -> list[MotivoDivergencia]:
    motivos = []
    for reg in registros_a:
        causa = reg.get("tipo_diferenca") or "DIVERGENTE_VALOR"
        valor = abs(float(reg.get("diferenca") or 0))
        motivos.append(MotivoDivergencia(
            causa=causa,
            descricao=_DESCRICOES_FINANCEIRO.get(causa, "Divergencia nao classificada."),
            registros_afetados=[reg],
            valor_total_impactado=round(valor, 2),
        ))
    return motivos


def _doc_key(registro: dict[str, Any]) -> str:
    """Mesma normalizacao de tools/banco/calc_diferencas_banco.py::_normalizar_numero_documento."""
    valor = registro.get("numero") or registro.get("documento_extraido") or registro.get("chave_documento") or ""
    digitos = "".join(re.findall(r"\d+", str(valor)))
    return digitos.lstrip("0") or "0"


def _diagnostico_bancario(registros_a: list[dict], registros_b: list[dict]) -> list[MotivoDivergencia]:
    por_doc_b: dict[str, list[dict]] = {}
    for r in registros_b:
        por_doc_b.setdefault(_doc_key(r), []).append(r)

    grupos: dict[str, dict] = {}

    def _registrar(causa: str, descricao: str, registro: dict, valor: float):
        g = grupos.setdefault(causa, {"descricao": descricao, "registros": [], "valor": 0.0})
        g["registros"].append(registro)
        g["valor"] = round(g["valor"] + valor, 2)

    for reg in registros_a:
        valor = _valor_registro(reg)
        chave = _doc_key(reg)
        candidatos = por_doc_b.get(chave, []) if chave != "0" else []

        if not candidatos:
            _registrar(
                "documento_ausente",
                "Nao ha lancamento com o mesmo numero de documento do outro lado dentro do "
                "periodo analisado.",
                reg, valor,
            )
        else:
            valor_candidato = _valor_registro(candidatos[0])
            _registrar(
                "valor_divergente",
                "Existe lancamento com o mesmo numero de documento do outro lado, mas o valor "
                f"diverge (lado A={valor:.2f}, lado B={valor_candidato:.2f}).",
                reg, valor,
            )

    return [
        MotivoDivergencia(causa=c, descricao=g["descricao"], registros_afetados=g["registros"], valor_total_impactado=g["valor"])
        for c, g in grupos.items()
    ]


def _diagnostico_estoque(registros_a: list[dict], registros_b: list[dict]) -> list[MotivoDivergencia]:
    grupos: dict[str, dict] = {}

    def _registrar(causa: str, descricao: str, registro: dict, valor: float):
        g = grupos.setdefault(causa, {"descricao": descricao, "registros": [], "valor": 0.0})
        g["registros"].append(registro)
        g["valor"] = round(g["valor"] + valor, 2)

    for reg in registros_a:
        data = str(reg.get("data") or "")
        cf = str(reg.get("cf") or "")
        valor = _valor_registro(reg)

        mesmo_cf = [r for r in registros_b if str(r.get("cf") or "") == cf]
        mesma_data = [r for r in registros_b if str(r.get("data") or "") == data]

        if mesmo_cf and not mesma_data:
            outra_data = mesmo_cf[0].get("data")
            _registrar(
                "data_divergente",
                f"Existe registro do outro lado com o mesmo CF/movimento ({cf}), mas em data "
                f"diferente ({data} vs {outra_data}).",
                reg, valor,
            )
        elif mesma_data and not mesmo_cf:
            outro_cf = mesma_data[0].get("cf")
            _registrar(
                "cf_divergente",
                f"Existe registro do outro lado na mesma data ({data}), mas com CF/movimento "
                f"diferente ({cf} vs {outro_cf}).",
                reg, valor,
            )
        else:
            _registrar(
                "registro_ausente",
                "Nao ha registro do outro lado com a mesma data nem o mesmo CF/movimento -- "
                "lancamento provavelmente ausente de um dos lados.",
                reg, valor,
            )

    return [
        MotivoDivergencia(causa=c, descricao=g["descricao"], registros_afetados=g["registros"], valor_total_impactado=g["valor"])
        for c, g in grupos.items()
    ]


def _diagnostico_generico(
    registros_a: list[dict], registros_b: list[dict], rotulo_a: str, rotulo_b: str,
) -> list[MotivoDivergencia]:
    motivos = []
    if registros_a:
        motivos.append(MotivoDivergencia(
            causa="nao_conciliado_lado_a",
            descricao=f"Registros de \"{rotulo_a}\" sem correspondencia no outro lado.",
            registros_afetados=registros_a,
            valor_total_impactado=round(sum(_valor_registro(r) for r in registros_a), 2),
        ))
    if registros_b:
        motivos.append(MotivoDivergencia(
            causa="nao_conciliado_lado_b",
            descricao=f"Registros de \"{rotulo_b}\" sem correspondencia no outro lado.",
            registros_afetados=registros_b,
            valor_total_impactado=round(sum(_valor_registro(r) for r in registros_b), 2),
        ))
    return motivos


def diagnosticar(
    dominio: str,
    registros_nao_conciliados_a: list[dict],
    registros_nao_conciliados_b: list[dict],
    rotulo_a: str,
    rotulo_b: str,
    config: dict[str, Any],
    candidatos_brutos_b: list[dict],
) -> DiagnosticoDivergencia:
    if dominio == "fiscal" and candidatos_brutos_b:
        motivos = _diagnostico_fiscal(registros_nao_conciliados_a, candidatos_brutos_b, config)
    elif dominio == "financeiro":
        motivos = _diagnostico_financeiro(registros_nao_conciliados_a)
    elif dominio == "bancario":
        motivos = _diagnostico_bancario(registros_nao_conciliados_a, registros_nao_conciliados_b)
    elif dominio == "estoque":
        motivos = _diagnostico_estoque(registros_nao_conciliados_a, registros_nao_conciliados_b)
    else:
        motivos = _diagnostico_generico(
            registros_nao_conciliados_a, registros_nao_conciliados_b, rotulo_a, rotulo_b,
        )

    return DiagnosticoDivergencia(
        motivos=motivos,
        valor_total_nao_conciliado_a=round(sum(_valor_registro(r) for r in registros_nao_conciliados_a), 2),
        valor_total_nao_conciliado_b=round(sum(_valor_registro(r) for r in registros_nao_conciliados_b), 2),
    )
