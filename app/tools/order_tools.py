from pydantic import BaseModel, ConfigDict, Field

class OrderArgs(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    order_id: str = Field(pattern=r'^[0-9]{5}$')

ORDERS = {
    '12345': {'owner':'user_001','status':'NOT_SHIPPED','logistics':'尚未交给物流公司'},
    '23456': {'owner':'user_001','status':'SHIPPED','logistics':'模拟运输途中'},
    '88888': {'owner':'user_002','status':'NOT_SHIPPED','logistics':'尚未交给物流公司'},
}

def query_order(args: OrderArgs, actor: str):
    record = ORDERS.get(args.order_id)
    if not record or record['owner'] != actor:
        return {'ok':False,'error':'ORDER_NOT_FOUND_OR_FORBIDDEN'}
    return {'ok':True,'order_id':args.order_id,'status':record['status'],'logistics':record['logistics']}
