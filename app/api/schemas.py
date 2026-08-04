from __future__ import annotations

from pydantic import BaseModel, Field


class InitDataPayload(BaseModel):
    init_data: str = Field(default="")


class PayoutPayload(BaseModel):
    init_data: str = Field(default="")
    amount_won: int = Field(default=0, ge=0)


class BalancePayload(BaseModel):
    init_data: str = Field(default="")


class GameRoundPayload(BaseModel):
    init_data: str = Field(default="")
    game_type: str
    bet: int = Field(gt=0)
    payout: int = Field(default=0, ge=0)
    multiplier: int = Field(default=0, ge=0)
    client_seed: str = Field(default="")
    server_seed_hash: str = Field(default="")
    server_seed: str = Field(default="")
    nonce: int = Field(default=0, ge=0)
    result_json: dict = Field(default_factory=dict)
