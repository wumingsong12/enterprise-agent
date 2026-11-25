import json
import re
from pathlib import Path
from app.schemas.task import Task
from pydantic import ValidationError

PROMPT = (Path(__file__).resolve().parents[1]/'prompts/router.txt').read_text(encoding='utf-8')
ORDER_ID = re.compile(r'(?<![0-9A-Za-z])[0-9]{5}(?![0-9A-Za-z])')

class RouterError(Exception):
    pass

def mock_task(question):
    ids = ORDER_ID.findall(question)
    oid = ids[0] if len(set(ids)) == 1 else None
    refund = any(x in question for x in ('退款','退货'))
    condition = any(x in question for x in ('未发货','没发货','没有发货','还未发货','尚未发货'))
    if refund and (oid or '这个订单' in question or '该订单' in question) and ('如果' in question or '能否' in question or '能不能' in question or condition):
        intent = 'CONDITIONAL_REFUND'
    elif refund and any(x in question for x in ('政策','规则','一般','条件','多久')) and not oid:
        intent = 'POLICY_QUERY'
    elif refund:
        intent = 'REFUND_REQUEST'
    elif any(x in question for x in ('订单','物流','发货','快递','包裹')):
        intent = 'ORDER_QUERY'
    else:
        intent = 'OTHER'
    return Task(intent=intent,order_id=oid,policy_type='NOT_SHIPPED_REFUND' if condition else 'GENERAL_REFUND')

async def route(question, gateway=None):
    if gateway is None:
        return mock_task(question)
    messages = [{'role':'system','content':PROMPT+'\nSchema:\n'+json.dumps(Task.model_json_schema(),ensure_ascii=False)},
                {'role':'user','content':question}]
    for attempt in range(2):
        result = await gateway.ask(messages)
        try:
            task = Task.model_validate_json(result.text)
            if task.order_id and task.order_id not in ORDER_ID.findall(question):
                raise ValueError('order_id not in current input')
            return task
        except (ValidationError,ValueError):
            if attempt == 1:
                raise RouterError('INVALID_TASK_OUTPUT')
            messages.append({'role':'assistant','content':result.text})
            messages.append({'role':'user','content':'上次 JSON 未通过结构或订单号来源校验。只根据原始用户需求重新输出完整合法 JSON。'})
