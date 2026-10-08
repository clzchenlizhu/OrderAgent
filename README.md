# 智能客服多Agent系统

基于LangGraph + MCP + A2A协议的企业级智能客服问答平台，融合RAG检索、NL2SQL数据查询、ReAct工具调用，实现订单查询、物流追踪、工单处理等客服场景的自动化响应。

## 技术栈

- **Agent编排**: LangGraph (主从式多Agent架构)
- **工具协议**: MCP (Model Context Protocol) + A2A (Agent-to-Agent)
- **大模型**: Qwen (通义千问)
- **RAG检索**: BM25 + 向量混合检索 + RRF融合 + Rerank精排
- **数据库**: MySQL (业务数据) + Redis (缓存)
- **前端**: Streamlit 客服工作台
- **部署**: FastAPI 后端服务

## 项目结构

```
├── app.py              # Streamlit前端入口
├── main.py             # 主流程入口
├── config.py           # 配置管理
├── main_prompts.py     # Prompt模板管理
├── create_logger.py    # 日志工具
├── .env                # 环境变量配置
├── requirements.txt    # Python依赖
├── a2a_server/         # A2A子Agent服务
│   ├── order_query_server.py    # 订单查询Agent
│   ├── logistics_query_server.py # 物流查询Agent
│   └── ticket_handle_server.py   # 工单处理Agent
├── mcp_server/         # MCP工具服务
│   ├── order_mcp.py    # 订单查询工具
│   ├── logistics_mcp.py # 物流查询工具
│   └── ticket_mcp.py   # 工单操作工具
├── sql/                # 数据库脚本
│   └── create_customer_tables.sql # 建表+测试数据
└── utils/              # 工具函数
```

## 核心功能

1. **多Agent路由**: 主Agent识别用户意图，动态分发到对应子Agent处理
2. **RAG知识检索**: 混合检索召回客服知识库，精排后生成答案
3. **NL2SQL数据查询**: 自然语言转SQL，安全网关拦截写操作
4. **ReAct工具调用**: 工单Agent支持多步推理，自主调用工具完成复杂任务
5. **多轮对话**: 上下文记忆，支持追问和信息补全
6. **全链路追踪**: 请求ID贯穿全链路，日志可追溯
7. **Redis缓存**: 热点查询结果缓存，降低数据库压力（支持降级）

## 快速开始

1. 安装依赖: `pip install -r requirements.txt`
2. 配置 `.env` 文件，填入API Key和数据库连接
3. 执行建表SQL: `mysql -u root -p < sql/create_customer_tables.sql`
4. 依次启动MCP服务和A2A服务
5. 启动Streamlit: `streamlit run app.py`
