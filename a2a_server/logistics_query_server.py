import json
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from python_a2a import A2AServer, run_server, AgentCard, AgentSkill, TaskStatus, TaskState, Message, TextContent, \
    MessageRole, Task
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from dev08_agent.SmartVoyage.config import Config
from datetime import datetime
import pytz

from dev08_agent.SmartVoyage.create_logger import logger

conf = Config()

# 初始化LLM
llm = ChatOpenAI(
    model=conf.model_name,
    base_url=conf.base_url,
    api_key=conf.api_key,
    temperature=0.1
)

# 物流数据表 schema
table_schema_string = """
CREATE TABLE IF NOT EXISTS logistics (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id VARCHAR(50) NOT NULL COMMENT '订单编号',
    tracking_number VARCHAR(50) COMMENT '物流单号',
    logistics_company VARCHAR(50) COMMENT '物流公司',
    logistics_status VARCHAR(50) COMMENT '物流状态：已发货/运输中/已签收/异常',
    sender_name VARCHAR(50) COMMENT '发件人',
    sender_phone VARCHAR(20) COMMENT '发件人电话',
    receiver_name VARCHAR(50) COMMENT '收件人',
    receiver_phone VARCHAR(20) COMMENT '收件人电话',
    send_address VARCHAR(200) COMMENT '发货地址',
    receive_address VARCHAR(200) COMMENT '收货地址',
    send_time DATETIME COMMENT '发货时间',
    estimated_delivery_time DATETIME COMMENT '预计送达时间',
    actual_delivery_time DATETIME COMMENT '实际送达时间',
    current_location VARCHAR(200) COMMENT '当前物流位置',
    latest_remark VARCHAR(200) COMMENT '最新物流备注',
    update_time DATETIME COMMENT '数据更新时间',
    UNIQUE KEY unique_order_id (order_id)
) ENGINE=INNODB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='物流信息表';
"""

# 生成SQL的提示词
sql_prompt = ChatPromptTemplate.from_template(
    """
系统提示：你是一个专业的物流SQL生成器，需要从对话历史（含用户的问题）中提取关键信息，然后基于logistics表生成SELECT语句。
- 如果用户需要查物流，则至少需要订单号或物流单号。如果对话历史中缺乏必要的信息，可以向其追问，输出格式为json格式，如示例所示；如果对话历史中信息齐全，则输出纯SQL即可。
- 如果用户问与物流无关的问题，则模仿最后2个示例回复即可。


示例：
- 对话: user: 帮我查一下订单ORD001的物流
输出: SELECT order_id, tracking_number, logistics_company, logistics_status, sender_name, receiver_name, send_address, receive_address, send_time, estimated_delivery_time, current_location, latest_remark FROM logistics WHERE order_id = 'ORD001'
- 对话: user: 我的快递到哪了？单号SF1234567890
输出: SELECT order_id, tracking_number, logistics_company, logistics_status, current_location, latest_remark, estimated_delivery_time FROM logistics WHERE tracking_number = 'SF1234567890'
- 对话: user: 查一下物流
输出: {{"status": "input_required", "message": "请提供订单编号或物流单号，例如 'ORD001'。"}}
- 对话: user: 我的快递\nassistant: 请提供订单号。\nuser: ORD002
输出: SELECT order_id, tracking_number, logistics_company, logistics_status, current_location, latest_remark, estimated_delivery_time FROM logistics WHERE order_id = 'ORD002'
- 对话: user: 北京发上海的快递现在什么状态
输出: SELECT order_id, tracking_number, logistics_status, current_location, latest_remark FROM logistics WHERE send_address LIKE '%北京%' AND receive_address LIKE '%上海%'
- 对话: user: 你好
输出: {{"status": "input_required", "message": "请提供订单编号或物流单号，例如 'ORD001'。"}}
- 对话: user: 今天有什么好吃的
输出: {{"status": "input_required", "message": "请提供物流相关查询，包括订单号或物流单号。"}}

logistics表结构：{table_schema_string}
对话历史: {conversation}
当前日期: {current_date} (Asia/Shanghai)
    """
)

# 定义查询函数
async def get_logistics(sql):
    try:
        # 启动 MCP server，通过streamable建立连接
        async with streamablehttp_client("http://127.0.0.1:8001/mcp") as (read, write, _):
            # 使用读写通道创建 MCP 会话
            async with ClientSession(read, write) as session:
                try:
                    await session.initialize()
                    # 工具调用
                    result = await session.call_tool("query_logistics", {"sql": sql})
                    result_data = json.loads(result) if isinstance(result, str) else result
                    logger.info(f"物流查询结果：{result_data}")
                    return result_data.content[0].text
                except Exception as e:
                    logger.error(f"物流 MCP 测试出错：{str(e)}")
                    return {"status": "error", "message": f"物流 MCP 查询出错：{str(e)}"}
    except Exception as e:
        logger.error(f"连接或会话初始化时发生错误: {e}")
        return {"status": "error", "message": "连接或会话初始化时发生错误"}


# Agent卡片定义
agent_card = AgentCard(
    name="LogisticsQueryAssistant",
    description="基于LangChain提供物流查询服务的助手",
    url="http://localhost:5006",
    version="1.0.0",
    capabilities={"streaming": True, "memory": True},
    skills=[
        AgentSkill(
            name="execute logistics query",
            description="执行物流查询，返回物流信息数据库结果，支持自然语言输入",
            examples=["查一下ORD001的物流", "我的快递到哪了", "SF1234567890物流状态"]
        )
    ]
)


# 物流查询服务器类
class LogisticsQueryServer(A2AServer):
    def __init__(self):
        super().__init__(agent_card=agent_card)
        self.llm = llm
        self.sql_prompt = sql_prompt
        self.schema = table_schema_string

    # 定义生成SQL查询方法，输入对话历史，返回SQL或追问JSON
    def generate_sql_query(self, conversation: str) -> dict:
        try:
            chain = self.sql_prompt | self.llm
            current_date = datetime.now(pytz.timezone('Asia/Shanghai')).strftime("%Y-%m-%d")
            output = chain.invoke({"conversation": conversation, "current_date": current_date, "table_schema_string": self.schema}).content.strip()
            logger.info(f"原始 LLM 输出: {output}")
            if output.startswith("{"):
                return json.loads(output)
            else:
                return {"status": "sql", "sql": output}

        except Exception as e:
            logger.error(f"生成SQL查询出错: {e}")
            return {"status": "input_required", "message": "查询无效，请提供订单编号或物流单号。"}

    # 处理任务：提取输入，生成SQL，调用MCP，格式化结果
    def handle_task(self, task):
        content = (task.message or {}).get("content", {})
        conversation = content.get("text", "") if isinstance(content, dict) else ""
        logger.info(f"对话历史及用户问题: {conversation}")

        try:
            sql_result = self.generate_sql_query(conversation)
            if sql_result.get("status") == "input_required":
                task.status = TaskStatus(state=TaskState.INPUT_REQUIRED,
                                         message={"role": "agent", "content": {"text": sql_result["message"]}})
                return task
            else:
                sql_query = sql_result["sql"]
                logger.info(f"SQL查询语句: {sql_query}")

                logistics_result = asyncio.run(get_logistics(sql_query))

                response = json.loads(logistics_result) if isinstance(logistics_result, str) else logistics_result
                logger.info(f"MCP 返回: {response}")
                if response.get("status") == "success":
                    data = response.get("data", [])
                    response_text = "\n".join([
                                                  f"订单号: {d['order_id']}\n物流单号: {d['tracking_number']}\n物流公司: {d['logistics_company']}\n物流状态: {d['logistics_status']}\n当前位置: {d['current_location']}\n最新动态: {d['latest_remark']}\n预计送达: {d['estimated_delivery_time']}"
                                                  for d in data])

                    task.artifacts = [{"parts": [{"type": "text", "text": response_text}]}]
                    task.status = TaskStatus(state=TaskState.COMPLETED)
                elif response.get("status") == "no_data":
                    response_text = response.get("message", "未查询到相关物流信息，请确认订单号是否正确。")

                    task.status = TaskStatus(state=TaskState.INPUT_REQUIRED,
                                             message={"role": "agent", "content": {"text": response_text}})
                else:
                    response_text = response.get("message", "查询失败，请重试或提供更多细节。")

                    task.status = TaskStatus(state=TaskState.FAILED,
                                             message={"role": "agent", "content": {"text": response_text}})

                return task

        except Exception as e:
            logger.error(f"查询失败: {str(e)}")

            task.status = TaskStatus(state=TaskState.FAILED,
                                     message={"role": "agent",
                                              "content": {"text": f"查询失败: {str(e)} 请重试或提供更多细节。"}})
            return task


if __name__ == "__main__":
    logistics_server = LogisticsQueryServer()
    run_server(logistics_server, host="127.0.0.1", port=5006)
