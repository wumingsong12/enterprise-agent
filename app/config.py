import os
from dotenv import load_dotenv
from app.core.llm_gateway import LLMGateway, make_provider

def build_gateway():
    load_dotenv()
    mode = os.getenv('APP_MODE','mock')
    if mode == 'mock':
        return None, []
    if mode != 'real':
        raise ValueError('APP_MODE must be mock or real')
    providers, clients = [], []
    #遍历主用/备用，fallback 没配 MODEL 就跳过（可选），否则检查 MODEL、API_KEY、BASE_URL 是否齐全，
    # 缺一个就 raise ValueError('Missing 变量名')。它不构造任何 client，目的是在创建资源前先全量校验、快速失败，
    # 保证第二轮构造时"要么全成功、要么一个都不建"，避免半初始化和资源泄漏。
    for prefix, name in [('LLM_', 'primary'), ('FALLBACK_', 'fallback')]:
        if name == 'fallback' and not os.getenv(prefix+'MODEL'):
            continue
        # Check all required configuration before constructing clients.
        for key in ('MODEL','API_KEY','BASE_URL'):
            if not os.getenv(prefix+key):
                raise ValueError(f'Missing {prefix+key}')
    for prefix, name in [('LLM_', 'primary'), ('FALLBACK_', 'fallback')]:
        if name == 'fallback' and not os.getenv(prefix+'MODEL'):
            continue
        provider, client = make_provider(name, os.environ[prefix+'MODEL'],
            os.environ[prefix+'API_KEY'], os.environ[prefix+'BASE_URL'],
            int(os.getenv(prefix+'RPM','30')))
        providers.append(provider)
        clients.append(client)
    return LLMGateway(providers, concurrency=3, total_timeout=45), clients
