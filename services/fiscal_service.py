from tools.fiscal.match_ct2_sft import match_ct2_sft


def match(
    ct2_recs: list[dict],
    sft_recs: list[dict],
    campo_valor_sft: str = "valcont",
    campo_valor_ct2: str = "debito",
    tolerancia: float = 0.10,
) -> tuple[list[dict], list[dict]]:
    return match_ct2_sft(
        ct2_recs, sft_recs,
        campo_valor_sft=campo_valor_sft,
        campo_valor_ct2=campo_valor_ct2,
        tolerancia=tolerancia,
    )
