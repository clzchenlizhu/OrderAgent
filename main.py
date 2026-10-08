import asyncio
import json
import uuid
from datetime import datetime
import pytz
import re
from python_a2a import AgentNetwork, TextContent, Message, MessageRole, Task
from langchain_openai import ChatOpenAI

from config import Config
from create_logger import logger, set_request_id
from main_prompts import CustomerServicePrompts

conf = Config()

# 初始化全局变量
messages = []
agent_network = None
llm = None
agent_urls = {}
conversation_history = ""


def initialize_system():
    global agent_network, llm, agent_urls, conversation_history
    agent_urls = {
        "OrderQueryAssistant": "http://localhost:5005",      # 订单查询
        "LogisticsQueryAssistant": "http://localhost:5006",   # 物流查询
        "TicketHandleAssistant": "http://localhost:5007"      # 工单处理
    }
    network = AgentNetwork(name="客服助手网络")
    network.add("OrderQueryAssistant", "http://localhost:5005")
    network.add("LogisticsQueryAssistant", "http://localhost:5006")
    network.add("TicketHandleAssistant", "http://localhost:5007")
    agent_network = network

    llm = ChatOpenAI(
        model=conf.model_name,
        api_key=conf.api_key,
        base_url=conf.base_url,
        temperature=0.1
    )
    conversation_history = ""


def intent_agent(user_input):
    global conversation_history, llm
    chain = CustomerServicePrompts.intent_prompt() | llm
    current_date = datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d')
    intent_response = chain.invoke(
        {"conversation_history": '\n'.join(conversation_history.split("\n")[-6:]),
         "query": user_input,
         "current_date": current_date}).content.strip()
    logger.info(f"意图识别原始响应: {intent_response}")

    intent_response = re.sub(r'^```json\s*|\s*```$', '', intent_response).strip()
    logger.info(f"清理后响应: {intent_response}")
    intent_output = json.loads(intent_response)
    intents = intent_output.get("intents", [])
    user_queries = intent_output.get("user_queries", {})
    follow_up_message = intent_output.get("follow_up_message", "")
    logger.info(f"intents: {intents}||user_queries: {user_queries}||follow_up_message: {follow_up_message}")
    return intents, user_queries, follow_up_message


def process_user_input(prompt):
    global messages, conversation_history, llm

    # 生成请求ID，贯穿全链路
    request_id = set_request_id()
    logger.info(f"收到用户请求，request_id={request_id}")

    messages.append({"role": "user", "content": prompt})
    conversation_history += f"\nUser: {prompt}"

    print("正在分析您的意图...")
    try:
        intents, user_queries, follow_up_message = intent_agent(prompt)

        if "out_of_scope" in intents:
            response = follow_up_message
            conversation_history += f"\nAssistant: {response}"
        elif follow_up_message != "":
            response = follow_up_message
            conversation_history += f"\nAssistant: {response}"
        else:
            responses = []
            routed_agents = []
            for intent in intents:
                logger.info(f"处理意图：{intent}")
                if intent == "order":
                    agent_name = "OrderQueryAssistant"
                elif intent == "logistics":
                    agent_name = "LogisticsQueryAssistant"
                elif intent == "ticket":
                    agent_name = "TicketHandleAssistant"
                else:
                    agent_name = None

                if agent_name:
                    query_str = user_queries.get(intent, {})
                    logger.info(f"{agent_name} 查询：{query_str}")
                    agent = agent_network.get_agent(agent_name)
                    chat_history = '\n'.join(conversation_history.split("\n")[-7:-1]) + f'\nUser: {query_str}'
                    message = Message(content=TextContent(text=chat_history), role=MessageRole.USER)
                    task = Task(id="task-" + str(uuid.uuid4()), message=message.to_dict())
                    raw_response = asyncio.run(agent.send_task_async(task))
                    logger.info(f"{agent_name} 原始响应: {raw_response}")

                    if raw_response.status.state == 'completed':
                        agent_result = raw_response.artifacts[0]['parts'][0]['text']
                    else:
                        agent_result = raw_response.status.message['content']['text']

                    if agent_name == "OrderQueryAssistant":
                        chain = CustomerServicePrompts.summarize_order_prompt() | llm
                        final_response = chain.invoke({"query": query_str, "raw_response": agent_result}).content.strip()
                    elif agent_name == "LogisticsQueryAssistant":
                        chain = CustomerServicePrompts.summarize_logistics_prompt() | llm
                        final_response = chain.invoke({"query": query_str, "raw_response": agent_result}).content.strip()
                    else:
                        final_response = agent_result

                    responses.append(final_response)
                    routed_agents.append(agent_name)
                else:
                    responses.append("暂不支持此业务。")

            response = "\n\n".join(responses)
            if routed_agents:
                logger.info(f"路由到代理：{routed_agents}")
            conversation_history += f"\nAssistant: {response}"

        print(f"\n客服回复：\n{response}\n")
        messages.append({"role": "assistant", "content": response})

    except json.JSONDecodeError as json_err:
        logger.error(f"意图识别JSON解析失败")
        error_message = f"意图识别解析失败：{str(json_err)}。请重试。"
        print(f"\n客服回复：\n{error_message}\n")
        messages.append({"role": "assistant", "content": error_message})
    except Exception as e:
        logger.error(f"处理异常: {str(e)}")
        error_message = f"处理失败：{str(e)}。请重试。"
        print(f"\n客服回复：\n{error_message}\n")
        messages.append({"role": "assistant", "content": error_message})


def display_agent_cards():
    print("\n🛠️ Agent Cards:")
    for agent_name in agent_network.agents.keys():
        agent_card = agent_network.get_agent_card(agent_name)
        agent_url = agent_urls.get(agent_name, "未知地址")
        print(f"\n--- Agent: {agent_name} ---")
        print(f"技能: {agent_card.skills}")
        print(f"描述: {agent_card.description}")
        print(f"地址: {agent_url}")
        print(f"状态: 在线")


if __name__ == "__main__":
    initialize_system()
    print("🤖 基于A2A的智能客服多Agent系统")
    print("欢迎体验智能客服对话！输入问题，按回车提交；输入'quit'退出；输入'cards'查看代理卡片。")
    display_agent_cards()

    while True:
        prompt = input("\n请输入您的问题: ").strip()
        if prompt.lower() == 'quit':
            print("感谢使用！再见！")
            break
        elif prompt.lower() == 'cards':
            display_agent_cards()
            continue
        elif not prompt:
            continue
        else:
            process_user_input(prompt)

    print("\n---")
    print("Powered by 智能客服多Agent系统 v1.0")
