"""
Matching entre lancamentos contabeis CT2 (razao com CT2_KEY) e notas fiscais SFT.

Extraido de services/pre_conferencia_service.py para ser reutilizado tambem pela
conciliacao de impostos (mesma logica, mas comparando contra uma coluna de valor
do SFT diferente de valcont, ex: valicm, valpis, valcof).
"""
import re
from typing import Optional

# Extrai o numero do documento (NF ou CT-e) de historicos como "PIS CREDITADO
# NFE 61" ou "COFINS AQUISICAO FRETE CTE 124" -- usado so' como fallback
# (fase 3) quando o lancamento nao tem CT2_KEY. O SFT guarda o numero do CT-e
# no mesmo campo "nf" (especie="CTE"), por isso o numero extraido casa direto.
_NF_HISTORICO_RE = re.compile(r"(?:NFE?|CTE)\.?\s*(\d+)", re.IGNORECASE)


def match_ct2_sft(
    ct2_recs: list[dict],
    sft_recs: list[dict],
    campo_valor_sft: str = "valcont",
    campo_valor_ct2: str = "debito",
    tolerancia: float = 0.10,
) -> tuple[list[dict], list[dict]]:
    """
    Casa lancamentos do CT2 (via CT2_KEY) com notas do SFT por
    (filial, nf, fornece[, produto]) + valor (campo_valor_sft) dentro da
    tolerancia. A direcao (Entrada/Saida) e' detectada automaticamente pelo
    CFOP predominante em sft_recs (1/2/3 = Entrada, 5/6/7 = Saida) -- cada
    chamada processa um lote homogeneo (mesmo LP/grupo de imposto ou mesmo
    filtro Entrada/Saida), entao a maioria decide com seguranca. Para Saida
    a chave tambem amarra por produto (D2_COD embutido no CT2_KEY, posicoes
    24:54 -- ver _extrair_chave_ct2), porque o lancamento contabil de Saida
    e' por item da NF; Entrada continua so' por filial+nf+fornece, como
    sempre foi.

    campo_valor_ct2 indica qual coluna do CT2 usar como valor do lancamento
    ("debito" para notas de Entrada, "credito" para notas de Saida).

    Fases:
    1. Matching exato 1:1 por chave (filial+nf+fornece[+produto]) + valor
       dentro da tolerancia.
    2. Reconciliacao por nota: para o que sobrou da fase 1 mas ainda tem
       chave valida, agrupa por (filial, nf, fornece[, produto]). Se a soma do que
       restou do CT2 bater com a soma do que restou do SFT para aquela
       MESMA nota, marca tudo daquele grupo como casado (cobre o caso comum
       de o razao lancar a nota inteira em uma linha so enquanto o SFT lista
       por item, ou vice-versa). Se a soma nao bater exatamente, tenta uma
       cobertura greedy por valor so' dentro do proprio grupo (mesma nota) --
       cobre o caso de a nota ter um lancamento extra sem correspondencia no
       SFT (ex.: complemento de importacao) ao lado de um lancamento
       principal que bate perfeitamente.
    3. Fallback por historico (so' para CT2 SEM CT2_KEY): extrai o numero da
       NF/CT-e do texto do historico (ex.: "PIS CREDITADO NFE 61" -> 61,
       "COFINS AQUISICAO FRETE CTE 124" -> 124) e agrupa pelas notas do SFT
       que ainda sobraram com esse MESMO numero -- por (filial, NF) quando
       o CT2 tiver o campo "filial" (chave mais forte), ou so' por NF
       quando nao tiver (cargas antigas, antes do campo existir no
       CT2RAZCT5). Sem fornecedor no CT2 pra validar a chave inteira, so'
       segue se todas as notas do SFT daquele grupo forem do MESMO
       fornecedor; se houver mais de um, tenta desambiguar comparando
       CT2_DATA (campo "data" do razao) com FT_ENTRADA (campo "entrada" do
       SFT) -- se isso isolar um unico fornecedor, segue com ele, senao
       continua ambiguo e fica como diferenca. Com fornecedor unico
       confirmado, soma o grupo igual a fase 2 (cobre NF dividida em varios
       itens no SFT) e, se a soma nao bater, tenta cobertura greedy dentro
       do mesmo grupo.

    Propositalmente NAO ha fallback global (cruzando todo o dataset por
    valor, sem respeitar NF): isso ja causou falsos positivos reais --
    lancamentos sem nenhuma relacao com nota fiscal (ex.: credito de PIS
    sobre aluguel) "casando" so' porque a soma batia por coincidencia com
    sobras de outras notas. CT2 sem CT2_KEY cujo numero de NF (via
    historico) nao for unico entre as sobras do SFT, ou cujo grupo de NF
    nao reconciliou nem parcialmente na fase 2, fica como diferenca -- mais
    seguro deixar para revisao manual do que arriscar um match errado.

    Returns:
        Tupla (ct2_resultado, sft_resultado), cada item original com a chave
        booleana "matched" adicionada.
    """

    def _norm_filial(v: str) -> str:
        return v.strip().zfill(4)

    def _norm_nf(v: str) -> str:
        return v.strip().zfill(9)

    def _norm_cliefor(v: str) -> str:
        s = str(v or "").strip()
        return s[:6].zfill(6) if len(s) >= 6 else s.zfill(6)

    # Layout do CT2_KEY (campo nativo do Protheus, gerado pela integracao
    # contabil a partir do SD1/SD2 de origem) apos filial+nf+serie+cliefor
    # (posicoes 0:22, iguais para Entrada e Saida): Entrada (SD1) termina ali
    # mesmo (resto e' lixo/PADR nao usado); Saida (SD2) emenda D2_LOJA (2,
    # ignorado) + D2_COD (30, com o produto alinhado a esquerda e preenchido
    # com espacos) + D2_ITEM (2). Confirmado com dados reais de producao
    # (LP 610 = Saida -- ver pre_conferencia_service._LP_CODIGO_POR_TIPO_MOV):
    # ct2_key="...0234620 1BIRA47000006[espacos]01" onde "023462" e' o
    # cliente (cliefor) e "BIRA47000006" e' exatamente o campo "produto" do
    # SFT para aquela NF.
    _POS_PRODUTO_INI = 24
    _LEN_PRODUTO = 30

    def _eh_saida(sft_recs: list) -> bool:
        """
        Detecta se o lote de notas do SFT recebido e' de Saida (CFOP 5/6/7)
        ou Entrada (CFOP 1/2/3) -- maioria simples. Cada chamada de
        match_ct2_sft processa um lote homogeneo (mesmo LP/grupo de imposto
        ou mesmo filtro Entrada/Saida), entao a maioria decide com seguranca.
        """
        saida = entrada = 0
        for r in sft_recs:
            cfop = str(r.get("cfop") or "").strip()
            if cfop[:1] in ("5", "6", "7"):
                saida += 1
            elif cfop[:1] in ("1", "2", "3"):
                entrada += 1
        return saida > entrada

    def _extrair_chave_ct2(rec: dict, eh_saida: bool):
        key = str(rec.get("ct2_key") or "").strip()
        if len(key) < 22:
            return None
        # O segmento da NF (posicoes 4:13) nao tem largura fixa de digitos
        # significativos no CT2_KEY real do Protheus -- varia por tipo de
        # documento (NF-e, CT-e, etc), vindo com espacos de preenchimento a
        # direita em vez de zeros a esquerda (ex.: "00005439 ", "001447   ").
        # _norm_nf (strip + zfill(9)) recanonicaliza para o mesmo formato do
        # SFT independente da largura original.
        filial = _norm_filial(key[0:4])
        nf = _norm_nf(key[4:13])
        cliefor = _norm_cliefor(key[16:22])
        if not eh_saida:
            return (filial, nf, cliefor)
        fim_produto = _POS_PRODUTO_INI + _LEN_PRODUTO
        if len(key) < fim_produto:
            return None
        produto = key[_POS_PRODUTO_INI:fim_produto].strip()
        return (filial, nf, cliefor, produto)

    def _chave_sft(rec: dict, eh_saida: bool):
        filial = str(rec.get("filial") or "").strip()
        nf = str(rec.get("nf") or "").strip()
        cliefor = str(rec.get("cliefor") or "").strip()
        if not filial or not nf:
            return None
        if not eh_saida:
            return (_norm_filial(filial), _norm_nf(nf), _norm_cliefor(cliefor))
        produto = str(rec.get("produto") or "").strip()
        return (_norm_filial(filial), _norm_nf(nf), _norm_cliefor(cliefor), produto)

    def _extrair_nf_historico(historico: str) -> Optional[str]:
        m = _NF_HISTORICO_RE.search(historico or "")
        if not m:
            return None
        return _norm_nf(m.group(1))

    def _cobrir_greedy(indices, recs, chave_v, budget):
        ordered = sorted(indices, key=lambda i: -round(float(recs[i].get(chave_v) or 0), 2))
        cobertos: set = set()
        restante = budget
        for i in ordered:
            v = round(float(recs[i].get(chave_v) or 0), 2)
            if v == 0:
                cobertos.add(i)
                continue
            if restante <= 0:
                break
            if restante >= v - 0.01:
                cobertos.add(i)
                restante = round(restante - v, 2)
        return cobertos

    def _soma(indices, recs, chave_v):
        return round(sum(float(recs[i].get(chave_v) or 0) for i in indices), 2)

    def _reconciliar_grupo(ct2_idxs_grupo, sft_idxs_grupo):
        """
        Soma os dois lados de um grupo (mesma nota/chave) e, se nao bater
        exatamente, tenta achar -- so' no lado com o total MAIOR -- um
        subconjunto cuja soma reconstrua o total INTEIRO do lado menor
        (cobertura greedy). So' confirma o match se essa soma coberta
        realmente bater com o total do outro lado (dentro da tolerancia);
        senao, ninguem casa -- mais seguro que arriscar um match parcial sem
        relacao real (ex.: 1 item de cada lado com valores bem diferentes,
        onde "caber no orcamento" do lado maior nao significa correspondencia).
        Usada pela fase 2 (chave completa) e pela fase 3 (NF/CT-e do historico).
        """
        total_ct2 = _soma(ct2_idxs_grupo, ct2_recs, campo_valor_ct2)
        total_sft = _soma(sft_idxs_grupo, sft_recs, campo_valor_sft)
        if abs(total_ct2 - total_sft) <= tolerancia:
            ct2_matched_set.update(ct2_idxs_grupo)
            sft_matched.update(sft_idxs_grupo)
            return

        if total_ct2 >= total_sft:
            cobertos = _cobrir_greedy(ct2_idxs_grupo, ct2_recs, campo_valor_ct2, total_sft)
            if abs(_soma(cobertos, ct2_recs, campo_valor_ct2) - total_sft) <= tolerancia:
                ct2_matched_set.update(cobertos)
                sft_matched.update(sft_idxs_grupo)
        else:
            cobertos = _cobrir_greedy(sft_idxs_grupo, sft_recs, campo_valor_sft, total_ct2)
            if abs(_soma(cobertos, sft_recs, campo_valor_sft) - total_ct2) <= tolerancia:
                sft_matched.update(cobertos)
                ct2_matched_set.update(ct2_idxs_grupo)

    # Saida amarra tambem por produto (CT2_KEY traz D2_COD); Entrada continua
    # so' por filial+nf+fornece, como sempre foi.
    eh_saida = _eh_saida(sft_recs)

    # Indice SFT por (filial, nf, fornece[, produto]) -> lista de indices
    sft_por_doc: dict = {}
    for i, s in enumerate(sft_recs):
        chave = _chave_sft(s, eh_saida)
        if chave:
            sft_por_doc.setdefault(chave, []).append(i)

    # ==========================================================
    # Fase 1: matching exato 1:1 por CT2_KEY + valor (tolerancia)
    # ==========================================================
    sft_matched: set = set()
    ct2_matched_set: set = set()
    ct2_pendente_com_chave: list = []  # tem ct2_key valida mas nao casou 1:1
    ct2_sem_chave: list = []  # sem ct2_key -- candidato ao fallback por historico (fase 3)

    for i, rec in enumerate(ct2_recs):
        valor_ct2 = round(float(rec.get(campo_valor_ct2) or 0), 2)
        if valor_ct2 == 0:
            ct2_matched_set.add(i)
            continue
        chave = _extrair_chave_ct2(rec, eh_saida)
        if chave is None:
            # Sem CT2_KEY valida -- tentativa de recuperacao via historico na fase 3.
            ct2_sem_chave.append(i)
            continue

        matched = False
        for idx in sft_por_doc.get(chave, []):
            if idx not in sft_matched:
                valor_sft = round(float(sft_recs[idx].get(campo_valor_sft) or 0), 2)
                if abs(valor_sft - valor_ct2) <= tolerancia:
                    sft_matched.add(idx)
                    ct2_matched_set.add(i)
                    matched = True
                    break

        if not matched:
            ct2_pendente_com_chave.append(i)

    # ==========================================================
    # Fase 2: reconciliacao por nota (soma do que restou, por chave)
    # ==========================================================
    # Sempre por nota (filial+nf+fornece, SEM produto) mesmo quando a fase 1
    # amarrou por produto (Saida): cobre lancamentos que somam a NF inteira
    # numa unica linha do razao (ex.: "VENDA PROD NFE..." na receita de
    # vendas, valor = soma de todos os itens) -- ai' o produto que sobra no
    # CT2_KEY e' so' resquicio da ultima linha processada pela rotina nativa
    # do Protheus, nao representa o valor lancado, e nunca bateria 1:1 na
    # fase 1. Lancamento por item (ex.: PIS/COFINS/ICMS DEBITADO) ja' casou
    # na fase 1 por produto e nao chega aqui.
    ct2_por_chave: dict = {}
    for i in ct2_pendente_com_chave:
        chave = _extrair_chave_ct2(ct2_recs[i], eh_saida)[:3]
        ct2_por_chave.setdefault(chave, []).append(i)

    sft_pendente_por_chave: dict = {}
    for i in range(len(sft_recs)):
        if i in sft_matched:
            continue
        chave = _chave_sft(sft_recs[i], eh_saida)
        if chave:
            sft_pendente_por_chave.setdefault(chave[:3], []).append(i)

    for chave, ct2_idxs in ct2_por_chave.items():
        sft_idxs = sft_pendente_por_chave.get(chave, [])
        if not sft_idxs:
            continue  # nenhuma nota correspondente sobrou -- fica como diferenca
        _reconciliar_grupo(ct2_idxs, sft_idxs)

    # ==========================================================
    # Fase 3: fallback por (filial)+NF do historico (so' para CT2 sem CT2_KEY)
    # ==========================================================
    # Indice por NF sozinha (fallback quando o CT2 nao tem filial) e por
    # (filial, NF) quando o CT2 tiver o campo "filial" -- chave mais forte,
    # reduz a chance de colisao de NF entre fornecedores/filiais diferentes.
    sft_pendente_por_nf: dict = {}
    sft_pendente_por_filial_nf: dict = {}
    for i in range(len(sft_recs)):
        if i in sft_matched:
            continue
        nf = str(sft_recs[i].get("nf") or "").strip()
        if not nf:
            continue
        nf_norm = _norm_nf(nf)
        sft_pendente_por_nf.setdefault(nf_norm, []).append(i)
        filial = str(sft_recs[i].get("filial") or "").strip()
        if filial:
            sft_pendente_por_filial_nf.setdefault((_norm_filial(filial), nf_norm), []).append(i)

    ct2_sem_chave_por_grupo: dict = {}
    for i in ct2_sem_chave:
        nf = _extrair_nf_historico(ct2_recs[i].get("historico"))
        if nf is None:
            continue
        filial_ct2 = str(ct2_recs[i].get("filial") or "").strip()
        grupo = (_norm_filial(filial_ct2), nf) if filial_ct2 else nf
        ct2_sem_chave_por_grupo.setdefault(grupo, []).append(i)

    for grupo, ct2_idxs in ct2_sem_chave_por_grupo.items():
        if isinstance(grupo, tuple):
            candidatos = sft_pendente_por_filial_nf.get(grupo, [])
        else:
            candidatos = sft_pendente_por_nf.get(grupo, [])
        if not candidatos:
            continue  # nenhuma nota com essa (filial+)NF sobrou no SFT -- fica como diferenca

        # Candidatas com valor zero na coluna de imposto sao' ruido -- nunca
        # podem ser a contrapartida real (o CT2 so' chega aqui com valor != 0,
        # ver fase 1) e so' serviriam pra falsear ambiguidade de fornecedor.
        candidatos = [
            idx for idx in candidatos
            if round(float(sft_recs[idx].get(campo_valor_sft) or 0), 2) != 0
        ]
        if not candidatos:
            continue

        fornecedores = {str(sft_recs[idx].get("cliefor") or "").strip() for idx in candidatos}
        if len(fornecedores) <= 1:
            # Fornecedor unico no grupo inteiro -- caso simples, soma tudo de uma vez.
            _reconciliar_grupo(ct2_idxs, candidatos)
            continue

        # Fornecedor ambiguo no grupo inteiro -- comum quando o numero do
        # NF/CT-e (extraido do historico, sem filial/fornecedor) coincide
        # entre faturas DIFERENTES de fornecedores diferentes. Divide o
        # grupo por data (CT2_DATA do razao == FT_ENTRADA do SFT) e tenta
        # resolver cada data separadamente -- cada lancamento do CT2 so'
        # disputa contra as notas do SFT daquele MESMO dia.
        ct2_por_data: dict = {}
        for i in ct2_idxs:
            data = str(ct2_recs[i].get("data") or "").strip()
            if data:
                ct2_por_data.setdefault(data, []).append(i)

        sft_por_data: dict = {}
        for idx in candidatos:
            data = str(sft_recs[idx].get("entrada") or "").strip()
            if data:
                sft_por_data.setdefault(data, []).append(idx)

        for data, ct2_idxs_data in ct2_por_data.items():
            sft_idxs_data = sft_por_data.get(data, [])
            if not sft_idxs_data:
                continue  # nenhuma nota nesse dia -- fica como diferenca
            fornecedores_data = {str(sft_recs[idx].get("cliefor") or "").strip() for idx in sft_idxs_data}
            if len(fornecedores_data) != 1:
                # Ainda ambiguo mesmo dentro do mesmo dia -- sem CT2_KEY nao
                # ha como confirmar de qual fornecedor e'. Fica como diferenca.
                continue
            _reconciliar_grupo(ct2_idxs_data, sft_idxs_data)

    ct2_resultado = [
        {**rec, "matched": i in ct2_matched_set}
        for i, rec in enumerate(ct2_recs)
    ]
    sft_resultado = [
        {**s, "matched": i in sft_matched}
        for i, s in enumerate(sft_recs)
    ]
    return ct2_resultado, sft_resultado
