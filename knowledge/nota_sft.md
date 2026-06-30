# Diagnóstico de Nota SFT Não Casada — Base de Conhecimento

## O que é este diagnóstico

Explica por que uma nota fiscal específica presente no Livro Fiscal (SFT) não encontrou
correspondência no Razão Contábil (CT2) durante a pré-conferência.

---

## Motivos possíveis e como explicar cada um

### `ausente_na_carga`
A NF não existe em nenhum registro da carga CT2 — nem via ct2_key nem via historico.

**Causas mais comuns:**
- O lançamento contábil da nota está em um **lote diferente** do que foi filtrado na carga
  (ex.: carga com `lote=008820`, mas o lançamento está no lote `008810`)
- A integração contábil do Protheus **ainda não foi executada** para esta nota
  (nota recém-lançada no fiscal, mas o CT2 ainda não foi gerado)
- A nota está fora do **período** da carga (`data_ini` / `data_fim`)
- O **saldo** da carga excluiu este lado (ex.: `saldo=3` exclui débitos)

**Ação recomendada:**
- Verificar no Protheus (CT2RAZ sem filtro de lote) se existe lançamento para esta NF
- Se existir em outro lote: recarregar a carga CT2 sem filtro de lote, ou incluindo o lote correto
- Se não existir: verificar se a integração contábil foi executada

### `encontrado_com_divergencia`
A NF foi localizada na carga CT2, mas algum campo diverge e impediu o matching automático.

**Subtipos de divergência:**
- **filial difere**: a filial no ct2_key é diferente da filial do SFT — frequente quando a filial
  fiscal e a filial contábil têm codificações distintas no Protheus
- **cliefor difere**: o código do fornecedor/cliente no ct2_key não bate com o do SFT — pode ser
  uma diferença de cadastro entre o módulo fiscal e o módulo contábil
- **valor difere**: o débito no CT2 é diferente do valcont do SFT — pode haver rateio, desconto
  ou ajuste que gerou lançamentos parciais; o total pode bater mas nenhum item individual case
- **ct2_lp vazio**: o lançamento existe mas não tem LP vinculado (CT2_ORIGEM não casou com CT5)
  — o lançamento não entra em nenhum LP da conferência
- **sem ct2_key válida**: o lançamento foi encontrado via histórico, mas sem ct2_key o matching
  é menos preciso (depende de fornecedor único e data)

**Ação recomendada (por subtipo):**
- filial/cliefor: verificar no Protheus se os cadastros estão alinhados entre módulos
- valor: verificar se há lançamentos parciais que somados cobrem o total da nota
- ct2_lp: verificar CT5 no Protheus para o lote/sequência desta nota
- sem ct2_key: reprocessar a integração contábil para gerar ct2_key corretamente

### `encontrado_sem_problema_aparente`
A NF foi encontrada na carga e não há divergência óbvia detectada. O matching pode ter falhado por:
- Número de NF coincidente entre fornecedores diferentes (ambiguidade)
- Nota presente em mais de uma filial com o mesmo número
- Problema de codificação de caracteres no histórico

**Ação recomendada:** revisão manual do lançamento no CT2 e da nota no SFT

---

## O que NÃO inventar

- Não mencionar outros lotes, datas ou contas que não estejam nos parâmetros recebidos
- Não assumir que a integração falhou sem evidência clara
- Não sugerir apagar ou recriar dados — sempre "verificar" ou "recarregar"
- Ser conciso: máximo 2 frases. A primeira descreve a causa, a segunda indica a ação
