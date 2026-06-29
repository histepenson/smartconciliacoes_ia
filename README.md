# SmartConciliacoes IA

Microservico que concentra as engines de **matching/diferencas** (fiscal,
financeiro, bancario e estoque) e o **diagnostico de divergencias**
("Analisar com IA") usados pelo `conciliacao-api`.

## Estrutura

Segue a mesma convencao de camadas do `conciliacao-api`:

```
Router (routers/) -> Schema (schemas/) -> Service (services/) -> Tools (tools/)
```

- `tools/` — copia **fiel** (sem alteracao de logica) dos 4 modulos de
  matching do `conciliacao-api`:
  - `tools/fiscal/match_ct2_sft.py` — Pre-Conferencia (CT2 x SFT)
  - `tools/calc_diferencas.py` — Financeiro x Contabilidade
  - `tools/banco/calc_diferencas_banco.py` — Extrato Bancario x Razao
  - `tools/estoque/calc_diferencas_estoque.py` — Kardex x Razao de Estoque
- `services/` — adapta JSON (list[dict]) <-> DataFrame e chama as `tools/`
  sem mudar o calculo. `analise_service.py` e `ia_service.py` sao a parte
  **nova** (diagnostico determinístico + explicacao via Claude).
- `routers/` — um por dominio + `/v1/analise/divergencia` (diagnostico).

## Autenticacao

Servico-a-servico via header `X-API-Key`, validado em `middleware/auth.py`
contra a env var `API_KEY`. Sem `API_KEY` configurada, a checagem fica
desabilitada (conveniente em desenvolvimento local).

## Endpoints

| Metodo | Rota | Equivalente no conciliacao-api |
|---|---|---|
| POST | `/api/v1/fiscal/match` | `tools/fiscal/match_ct2_sft.py::match_ct2_sft` |
| POST | `/api/v1/financeiro/diferencas` | `tools/calc_diferencas.py::calcular_diferencas` |
| POST | `/api/v1/bancario/diferencas` | `tools/banco/calc_diferencas_banco.py::calcular_diferencas_bancarias` |
| POST | `/api/v1/estoque/diferencas` | `tools/estoque/calc_diferencas_estoque.py::calcular_diferencas_estoque` |
| POST | `/api/v1/analise/divergencia` | (novo) diagnostico do botao "Analisar com IA" |

Schemas completos em `schemas/`. Os 4 primeiros endpoints recebem/retornam
exatamente os mesmos `dict`/`DataFrame` que as funções originais — só a
borda (JSON) é nova.

### `/api/v1/analise/divergencia`

Recebe os registros que **não casaram** de cada lado (ex.: `ct2_detalhes`
com `matched=False` e `sft_detalhes` com `matched=False`, já calculados pelo
conciliacao-api), a configuração usada no matching (ex.: `cfops`/`tes_codes`/
`especies` do LP) e, quando disponível, os candidatos **brutos** do outro
lado sem o filtro aplicado (necessário para apontar com precisão "a nota
existe, só não entrou porque o CFOP X não está configurado" — sem isso o
diagnóstico cai no genérico "sem correspondência").

O cálculo da causa (`diagnostico`) é **100% determinístico** — roda em
Python puro, nunca passa pelo modelo. A `explicacao` em texto é opcional
(`gerar_explicacao_ia`) e só formata o diagnóstico já calculado; sem
`ANTHROPIC_API_KEY` configurada, devolve um texto-fallback (lista dos
motivos) em vez de chamar a IA.

Exemplo de payload (caso real "DEVOLUCAO DE COMPRA" sem matching):

```json
{
  "dominio": "fiscal",
  "contexto": {"lp_codigo": "610", "descricao": "DEVOLUCAO DE COMPRA", "diferenca": 1144.95},
  "registros_nao_conciliados_a": [
    {"historico": "DEVOLUCAO COMPRA NFE 2202566", "debito": 12.65}
  ],
  "rotulo_a": "CT2 (razao)",
  "rotulo_b": "SFT (livro fiscal)",
  "config": {"cfops": ["5201", "6201", "5202", "6202", "5662", "6662", "5410", "6410", "5411", "6411", "5556", "6556"]},
  "candidatos_brutos_b": [
    {"nf": "002202566", "cfop": "5949", "tes": "999", "especie": "SPED", "valcont": 12.65}
  ]
}
```

## O que NAO esta aqui (de proposito)

A normalizacao/parsing de planilha (`tools/financeiro/base.py`,
`tools/banco/extrato_bancario.py`, `tools/estoque/kardex.py` etc.) continua
no `conciliacao-api` — e' ETL de entrada (le Excel/JSON do Protheus e
produz DataFrame normalizado), nao matching. Este servico recebe os dados
ja' normalizados.

## Integracao com conciliacao-api (PENDENTE)

Este projeto ainda **nao esta cablado** ao `conciliacao-api`. As funcoes
originais em `tools/`/`services/pre_conferencia_service.py` (e equivalentes
de financeiro/bancario/estoque) continuam rodando localmente la' -- nada foi
removido. Quando este servico estiver no ar (Railway) e validado batendo
igual ao calculo local, o cutover (trocar a chamada local por uma chamada
HTTP a este servico) e' uma etapa separada e deliberada.

## Deploy (Railway)

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8000   # dev local
```

`Procfile` ja' configurado para o Railway (`web: uvicorn main:app --host 0.0.0.0 --port $PORT`).
Configurar `API_KEY` e (opcional) `ANTHROPIC_API_KEY` nas variaveis de
ambiente do projeto no Railway.
