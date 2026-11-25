from pydantic import ValidationError
from app.tools.order_tools import OrderArgs, query_order
from app.tools.policy_tools import PolicyArgs, get_refund_policy

REGISTRY = {'query_order':(OrderArgs,query_order), 'get_refund_policy':(PolicyArgs,get_refund_policy)}
TOOLS = [{'type':'function','function':{'name':name,'description':desc,'parameters':REGISTRY[name][0].model_json_schema()}}
         for name,desc in [('query_order','查询当前用户订单及物流，仅只读'),('get_refund_policy','查询模拟退款政策，仅只读')]]
#REGISTRY[name][0].model_json_schema() 这样就可以减少手动维护 Pydantic 模型和 Tool Schema 两份定义的工作量。
def execute_tool(name, arguments, actor):
    if name not in REGISTRY:
        return {'ok':False,'error':'UNKNOWN_TOOL'}
    schema, handler = REGISTRY[name]
    try:
        args = schema.model_validate(arguments)
    except ValidationError:
        return {'ok':False,'error':'INVALID_TOOL_ARGUMENTS'}
    return handler(args, actor)
#actor 就是调用者的身份标识（通常是用户 ID，如 user_001）。它由调用方传入，一路透传到底层 handler
