# Pré-Conferência — Base de Conhecimento para Análise de Divergências

## 1. O que é a Pré-Conferência

Confronto entre dois lados gerados pelo Protheus:

| Lado | Fonte | Descrição |
|------|-------|-----------|
| **CT2** | CT2RAZCT5 (razão contábil filtrado) | Lançamentos contábeis — débitos e créditos gerados pela integração contábil |
| **SFT** | SFTENT (livro fiscal de entradas/saídas) | Notas fiscais registradas no livro fiscal |

O objetivo é confirmar que **cada nota fiscal lançada no SFT foi refletida corretamente no razão contábil** (e vice-versa), LP por LP.

---

## 2. Lançamento Padrão (LP) — O elo entre os dois lados

Cada LP representa uma natureza contábil. O sistema usa o campo **CT2_LP** do razão para identificar a qual LP pertence cada lançamento. Um LP tem:

- **lp_codigo**: código do LP no Protheus (ex.: `610`, `650`, `008810`)
- **descricao**: descrição que casa com CT5_DESC do Protheus (ex.: `"COMPRA MERCADORIA"`)
- **grupo**: agrupa vários LPs para somar como bloco único (ex.: grupo `"ICMS ENTRADA"` pode conter LPs `008810` e `008811`)
- **cfops**: lista de CFOPs que identificam as notas do SFT que pertencem a este LP
- **tes_codes**: filtro adicional por TES (opcional)
- **especies**: filtro por espécie de documento (opcional, ex.: `"NF"`, `"CTE"`)
- **cfops_excluir / tes_codes_excluir / especies_excluir**: listas de exclusão
- **colunas_valor_sft**: quando preenchido, soma essas colunas do SFT em vez de `valcont` (ex.: `["difal", "vfcpdif"]` para DIFAL)

**LPs especiais:**
- `610` = agrega lançamentos de **Saída** (CFOP 5/6/7)
- `650` = agrega lançamentos de **Entrada** (CFOP 1/2/3)

---

## 3. Estrutura dos dados

### CT2 (campos relevantes)
| Campo | Descrição |
|-------|-----------|
| `ct2_lp` | Código do LP (de CT2_ORIGEM → CT5) — vazio quando não tem LP vinculado |
| `ct5_desc` | Descrição do CT5 (deve casar com `lp.descricao`) |
| `ct2_key` | Chave de origem: `filial(4) + NF(9) + serie(3) + cliefor(6) [+ produto(30) para Saída]` |
| `ct2_itemc` | Fornecedor/cliente (CT2_ITEMC) — usado para resolver a chave quando `ct2_key` está vazio |
| `debito` | Valor de débito do lançamento |
| `credito` | Valor de crédito do lançamento |
| `data` | Data de lançamento |
| `historico` | Texto livre — contém o número da NF (ex.: `"COMPRA MERCADORIA NFE2214902"`, `"NF 001447 FORNECEDOR 01/123456"`) |
| `filial` | Filial contábil |
| `lote_sub_doc_linha` | Identificação interna do lote/documento |

### SFT (campos relevantes)
| Campo | Descrição |
|-------|-----------|
| `filial` | Filial fiscal |
| `nf` | Número da nota fiscal |
| `cliefor` | Código do fornecedor/cliente |
| `cfop` | CFOP da nota |
| `tes` | Tipo de Entrada/Saída |
| `especie` | Espécie do documento (`NF`, `CTE`, etc.) |
| `valcont` | Valor contábil (padrão para comparação) |
| `entrada` / `emissao` | Data de entrada/emissão |
| `produto` | Produto (usado na chave de Saída) |
| `serie` | Série da nota |

---

## 4. Como o matching funciona (3 fases)

### Fase 1 — Matching exato 1:1 por chave + valor
- Extrai do `ct2_key`: `(filial, NF, cliefor)` para Entrada; `(filial, NF, cliefor, produto)` para Saída
- Busca no SFT a nota com a mesma chave e valor dentro da tolerância de **R$ 0,10**
- Lançamentos com `debito=0` são descartados automaticamente (contam como matched)

### Fase 2 — Reconciliação por nota (soma do que restou)
- Para o que sobrou da Fase 1 com `ct2_key` válida, agrupa por `(filial, NF, cliefor)`
- Se a **soma** do CT2 + a **soma** do SFT para aquela nota batem dentro da tolerância → marca tudo como matched
- Cobre o caso de o razão lançar a nota inteira em uma linha enquanto o SFT lista por item
- Se a soma não bate exatamente, tenta cobertura greedy dentro do grupo

### Fase 3 — Fallback por NF do histórico (CT2 sem ct2_key)
- Extrai o número da NF do campo `historico` via regex `NFE?|CTE` (ex.: `"NFE2214902"` → `2214902`)
- Busca notas do SFT com o mesmo número
- Se houver um único fornecedor no grupo → reconcilia igual à Fase 2
- Se houver fornecedores ambíguos → tenta desambiguar por data (`CT2.data == SFT.entrada`)
- Se ainda ambíguo → **fica como diferença** (mais seguro do que arriscar match errado)

**Não há fallback global por valor** (intencionalmente — causou falsos positivos no passado).

---

## 5. Causas de divergência e como interpretar

### `registro_ausente`
A NF foi encontrada no histórico do CT2, mas **não existe no SFT** (ou não passou no filtro da carga/exportação).

**Ações:**
- Verificar se a NF existe no SFT dentro do período carregado
- Confirmar o período da carga SFTENT (data_ini / data_fim)
- Verificar se a nota foi exportada para o tipo de movimento correto (Entrada ou Saída)

### `cfop_nao_configurado`
A NF existe no SFT, mas o **CFOP dela não está na lista configurada para este LP**.

**Ações:**
- Adicionar o CFOP na configuração do LP, OU
- Verificar se esse CFOP pertence a outro LP

### `tes_nao_configurado`
A NF existe no SFT e o CFOP está correto, mas a **TES não está configurada para este LP**.

**Ações:**
- Adicionar a TES na configuração do LP, OU
- Verificar se há uma TES coringa sendo usada para um tipo diferente de operação

### `especie_nao_configurada`
A NF existe no SFT, CFOP e TES corretos, mas a **espécie do documento** (ex.: `CTE` em vez de `NF`) não está na lista de espécies aceitas.

**Ações:**
- Adicionar a espécie na configuração do LP

### `valor_divergente`
A NF existe no SFT, passou em todos os filtros, mas o **valor contábil não coincide** com o valor do lançamento no CT2.

**Ações:**
- Verificar se a coluna de valor correta está configurada em `colunas_valor_sft` para este LP
- Verificar se há rateio ou ajuste na nota que gerou lançamentos parciais

---

## 6. Diagnóstico da carga CT2 (problemas estruturais)

Quando `total_ct2=0` mesmo com registros na carga, o problema quase sempre é um parâmetro errado.

### Parâmetro `saldo` (campo da carga CT2RAZCT5)
| Valor | Significado | Impacto |
|-------|-------------|---------|
| `1` | Ambos (débito + crédito) | Correto para maioria dos casos; pode trazer ruído de créditos |
| `2` | Somente Débito | **Padrão recomendado** para Entrada — notas de entrada geram débito na conta |
| `3` | Somente Crédito | **Errado para Entrada** — todos os `debito=0`, `total_ct2=0` para todos os LPs |

**Se `saldo=3` e `total_ct2=0`**: a carga está configurada errada. Recarregar com `saldo=2`.

**Se `saldo=1` e `pct_debito_zero` alto**: a conta filtrada (`conta_de/ate`) pode estar trazendo só o lado crédito de uma conta de contrapartida.

### Campo `ct2_lp` vazio (`pct_ct2_lp_vazio` alto)
O CT2_LP vem do campo CT2_ORIGEM do Protheus, que é preenchido pela integração contábil a partir do CT5. Se `ct2_lp` está vazio em muitos registros:
- O CT2_ORIGEM do lançamento não bateu com nenhum registro CT5 ativo
- Verificar no Protheus se o CT5 está configurado corretamente para o período
- Lançamentos sem LP não aparecem em nenhum LP da conferência — ficam como "sem mapeamento"

### Parâmetro `lote`
- Default hardcoded no ADVPL: `008810` quando deixado em branco
- Filtra apenas lançamentos desse lote contábil
- Se os lançamentos estão em outro lote, não aparecerão na carga

### Parâmetros de conta (`conta_de` / `conta_ate`)
- Restringe as contas contábeis buscadas no razão
- Se o intervalo de contas estiver errado, lançamentos de certas naturezas não serão incluídos

### Parâmetros de data (`data_ini` / `data_fim`)
- Período de lançamentos contábeis buscados
- Deve cobrir o mesmo período da carga SFTENT

---

## 7. LPs sem mapeamento (`lps_sem_cfop`)

LPs ativos que não têm CFOP configurado não aparecem no resultado da conferência — são listados apenas no resumo como `sem_mapeamento`. Não são divergências, são lacunas de configuração.

---

## 8. Processamento de grupos

Quando vários LPs têm o mesmo campo `grupo`, seus registros CT2 são somados e confrontados com a união dos CFOPs de todos os membros do grupo. Útil para separar o ICMS do PIS/COFINS usando o mesmo LP base, por exemplo.

---

## 9. Ações de correção mais comuns

| Sintoma observado | Causa mais provável | Ação |
|-------------------|---------------------|------|
| `total_ct2=0` com carga populada | `saldo=3` na carga | Recarregar com `saldo=2` |
| `total_ct2=0` com `pct_ct2_lp_vazio` alto | CT5 não configurado no Protheus | Revisar CT5 e recarregar |
| LP com `total_ct2>0` mas `total_sft=0` | CFOPs do LP não batem com SFT | Revisar CFOPs na config do LP |
| Notas presentes como `registro_ausente` | Nota fora do período ou não exportada | Verificar período/exportação SFTENT |
| Muitas notas com `cfop_nao_configurado` | Novo CFOP surgiu na operação | Adicionar CFOP ao LP |
| Valor diverge por nota | `colunas_valor_sft` errado | Verificar se o LP usa coluna específica (ex.: DIFAL) |
| LP não aparece na lista | LP sem CFOP configurado | Configurar CFOPs no LP |

---

## 10. O que NÃO fazer na análise

- **Não inventar CFOPs, TES ou valores** que não estejam no diagnóstico recebido
- **Não assumir que `total_ct2=0` significa falta de lançamentos** sem verificar o `diagnostico_carga`
- **Não sugerir recarregar tudo** sem identificar primeiro se é problema de parâmetro (`saldo`, `lote`, `conta`) ou de configuração de LP
- **Não confundir `ct2_lp vazio` com lançamento não existente** — o lançamento existe, apenas não tem LP vinculado
