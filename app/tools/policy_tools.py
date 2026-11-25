from typing import Literal
from pydantic import BaseModel, ConfigDict

class PolicyArgs(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    policy_type: Literal['GENERAL_REFUND','NOT_SHIPPED_REFUND']

def get_refund_policy(args: PolicyArgs, actor: str):
    policies = {'GENERAL_REFUND':'模拟政策：退款资格取决于订单状态，提交前须确认。',
                'NOT_SHIPPED_REFUND':'模拟政策：未发货订单符合申请退款的基本条件，提交前须确认。'}
    return {'ok':True,'policy_type':args.policy_type,'policy':policies[args.policy_type]}
