# EnterpriseAgent Mini — Lesson 10

教学项目：企业订单与退款政策只读助手。所有数据为模拟数据，绝不执行真实退款。

## Windows PowerShell

解压到独立目录，进入包含 `requirements.txt` 的目录：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m unittest discover -s tests -v
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000 。默认 APP_MODE=mock，采用本地规则模拟任务分类，无需 Key、不产生模型费用。注意 mock 不代表真实模型准确率。

## 真实模型

修改 `.env`：APP_MODE=real，并填写原来能成功调用的 LLM_API_KEY、LLM_BASE_URL、LLM_MODEL。重启服务。主业务使用第九课 Gateway 进行普通文本 JSON 任务理解（Prompt 中附 Schema + Pydantic + 一次修复），而不是 json_schema 原生模式。备用模型可选，且必须允许数据跨供应商传输。不要提交 .env。

## 试验场景

同一 session_id：
- 查询订单12345的物流状态（未发货）
- 这个订单能否退款（复用已授权订单号，再查询状态及政策）
- 如果订单23456没发货，告诉我能否退款（已发货，跳过未发货政策）
- 查询订单88888（不存在或无权访问）
- 查询订单（请求补充订单号）
- 未发货订单的退款政策是什么（政策工具）

换 session_id 后，询问“这个订单能否退款”应要求订单号。

## 可选：原生 Function Calling 与真实文本流

使用已经验证可用的模型配置运行 `python -m app.core.native_agent`。它会实际调用模型 API，直接展示流式 delta、按 index 拼接工具请求、执行注册的只读工具并回传结果。该路径不接入 Gateway、不自动降级，不认证最终模型文字；不要用于真实业务。各供应商工具流与思考参数兼容性需要本机验证。主业务 SSE 只流式推送真实任务事件，不逐 Token 输出模板答案。

## 设计限制

主流程是 LLM 任务分类 + Python 确定性工作流，不是无限制自主 ReAct。会话仅保留三轮和最后授权订单号，不做摘要、不持久化；每个会话可串行访问，最多 256 个内存会话，重启清空。服务默认固定演示身份 user_001，没有真实身份认证；仅绑定本地，不可公开部署。模型分类仍可能错误；订单 ID 来源检查、权限、条件判断和业务答案由后端控制。Gateway 单进程本地 RPM/并发限制、软成本统计，未实现 TPM 或分布式限流。前端展示模拟数据，真实企业日志需脱敏。测试仅使用模拟响应和 ASGI TestClient，未联网调用真实模型或浏览器端到端验证。
