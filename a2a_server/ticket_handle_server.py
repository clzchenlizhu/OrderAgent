import json
import asyncio
import time
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from python_a2a import A2AServer, run_server, AgentCard, AgentSkill, TaskStatus, TaskState
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from create_logger import logger, set_request_id
from config import Config

conf = Config()

llm = ChatOpenAI(
    model=conf.model_name,
    base_url=conf.base_url,
    api_key=conf.api_key,
    temperature=0.1
)


async def call_mcp_tool(tool_name, arguments, max_retries=2, timeout=5):
    """调用MCP工具，带超时控制和失败重试。自动根据工具名路由到对应MCP服务。"""

    # 工具名 → MCP服务地址映射
    mcp_url_map = {
        "create_ticket": "http://127.0.0.1:8003/mcp",
        "query_ticket": "http://127.0.0.1:8003/mcp",
        "query_orders": "http://127.0.0.1:8002/mcp",
        "query_logistics": "http://127.0.0.1:8001/mcp",
    }
    mcp_url = mcp_url_map.get(tool_name, "http://127.0.0.1:8003/mcp")

    for attempt in range(max_retries + 1):
        try:
            logger.info(f"第{attempt+1}次尝试调用MCP工具: {tool_name}")
            async with streamablehttp_client(mcp_url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments)
                    result_text = result.content[0].text
                    logger.info(f"MCP工具调用成功: {tool_name}（第{attempt+1}次尝试）")
                    return result_text
        except asyncio.TimeoutError:
            logger.error(f"MCP工具调用超时（{timeout}秒），第{attempt+1}次尝试: {tool_name}")
        except Exception as e:
            logger.error(f"MCP工具调用失败：{str(e)}，第{attempt+1}次尝试: {tool_name}")

        if attempt < max_retries:
            await asyncio.sleep(1)

    return {"status": "error", "message": "服务暂时不可用，请稍后再试"}


async def handle_ticket(conversation):
    """ReAct模式：思考→行动→观察→再思考，直到信息足够回答"""

    system_prompt = """你是一个售后工单处理智能体。你可以调用以下工具：

可用工具（注意参数名！）：
1. query_orders：查询订单信息。参数名必须是sql，值是完整的SELECT语句，例如：{"sql": "SELECT * FROM orders WHERE order_id = 'ORD001'"}。返回订单状态、金额、商品名等。
2. query_logistics：查询物流轨迹。参数名必须是sql，值是完整的SELECT语句，例如：{"sql": "SELECT * FROM logistics WHERE order_id = 'ORD001'"}。返回物流状态和轨迹。
3. create_ticket：创建售后工单。参数：{"order_id": "订单号", "ticket_type": "类型", "description": "问题描述"}。类型只能是：退款/退货/换货/投诉/发票。
4. query_ticket：查询工单进度。参数：{"order_id": "订单号"}。

重要规则：
- query_orders和query_logistics的参数名是sql，不是query！必须传完整的SELECT语句！
- 不要传自然语言，会被安全网关拦截！

工作方式（ReAct循环）：
你要一步步思考并行动。每一步输出JSON：
- 如果需要调用工具：{"thought": "你的思考", "action": "tool_name", "action_input": {参数}}
- 如果信息足够可以回答用户了：{"thought": "你的思考", "final_answer": "给用户的最终回答"}

规则：
1. 最多思考4步，不要浪费步骤在试错上，第一次就用正确的参数格式
2. 创建工单前，先查一下订单是否存在、状态如何，确认合理再创建
3. 如果用户说"查一下订单如果没发货就催一下"，你要先查订单，根据结果决定要不要创建工单
4. 信息不足（比如没有订单号）时直接final_answer追问，不要瞎猜
5. final_answer要用客服友好的语气，不要输出JSON
"""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=conversation)
    ]

    max_steps = 5
    step = 0

    while step < max_steps:
        step += 1
        logger.info(f"ReAct第{step}步思考中...")

        response = llm.invoke(messages)
        raw = response.content.strip()
        import re
        raw = re.sub(r'^```json\s*|\s*```$', '', raw).strip()
        logger.info(f"ReAct第{step}步LLM输出: {raw}")

        try:
            decision = json.loads(raw)
        except json.JSONDecodeError:
            # LLM没输出JSON，直接当最终回答
            return {"status": "success", "message": raw}

        thought = decision.get("thought", "")
        logger.info(f"ReAct思考: {thought}")

        # 如果LLM说可以回答了，跳出循环
        if "final_answer" in decision:
            final = decision["final_answer"]
            logger.info(f"ReAct完成，共{step}步，最终回答: {final[:100]}...")
            return {"status": "success", "message": final}

        # 否则执行工具调用
        action = decision.get("action", "")
        action_input = decision.get("action_input", {})
        if not action:
            return {"status": "success", "message": decision.get("final_answer", "处理完成")}

        logger.info(f"ReAct执行工具: {action}, 参数: {action_input}")
        tool_result = await call_mcp_tool(action, action_input)
        logger.info(f"ReAct工具返回: {str(tool_result)[:200]}...")

        # 把工具返回结果加进上下文，让LLM下一步能看到
        messages.append(response)  # 之前的思考
        messages.append(HumanMessage(content=f"工具{action}返回结果：\n{tool_result}\n\n请继续思考下一步。"))

    # 超过最大步数，让LLM基于已有信息总结回答
    logger.info("ReAct达到最大步数5步，强制总结")
    messages.append(HumanMessage(content="已达到最大步数限制，请基于已有信息给用户一个最终回答。"))
    final_response = llm.invoke(messages)
    return {"status": "success", "message": final_response.content}


agent_card = AgentCard(
    name="TicketHandleAssistant",
    description="售后工单处理助手，基于ReAct推理-行动循环，支持多步决策：先查订单/物流状态，再决定是否创建工单，可跨MCP服务调用工具",
    url="http://localhost:5007",
    version="1.0.0",
    capabilities={"streaming": True, "memory": True},
    skills=[
        AgentSkill(
            name="handle ticket",
            description="ReAct模式处理售后需求：查询订单状态、查询物流轨迹、创建售后工单、查询工单进度，支持多步推理决策",
            examples=["查一下ORD001订单状态，如果没发货就帮我创建催单工单", "为ORD003创建退款工单", "查询我的工单进度"]
        )
    ]
)


class TicketHandleServer(A2AServer):
    def __init__(self):
        super().__init__(agent_card=agent_card)

    def handle_task(self, task):
        start_time = time.time()
        set_request_id()
        content = (task.message or {}).get("content", {})
        conversation = content.get("text", "") if isinstance(content, dict) else ""
        logger.info(f"工单Agent收到请求: {conversation}")

        try:
            result = asyncio.run(handle_ticket(conversation))
            logger.info(f"工单处理结果: {result}")

            elapsed = round(time.time() - start_time, 2)
            logger.info(f"工单处理耗时: {elapsed}s")

            if result.get("status") == "need_more":
                task.status = TaskStatus(state=TaskState.INPUT_REQUIRED,
                                         message={"role": "agent", "content": {"text": result["message"]}})
            elif result.get("status") == "success":
                msg = result["message"] + f"\n\n⏱️ 本次耗时: {elapsed}秒"
                task.artifacts = [{"parts": [{"type": "text", "text": msg}]}]
                task.status = TaskStatus(state=TaskState.COMPLETED)
            else:
                task.status = TaskStatus(state=TaskState.FAILED,
                                         message={"role": "agent", "content": {"text": result.get("message", "处理失败")}})
            return task
        except Exception as e:
            elapsed = round(time.time() - start_time, 2)
            logger.error(f"工单处理失败: {str(e)}, 耗时: {elapsed}s")
            task.status = TaskStatus(state=TaskState.FAILED,
                                     message={"role": "agent", "content": {"text": f"处理失败: {str(e)}"}})
            return task


if __name__ == "__main__":
    ticket_server = TicketHandleServer()
    print("=== 工单处理Agent启动 ===")
    run_server(ticket_server, host="127.0.0.1", port=5007)
