import json
import asyncio
import time
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from python_a2a import A2AServer, run_server, AgentCard, AgentSkill, TaskStatus, TaskState
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from config import Config
from datetime import datetime
import pytz
from create_logger import logger, set_request_id

conf = Config()

llm = ChatOpenAI(
    model=conf.model_name,
    base_url=conf.base_url,
    api_key=conf.api_key,
    temperature=0.1
)

table_schema_string = """
CREATE TABLE orders (
    order_id VARCHAR(32) PRIMARY KEY COMMENT '订单号',
    user_id VARCHAR(32) COMMENT '用户ID',
    product_name VARCHAR(128) COMMENT '商品名称',
    status VARCHAR(32) COMMENT '订单状态：待付款/待发货/已发货/已完成/退款中/已退款',
    amount DECIMAL(10,2) COMMENT '订单金额',
    create_time DATETIME COMMENT '下单时间'
) ENGINE=INNODB DEFAULT CHARSET=utf8mb4 COMMENT='订单表';
"""

sql_prompt = ChatPromptTemplate.from_template(
    """
系统提示：你是一个专业的订单查询SQL生成器，需要从对话历史（含用户的问题）中提取关键信息，然后基于orders表生成SELECT语句。
- 如果用户需要查订单，则至少需要订单号(order_id)。如果对话历史中缺乏订单号信息，可以向其追问，输出格式为json格式；如果信息齐全，则输出纯SQL即可。
- 只允许生成SELECT查询语句，禁止生成INSERT/UPDATE/DELETE。
- 查询字段：order_id, product_name, status, amount, create_time。

示例：
- 对话: user: 查询订单ORD001
输出: SELECT order_id, product_name, status, amount, create_time FROM orders WHERE order_id = 'ORD001'
- 对话: user: 我的订单怎么样了\nassistant: 请提供订单号\nuser: ORD002
输出: SELECT order_id, product_name, status, amount, create_time FROM orders WHERE order_id = 'ORD002'
- 对话: user: 查一下退款中的订单
输出: SELECT order_id, product_name, status, amount, create_time FROM orders WHERE status = '退款中'
- 对话: user: 我的订单
输出: {{"status": "input_required", "message": "请提供您的订单号，例如ORD001。"}}
- 对话: user: 你好
输出: {{"status": "input_required", "message": "请提供订单号，例如ORD001，我帮您查询订单状态。"}}

orders表结构：{table_schema_string}
对话历史: {conversation}
当前日期: {current_date} (Asia/Shanghai)
    """
)


async def _do_query_order(sql):
    """实际执行订单查询"""
    async with streamablehttp_client("http://127.0.0.1:8002/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("query_orders", {"sql": sql})
            result_data = json.loads(result) if isinstance(result, str) else result
            return result_data.content[0].text


async def query_order(sql, max_retries=2, timeout=5):
    """订单查询，带超时控制和失败重试"""
    for attempt in range(max_retries + 1):
        try:
            logger.info(f"第{attempt+1}次尝试查询订单")
            result = await asyncio.wait_for(_do_query_order(sql), timeout=timeout)
            logger.info(f"订单查询成功（第{attempt+1}次尝试）")
            return result
        except asyncio.TimeoutError:
            logger.error(f"订单查询超时（{timeout}秒），第{attempt+1}次尝试")
        except Exception as e:
            logger.error(f"订单查询失败：{str(e)}，第{attempt+1}次尝试")

        if attempt < max_retries:
            await asyncio.sleep(1)

    return {"status": "error", "message": "订单查询服务暂时不可用，请稍后再试"}


agent_card = AgentCard(
    name="OrderQueryAssistant",
    description="订单查询助手，支持查询订单状态、商品、金额等信息",
    url="http://localhost:5005",
    version="1.0.0",
    capabilities={"streaming": True, "memory": True},
    skills=[
        AgentSkill(
            name="query order",
            description="根据订单号查询订单详情，包括商品名称、状态、金额、下单时间",
            examples=["查询订单ORD001的状态", "我的ORD002订单怎么样了", "查一下退款中的订单"]
        )
    ]
)


class OrderQueryServer(A2AServer):
    def __init__(self):
        super().__init__(agent_card=agent_card)
        self.llm = llm
        self.sql_prompt = sql_prompt
        self.schema = table_schema_string

    def generate_sql_query(self, conversation: str) -> dict:
        try:
            chain = self.sql_prompt | self.llm
            current_date = datetime.now(pytz.timezone('Asia/Shanghai')).strftime("%Y-%m-%d")
            output = chain.invoke({"conversation": conversation, "current_date": current_date,
                                   "table_schema_string": self.schema}).content.strip()
            logger.info(f"原始 LLM 输出: {output}")
            if output.startswith("{"):
                return json.loads(output)
            else:
                return {"status": "sql", "sql": output}
        except Exception as e:
            logger.error(f"生成SQL出错: {e}")
            return {"status": "input_required", "message": "查询无效，请提供订单号。"}

    def handle_task(self, task):
        start_time = time.time()
        # 生成或获取request_id
        set_request_id()
        content = (task.message or {}).get("content", {})
        conversation = content.get("text", "") if isinstance(content, dict) else ""
        logger.info(f"订单Agent收到请求: {conversation}")

        try:
            sql_result = self.generate_sql_query(conversation)
            if sql_result.get("status") == "input_required":
                elapsed = round(time.time() - start_time, 2)
                task.status = TaskStatus(state=TaskState.INPUT_REQUIRED,
                                         message={"role": "agent", "content": {"text": sql_result["message"]}})
                logger.info(f"订单查询耗时: {elapsed}s")
                return task
            else:
                sql_query = sql_result["sql"]
                logger.info(f"SQL查询语句: {sql_query}")
                order_result = asyncio.run(query_order(sql_query))
                response = json.loads(order_result) if isinstance(order_result, str) else order_result
                logger.info(f"MCP 返回: {response}")

                elapsed = round(time.time() - start_time, 2)
                logger.info(f"订单查询耗时: {elapsed}s")

                if response.get("status") == "success":
                    data = response.get("data", [])
                    response_text = "\n".join([
                        f"订单号: {d['order_id']}，商品: {d['product_name']}，状态: {d['status']}，金额: {d['amount']}元，下单时间: {d['create_time']}"
                        for d in data])
                    response_text += f"\n\n⏱️ 本次耗时: {elapsed}秒"
                    task.artifacts = [{"parts": [{"type": "text", "text": response_text}]}]
                    task.status = TaskStatus(state=TaskState.COMPLETED)
                elif response.get("status") == "no_data":
                    response_text = response.get("message", "未找到该订单，请确认订单号。")
                    task.status = TaskStatus(state=TaskState.INPUT_REQUIRED,
                                             message={"role": "agent", "content": {"text": response_text}})
                else:
                    response_text = response.get("message", "查询失败，请重试。")
                    task.status = TaskStatus(state=TaskState.FAILED,
                                             message={"role": "agent", "content": {"text": response_text}})
                return task
        except Exception as e:
            elapsed = round(time.time() - start_time, 2)
            logger.error(f"查询失败: {str(e)}, 耗时: {elapsed}s")
            task.status = TaskStatus(state=TaskState.FAILED,
                                     message={"role": "agent", "content": {"text": f"查询失败: {str(e)}"}})
            return task


if __name__ == "__main__":
    order_server = OrderQueryServer()
    print("=== 订单查询Agent启动 ===")
    run_server(order_server, host="127.0.0.1", port=5005)
