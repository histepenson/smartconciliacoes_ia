import pandas as pd

from tools.calc_diferencas import calcular_diferencas


def calcular(financeiro: list[dict], contabilidade: list[dict]) -> dict:
    df_fin = pd.DataFrame(financeiro)
    df_cont = pd.DataFrame(contabilidade)

    # salvar_arquivo=False: a API e' stateless (sem disco persistente no
    # Railway) -- a exportacao em Excel continua existindo no conciliacao-api,
    # que e' quem tem o storage/endpoint de download.
    resultado = calcular_diferencas(df_fin, df_cont, salvar_arquivo=False)

    return {
        "registros": resultado["df_completo"].to_dict("records"),
        "resumo": resultado["resumo"],
    }
