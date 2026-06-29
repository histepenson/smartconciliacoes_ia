from typing import Any

from pydantic import BaseModel


class MatchCt2SftRequest(BaseModel):
    ct2_recs: list[dict[str, Any]]
    sft_recs: list[dict[str, Any]]
    campo_valor_sft: str = "valcont"
    campo_valor_ct2: str = "debito"
    tolerancia: float = 0.10


class MatchCt2SftResponse(BaseModel):
    ct2_resultado: list[dict[str, Any]]
    sft_resultado: list[dict[str, Any]]
