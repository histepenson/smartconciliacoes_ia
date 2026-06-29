"""
Modulo de calculo de diferencas para Conciliacao de Estoque.

Realiza o matching entre Kardex e Razao Contabil de Estoque (CTBR400):
- Agrupa movimentos por codigo_movimento
- Compara totais Kardex vs Razao por grupo
- Classifica divergencias
- Lista registros individuais sem correspondencia

Regras:
- Entradas Kardex (DE0-DE7, PR0, CFOPs < 5000) = Debito no Razao
- Saidas Kardex (RE0-RE7, CFOPs >= 5000) = Credito no Razao
"""

import pandas as pd
import logging
import time
from typing import Dict, Any
from datetime import datetime
import re

logger = logging.getLogger(__name__)

THRESHOLD_CONCILIACAO = 1.0

# Orcamento de tempo total (todas as chamadas somadas) para a decomposicao
# exata por subset-sum em _selecionar_registros_para_total -- e' um recurso
# de UI (mostrar quais lancamentos compoem uma diferenca), nao essencial pro
# resultado da conciliacao (o chamador ja cai de volta pra lista completa de
# registros quando a funcao retorna vazio). Sem esse teto, um Kardex grande
# (milhares de movimentos, muitos buckets data+cf divergentes) pode disparar
# a funcao centenas/milhares de vezes e travar a requisicao por minutos.
_DECOMP_DEADLINE = {"value": 0.0}

# Codigos de movimento que representam entradas (debito no razao)
CODIGOS_ENTRADA = {
    "ENTRADAS", "DEV", "PR0",
    "DE0", "DE1", "DE2", "DE3", "DE4", "DE5", "DE6", "DE7",
}


def _normalizar_codigo_movimento(valor: Any) -> str:
    return str(valor or "").strip().upper()


def _normalizar_data_chave(valor: Any) -> str:
    """
    Normaliza data para chave de matching em DD/MM/YYYY.
    """
    texto = str(valor or "").strip()
    if not texto:
        return ""

    # Ja no formato esperado
    if re.match(r"^\d{2}/\d{2}/\d{4}$", texto):
        return texto

    # ISO: YYYY-MM-DD (opcionalmente com hora)
    if re.match(r"^\d{4}-\d{2}-\d{2}", texto):
        dt_iso = pd.to_datetime(texto, format="%Y-%m-%d", errors="coerce")
        if pd.isna(dt_iso):
            dt_iso = pd.to_datetime(texto, errors="coerce")
        if pd.notna(dt_iso):
            return dt_iso.strftime("%d/%m/%Y")

    dt = pd.to_datetime(texto, dayfirst=True, errors="coerce")
    if pd.notna(dt):
        return dt.strftime("%d/%m/%Y")

    # Fallback: extrair primeira data DD/MM/YYYY do texto
    m = re.search(r"(\d{2}/\d{2}/\d{4})", texto)
    return m.group(1) if m else texto


def _normalizar_cf_chave(valor: Any) -> str:
    """
    Normaliza CF para chave de matching.
    """
    texto = str(valor or "").strip().upper()
    if not texto:
        return ""

    # Mantem codigos internos
    if re.fullmatch(r"(DE[0-7]|RE[0-7]|PR0|CPV|DEV)", texto):
        return texto

    # CFOP numerico: remove separadores
    digitos = re.sub(r"\D", "", texto)
    if digitos:
        return digitos

    return texto


def _normalizar_cf_por_movimento(cf: Any, codigo_movimento: Any) -> str:
    """
    Normaliza CF considerando o grupo de movimento.
    Em ENTRADAS/SAIDAS, usa chave unica do grupo para evitar falso mismatch entre
    CFOP numerico do Kardex e codigos internos (DE/RE/PR) do Razao.
    """
    cm = _normalizar_codigo_movimento(codigo_movimento)
    if cm == "ENTRADAS":
        return "ENTRADAS"
    if cm == "SAIDAS":
        return "SAIDAS"
    return _normalizar_cf_chave(cf)


def _selecionar_registros_para_total(registros: list, total_alvo: float) -> list:
    """
    Seleciona subconjunto de registros cuja soma de 'valor' fecha o total_alvo.
    Usa DP em centavos para match exato (tolerancia de 1 centavo).
    """
    alvo_cent = int(round(abs(float(total_alvo or 0)) * 100))
    if alvo_cent <= 0 or not registros:
        return []

    if time.monotonic() > _DECOMP_DEADLINE["value"]:
        return []

    itens = []
    for idx, reg in enumerate(registros):
        v_cent = int(round(abs(float(reg.get("valor", 0) or 0)) * 100))
        if v_cent > 0:
            itens.append((idx, v_cent))

    if not itens:
        return []

    # Bucket grande demais: a busca exata por subconjunto (DP) fica cara
    # (O(len(itens) * estados)) sem trazer beneficio proporcional -- o
    # chamador ja cai de volta para a lista completa de registros quando
    # isso retorna vazio (ver "composicao if composicao else regs_chave").
    if len(itens) > 500:
        return []

    # soma_cent -> (idx_do_item_usado, soma_anterior) -- back-pointer em vez
    # de guardar a lista completa de indices em cada estado. A versao antiga
    # fazia "idxs + [idx]" (copia de lista, O(tamanho)) a cada transicao; com
    # ate max_estados*len(itens) transicoes, isso explodia para buckets de
    # centenas de itens. Guardar so' o passo anterior e' O(1) por transicao;
    # a lista de indices so' e' reconstruida UMA vez, no final, para o
    # candidato escolhido.
    estados: dict[int, Any] = {0: None}
    # 60000 estados tornava a poda (sort + rebuild) cara o suficiente para
    # travar com buckets de centenas de itens (cada poda chama a key function
    # uma vez por estado -- com poda disparando em quase toda iteracao do
    # loop principal, o custo total explode). 2000 ja' cobre com folga os
    # casos reais (poucas dezenas/centenas de lancamentos por bucket).
    max_estados = 2000

    for idx, v_cent in itens:
        # Checagem por iteracao (nao so' na entrada da funcao): uma unica
        # chamada com itens proximos do limite (500) e muitos estados pode
        # estourar o orcamento por conta propria antes de outra chamada
        # nova ser bloqueada pela checagem inicial.
        if time.monotonic() > _DECOMP_DEADLINE["value"]:
            return []

        # Itera sobre um snapshot das somas atuais e insere as novas somas
        # diretamente em "estados" -- evita copiar o dict inteiro a cada
        # item processado.
        for soma in list(estados.keys()):
            ns = soma + v_cent
            if ns > alvo_cent + 1:
                continue
            if ns not in estados:
                estados[ns] = (idx, soma)

        if len(estados) > max_estados:
            # poda por proximidade ao alvo
            chaves = sorted(estados.keys(), key=lambda s: abs(alvo_cent - s))[: max_estados // 2]
            estados = {k: estados[k] for k in chaves}

    def _reconstruir(soma_final: int) -> list:
        idxs = []
        soma = soma_final
        passo = estados.get(soma)
        while passo is not None:
            idx_usado, soma_anterior = passo
            idxs.append(idx_usado)
            soma = soma_anterior
            passo = estados.get(soma)
        return idxs

    for candidato in (alvo_cent, alvo_cent - 1, alvo_cent + 1):
        if candidato in estados:
            return [registros[i] for i in _reconstruir(candidato)]

    # fallback: melhor aproximacao
    melhor = min(estados.keys(), key=lambda s: abs(alvo_cent - s))
    return [registros[i] for i in _reconstruir(melhor)]


def calcular_diferencas_estoque(
    df_kardex: pd.DataFrame,
    df_razao: pd.DataFrame
) -> Dict[str, Any]:
    """
    Calcula diferencas entre Kardex e Razao Contabil de Estoque
    agrupado por codigo_movimento.

    Parametros:
    -----------
    df_kardex : pd.DataFrame
        DataFrame normalizado do Kardex (saida de normalizar_kardex)
        Colunas esperadas: data, cf, codigo_movimento, tipo_movimento, valor

    df_razao : pd.DataFrame
        DataFrame normalizado do Razao de Estoque (saida de normalizar_razao_estoque)
        Colunas esperadas: data_movimento, codigo_movimento, debito, credito, tipo

    Retorna:
    --------
    dict contendo:
        - 'resumo': Estatisticas da conciliacao
        - 'movimentos_por_grupo': Lista de movimentos agrupados por codigo_movimento
        - 'grupos_divergentes': Grupos com divergencia
        - 'grupos_conciliados': Grupos conciliados
        - 'registros_so_kardex': Registros individuais do Kardex sem match no Razao
        - 'registros_so_razao': Registros individuais do Razao sem match no Kardex
    """
    logger.info("[CALC DIFERENCAS ESTOQUE] Iniciando calculo")

    _DECOMP_DEADLINE["value"] = time.monotonic() + 5.0

    df_k = df_kardex.copy()
    df_r = df_razao.copy()

    # Normalizacao de chaves antes de agrupar/match
    if "codigo_movimento" in df_k.columns:
        df_k["codigo_movimento"] = df_k["codigo_movimento"].apply(_normalizar_codigo_movimento)
    if "codigo_movimento" in df_r.columns:
        df_r["codigo_movimento"] = df_r["codigo_movimento"].apply(_normalizar_codigo_movimento)
    if "data" in df_k.columns:
        df_k["data"] = df_k["data"].apply(_normalizar_data_chave)
    if "data_movimento" in df_r.columns:
        df_r["data_movimento"] = df_r["data_movimento"].apply(_normalizar_data_chave)
    if "cf" in df_k.columns:
        df_k["cf"] = df_k["cf"].apply(lambda x: str(x or "").strip().upper())
    if "cf_original" in df_r.columns:
        df_r["cf_original"] = df_r["cf_original"].apply(lambda x: str(x or "").strip().upper())

    # ===========================
    # 1. AGRUPAR KARDEX por codigo_movimento
    # ===========================
    df_k_grupo = df_k.groupby(["codigo_movimento"], as_index=False).agg({
        "valor": "sum",
        "tipo_movimento": "first",
    })
    df_k_grupo.columns = ["codigo_movimento", "valor_kardex", "tipo_movimento"]

    logger.info(f"[CALC DIFERENCAS ESTOQUE] Grupos Kardex: {len(df_k_grupo)}")

    # ===========================
    # 2. AGRUPAR RAZAO por codigo_movimento
    # ===========================
    df_r_grupo = df_r.groupby(["codigo_movimento"], as_index=False).agg({
        "debito": "sum",
        "credito": "sum",
    })
    df_r_grupo.columns = ["codigo_movimento", "debito_razao", "credito_razao"]

    # Valor do razao: entradas usa debito, saidas usa credito
    df_r_grupo["valor_razao"] = df_r_grupo.apply(
        lambda row: row["debito_razao"]
        if row["codigo_movimento"] in CODIGOS_ENTRADA
        else row["credito_razao"],
        axis=1
    )

    logger.info(f"[CALC DIFERENCAS ESTOQUE] Grupos Razao: {len(df_r_grupo)}")

    # ===========================
    # 3. MERGE por codigo_movimento
    # ===========================
    df_merge = pd.merge(
        df_k_grupo[["codigo_movimento", "valor_kardex", "tipo_movimento"]],
        df_r_grupo[["codigo_movimento", "valor_razao", "debito_razao", "credito_razao"]],
        on=["codigo_movimento"],
        how="outer"
    )
    df_merge = df_merge.fillna(0)

    # Preencher tipo_movimento para registros so do razao
    mask_sem_tipo = (df_merge["tipo_movimento"] == 0) | (df_merge["tipo_movimento"] == "0")
    df_merge.loc[mask_sem_tipo, "tipo_movimento"] = df_merge.loc[mask_sem_tipo, "codigo_movimento"].apply(
        lambda cm: "ENTRADA" if cm in CODIGOS_ENTRADA else "SAIDA"
    )

    # ===========================
    # 4. CALCULAR DIFERENCAS
    # ===========================
    df_merge["diferenca"] = df_merge["valor_razao"] - df_merge["valor_kardex"]
    df_merge["diferenca_abs"] = df_merge["diferenca"].abs()

    def classificar_grupo(row):
        if row["diferenca_abs"] <= THRESHOLD_CONCILIACAO:
            return "CONCILIADO"
        return "DIVERGENTE"

    df_merge["status"] = df_merge.apply(classificar_grupo, axis=1)

    def classificar_origem(row):
        tem_kardex = float(row["valor_kardex"]) != 0
        tem_razao = float(row["valor_razao"]) != 0
        if not tem_kardex:
            return "SO_RAZAO"
        if not tem_razao:
            return "SO_KARDEX"
        return "AMBOS"

    df_merge["origem"] = df_merge.apply(classificar_origem, axis=1)

    # Ordenar
    df_merge = df_merge.sort_values(["codigo_movimento"])

    # ===========================
    # 5. MATCHING INDIVIDUAL por (data, cf, valor)
    # ===========================
    # Para cada grupo (ENTRADAS/SAIDAS), faz matching registro-a-registro
    # entre Kardex e Razao. Razao e normalizado para formato comparavel:
    #   data = data_movimento, cf = cf_original (HISTORICO[:3]), valor = debito ou credito

    def _normalizar_razao_para_matching(df_razao_grupo, is_entrada):
        """Normaliza registros do Razao para formato comparavel com Kardex."""
        registros = []
        # to_dict("records") em vez de iterrows() -- iterrows() reconstroi uma
        # Series por linha (custoso em DataFrame com colunas de tipos mistos),
        # e esse grupo pode ter milhares de linhas num Kardex/Razao grandes.
        for idx, reg in enumerate(df_razao_grupo.to_dict("records")):
            valor = float(reg.get("debito", 0)) if is_entrada else float(reg.get("credito", 0))
            data_mov = reg.get("data_movimento", "") or reg.get("data_lancamento", "")
            cm = _normalizar_codigo_movimento(reg.get("codigo_movimento", ""))
            registros.append({
                "_idx": idx,
                "data": _normalizar_data_chave(data_mov),
                "cf": _normalizar_cf_por_movimento(reg.get("cf_original", ""), cm),
                "valor": round(valor, 2),
                "historico": str(reg.get("historico", "")),
                "lote_doc": str(reg.get("lote_doc", "")),
                "debito": round(float(reg.get("debito", 0)), 2),
                "credito": round(float(reg.get("credito", 0)), 2),
                "codigo_movimento": cm,
                "ct2_key": str(reg.get("ct2_key", "") or "").strip(),
                "_origem": "razao",
            })
        return registros

    def _normalizar_kardex_para_matching(df_kardex_grupo):
        """Normaliza registros do Kardex para formato comparavel."""
        registros = []
        for idx, reg in enumerate(df_kardex_grupo.to_dict("records")):
            cm = _normalizar_codigo_movimento(reg.get("codigo_movimento", ""))
            registros.append({
                "_idx": idx,
                "data": _normalizar_data_chave(reg.get("data", "")),
                "cf": _normalizar_cf_por_movimento(reg.get("cf", ""), cm),
                "valor": round(float(reg.get("valor", 0)), 2),
                "documento_numero": str(reg.get("documento_numero", "")),
                "descricao": str(reg.get("descricao", "")),
                "codigo_produto": str(reg.get("codigo_produto", "")),
                "codigo_movimento": cm,
                "ct2_key": str(reg.get("ct2_key", "") or "").strip(),
                "_origem": "kardex",
            })
        return registros

    def _agrupar_para_matching(registros, usar_cf=True):
        """
        Aglutina registros por:
        - data + cf (quando usar_cf=True)
        - data (quando usar_cf=False)
        Somando os valores.
        """
        mapa = {}
        for reg in registros:
            data = _normalizar_data_chave(reg.get("data", ""))
            cf = _normalizar_cf_chave(reg.get("cf", "")) if usar_cf else ""
            chave = (data, cf) if usar_cf else (data,)
            if chave not in mapa:
                mapa[chave] = {"data": data, "cf": cf, "valor": 0.0, "registros": []}
            mapa[chave]["valor"] += float(reg.get("valor", 0) or 0)
            mapa[chave]["registros"].append(reg)

        resultado = []
        for item in mapa.values():
            item["valor"] = round(item["valor"], 2)
            resultado.append(item)
        return resultado

    # Grupos onde Kardex CF (CFOP numerico) difere do Razao CF (codigo texto)
    # Para esses, matching e por (data, valor) apenas, sem comparar CF
    # Inclui DEV e CFOPs numericos (extraidos de CPV)
    def _skip_cf_match(codigo_movimento):
        return codigo_movimento in {"CPV", "DEV"}

    def _matching_por_ct2_key(regs_kardex, regs_razao):
        """
        Passada 0 (antes do matching agregado por data+cf): casa Kardex x
        Razao pelo ct2_key -- mesma chave que o Protheus grava na CT2 ao
        gerar o lancamento contabil a partir do movimento de estoque
        (Codigo+ARM+Data+Documento no Kardex; CT2_KEY nativo no Razao).
        So' consome o par quando chave E valor batem (tolerancia de R$ 0,01)
        -- sem fallback global, mesmo principio de tools/fiscal/match_ct2_sft.py
        (evita falso positivo por colisao de chave). O que nao casar aqui
        (sem ct2_key de um dos lados, ou chave sem par) segue no fluxo
        existente de matching por (data, cf).
        """
        por_chave_razao: dict = {}
        for idx, reg in enumerate(regs_razao):
            chave = reg.get("ct2_key") or ""
            if chave:
                por_chave_razao.setdefault(chave, []).append(idx)

        usados_kardex = set()
        usados_razao = set()
        for idx_k, reg_k in enumerate(regs_kardex):
            chave = reg_k.get("ct2_key") or ""
            if not chave:
                continue
            candidatos = [i for i in por_chave_razao.get(chave, []) if i not in usados_razao]
            if not candidatos:
                continue
            valor_k = float(reg_k.get("valor", 0) or 0)
            for idx_r in candidatos:
                valor_r = float(regs_razao[idx_r].get("valor", 0) or 0)
                if abs(valor_k - valor_r) <= THRESHOLD_CONCILIACAO:
                    usados_kardex.add(idx_k)
                    usados_razao.add(idx_r)
                    break

        if not usados_kardex and not usados_razao:
            return regs_kardex, regs_razao

        regs_kardex_restantes = [r for i, r in enumerate(regs_kardex) if i not in usados_kardex]
        regs_razao_restantes = [r for i, r in enumerate(regs_razao) if i not in usados_razao]
        return regs_kardex_restantes, regs_razao_restantes

    def _matching_registros(regs_kardex, regs_razao, match_cf=True):
        """
        Matching aglutinado:
        - passada 0: chave exata por ct2_key (quando disponivel)
        - por (data, cf_normalizado) quando match_cf=True
        - por (data) quando match_cf=False
        Compara soma de valor por chave.
        """
        regs_kardex, regs_razao = _matching_por_ct2_key(regs_kardex, regs_razao)
        k_ag = _agrupar_para_matching(regs_kardex, usar_cf=match_cf)
        r_ag = _agrupar_para_matching(regs_razao, usar_cf=match_cf)

        k_map = {((r["data"], r["cf"]) if match_cf else (r["data"],)): r for r in k_ag}
        r_map = {((r["data"], r["cf"]) if match_cf else (r["data"],)): r for r in r_ag}

        chaves = set(k_map.keys()) | set(r_map.keys())
        so_kardex = []
        so_razao = []

        for chave in sorted(chaves):
            kv = float(k_map.get(chave, {}).get("valor", 0.0))
            rv = float(r_map.get(chave, {}).get("valor", 0.0))
            diff = round(kv - rv, 2)

            if abs(diff) <= THRESHOLD_CONCILIACAO:
                continue

            data = chave[0]
            cf = chave[1] if match_cf else ""

            if diff > 0:
                regs_chave = k_map.get(chave, {}).get("registros", [])
                composicao = _selecionar_registros_para_total(regs_chave, diff)
                so_kardex.append({
                    "data": data,
                    "cf": cf,
                    "valor": round(diff, 2),
                    "_origem": "kardex",
                    "registros_composicao": composicao if composicao else regs_chave,
                })
            else:
                valor_diff = abs(diff)
                regs_chave = r_map.get(chave, {}).get("registros", [])
                composicao = _selecionar_registros_para_total(regs_chave, valor_diff)
                so_razao.append({
                    "data": data,
                    "cf": cf,
                    "valor": round(valor_diff, 2),
                    "_origem": "razao",
                    "registros_composicao": composicao if composicao else regs_chave,
                })

        # 2a passada: fallback por valor apenas (mesmo codigo_movimento),
        # para reduzir falso "sem correspondencia" causado por data inconsistente no historico.
        rk = so_kardex.copy()
        rr = so_razao.copy()
        usados_r = set()
        reconciliados_k = set()
        for i, k in enumerate(rk):
            vk = float(k.get("valor", 0) or 0)
            for j, r in enumerate(rr):
                if j in usados_r:
                    continue
                vr = float(r.get("valor", 0) or 0)
                if abs(vk - vr) <= THRESHOLD_CONCILIACAO:
                    reconciliados_k.add(i)
                    usados_r.add(j)
                    break

        so_kardex_final = [k for i, k in enumerate(rk) if i not in reconciliados_k]
        so_razao_final = [r for j, r in enumerate(rr) if j not in usados_r]

        # 3a passada: compensacao por saldo total.
        # Se ainda restar pendencia dos dois lados, mas os totais baterem,
        # considera conciliado no math para evitar falso divergente.
        total_k = round(sum(float(x.get("valor", 0) or 0) for x in so_kardex_final), 2)
        total_r = round(sum(float(x.get("valor", 0) or 0) for x in so_razao_final), 2)
        if so_kardex_final and so_razao_final and abs(total_k - total_r) <= THRESHOLD_CONCILIACAO:
            return [], []

        return so_kardex_final, so_razao_final

    # ===========================
    # 6. PREPARAR RESULTADO com matching individual
    # ===========================
    movimentos_por_grupo = []
    grupos_divergentes = []
    grupos_conciliados = []

    for _, row in df_merge.iterrows():
        cm = str(row["codigo_movimento"]) if row["codigo_movimento"] else ""
        is_entrada = cm in CODIGOS_ENTRADA

        grupo_info = {
            "codigo_movimento": cm,
            "tipo_movimento": str(row["tipo_movimento"]),
            "valor_kardex": round(float(row["valor_kardex"]), 2),
            "valor_razao": round(float(row["valor_razao"]), 2),
            "debito_razao": round(float(row.get("debito_razao", 0)), 2),
            "credito_razao": round(float(row.get("credito_razao", 0)), 2),
            "diferenca": 0.0,
            "diferenca_abs": 0.0,
            "status": "CONCILIADO",
            "origem": "AMBOS",
            "so_kardex": [],
            "so_razao": [],
            "conciliados_kardex": [],
            "conciliados_razao": [],
            "registros_kardex": [],
            "registros_razao": [],
            "total_so_kardex": 0.0,
            "total_so_razao": 0.0,
            "qtd_so_kardex": 0,
            "qtd_so_razao": 0,
            "qtd_registros_kardex": 0,
            "qtd_registros_razao": 0,
        }

        # Fazer matching individual para todos os grupos (divergentes ou nao)
        regs_k = _normalizar_kardex_para_matching(df_k[df_k["codigo_movimento"] == cm])
        regs_r = _normalizar_razao_para_matching(df_r[df_r["codigo_movimento"] == cm], is_entrada)
        grupo_info["registros_kardex"] = regs_k
        grupo_info["registros_razao"] = regs_r
        grupo_info["qtd_registros_kardex"] = len(regs_k)
        grupo_info["qtd_registros_razao"] = len(regs_r)

        match_cf = not _skip_cf_match(cm)
        so_k, so_r = _matching_registros(regs_k, regs_r, match_cf=match_cf)
        grupo_info["so_kardex"] = so_k
        grupo_info["so_razao"] = so_r
        grupo_info["total_so_kardex"] = round(sum(float(r.get("valor", 0) or 0) for r in so_k), 2)
        grupo_info["total_so_razao"] = round(sum(float(r.get("valor", 0) or 0) for r in so_r), 2)
        grupo_info["qtd_so_kardex"] = len(so_k)
        grupo_info["qtd_so_razao"] = len(so_r)

        # Computar conciliados: registros que NAO aparecem nas composicoes de so_*
        idxs_pendentes_k = set()
        for entry in so_k:
            for comp in (entry.get("registros_composicao") or []):
                if "_idx" in comp:
                    idxs_pendentes_k.add(comp["_idx"])
        grupo_info["conciliados_kardex"] = [r for r in regs_k if r.get("_idx") not in idxs_pendentes_k]

        idxs_pendentes_r = set()
        for entry in so_r:
            for comp in (entry.get("registros_composicao") or []):
                if "_idx" in comp:
                    idxs_pendentes_r.add(comp["_idx"])
        grupo_info["conciliados_razao"] = [r for r in regs_r if r.get("_idx") not in idxs_pendentes_r]

        # Math principal baseado na aglutinacao (dia + cf + soma)
        dif_aglutinada = round(grupo_info["total_so_razao"] - grupo_info["total_so_kardex"], 2)
        grupo_info["diferenca"] = dif_aglutinada
        grupo_info["diferenca_abs"] = round(abs(dif_aglutinada), 2)

        tem_so_k = grupo_info["total_so_kardex"] > THRESHOLD_CONCILIACAO
        tem_so_r = grupo_info["total_so_razao"] > THRESHOLD_CONCILIACAO

        if not tem_so_k and not tem_so_r:
            grupo_info["status"] = "CONCILIADO"
            grupo_info["origem"] = "AMBOS"
        else:
            grupo_info["status"] = "DIVERGENTE"
            if tem_so_k and not tem_so_r:
                grupo_info["origem"] = "SO_KARDEX"
            elif tem_so_r and not tem_so_k:
                grupo_info["origem"] = "SO_RAZAO"
            else:
                grupo_info["origem"] = "AMBOS"

        movimentos_por_grupo.append(grupo_info)

        if grupo_info["status"] == "DIVERGENTE":
            grupos_divergentes.append(grupo_info)
        else:
            grupos_conciliados.append(grupo_info)

    # ===========================
    # 7.5 SALDO FINAL DO RAZAO (ultima linha, igual ao banco)
    # ===========================
    total_debito_razao = df_r["debito"].sum() if "debito" in df_r.columns else 0.0
    total_credito_razao = df_r["credito"].sum() if "credito" in df_r.columns else 0.0
    saldo_final_razao = (
        float(df_r.iloc[-1]["saldo_atual"])
        if len(df_r) > 0 and "saldo_atual" in df_r.columns
        else None
    )

    # Movimentos da ORIGEM (Kardex): entradas = debito, saidas = credito
    total_entradas_kardex = (
        df_k.loc[df_k["tipo_movimento"] == "ENTRADA", "valor"].sum()
        if "valor" in df_k.columns and "tipo_movimento" in df_k.columns
        else 0.0
    )
    total_saidas_kardex = (
        df_k.loc[df_k["tipo_movimento"] == "SAIDA", "valor"].sum()
        if "valor" in df_k.columns and "tipo_movimento" in df_k.columns
        else 0.0
    )

    # ===========================
    # 8. RESUMO
    # ===========================
    total_kardex = df_merge["valor_kardex"].sum()
    total_razao = df_merge["valor_razao"].sum()
    dif_total = total_razao - total_kardex

    qtd_grupos = len(df_merge)
    qtd_conciliados = len(grupos_conciliados)
    qtd_divergentes = len(grupos_divergentes)
    qtd_so_kardex = len([g for g in movimentos_por_grupo if g["origem"] == "SO_KARDEX"])
    qtd_so_razao = len([g for g in movimentos_por_grupo if g["origem"] == "SO_RAZAO"])

    percentual_conciliacao = (qtd_conciliados / qtd_grupos * 100) if qtd_grupos > 0 else 0
    situacao = "CONCILIADO" if qtd_divergentes == 0 else "DIVERGENTE"

    resumo = {
        "total_kardex": round(total_kardex, 2),
        "total_razao": round(total_razao, 2),
        "dif_total": round(dif_total, 2),
        "situacao": situacao,
        "qtd_grupos": qtd_grupos,
        "qtd_conciliados": qtd_conciliados,
        "qtd_divergentes": qtd_divergentes,
        "qtd_so_kardex": qtd_so_kardex,
        "qtd_so_razao": qtd_so_razao,
        "percentual_conciliacao": round(percentual_conciliacao, 2),
        "total_debito_razao": round(float(total_debito_razao), 2),
        "total_credito_razao": round(float(total_credito_razao), 2),
        "saldo_final_razao": round(saldo_final_razao, 2) if saldo_final_razao is not None else None,
        "total_entradas_kardex": round(float(total_entradas_kardex), 2),
        "total_saidas_kardex": round(float(total_saidas_kardex), 2),
        "data_processamento": datetime.now().isoformat(),
    }

    logger.info(f"[CALC DIFERENCAS ESTOQUE] Resumo: {resumo}")

    return {
        "resumo": resumo,
        "movimentos_por_grupo": movimentos_por_grupo,
        "grupos_divergentes": grupos_divergentes,
        "grupos_conciliados": grupos_conciliados,
    }
