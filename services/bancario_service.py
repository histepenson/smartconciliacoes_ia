import pandas as pd

from tools.banco.calc_diferencas_banco import calcular_diferencas_bancarias


def calcular(extrato: list[dict], razao: list[dict]) -> dict:
    df_extrato = pd.DataFrame(extrato)
    df_razao = pd.DataFrame(razao)
    return calcular_diferencas_bancarias(df_extrato, df_razao)
