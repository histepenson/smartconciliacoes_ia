import pandas as pd

from tools.estoque.calc_diferencas_estoque import calcular_diferencas_estoque


def calcular(kardex: list[dict], razao: list[dict]) -> dict:
    df_kardex = pd.DataFrame(kardex)
    df_razao = pd.DataFrame(razao)
    return calcular_diferencas_estoque(df_kardex, df_razao)
