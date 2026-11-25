from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class Task(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    intent: Literal['ORDER_QUERY','POLICY_QUERY','CONDITIONAL_REFUND','REFUND_REQUEST','OTHER']
    order_id: str | None = Field(description='用户提供的五位订单号，或 null')
    policy_type: Literal['GENERAL_REFUND','NOT_SHIPPED_REFUND']
