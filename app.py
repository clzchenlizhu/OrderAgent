import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
import asyncio
import uuid
import streamlit as st
from python_a2a import AgentNetwork, Message, TextContent, MessageRole, Task
from langchain_openai import ChatOpenAI
import json
from datetime import datetime
import pytz
import re

from config import Config
from main_prompts import CustomerServicePrompts
from create_logger import logger, set_request_id

conf = Config()

st.set_page_config(page_title="智能客服多Agent系统", layout="wide", page_icon="🤖")

st.markdown("""
<style>
.stChatMessage {
    background-color: #2c3e50 !important;
    border-radius: 12px !important;
    padding: 15px !important;
    margin-bottom: 15px !important;
    box-shadow: 0 3px 6px rgba(0,0,0,0.2) !important;
}
.stChatMessage.user {
    background-color: #34495e !important;
}
.stChatMessage .stMarkdown,
.stChatMessage .stMarkdown p,
.stChatMessage .stMarkdown span,
.stChatMessage .stMarkdown div,
.stChatMessage .stMarkdown strong,
.stChatMessage .stMarkdown em,
.stChatMessage .stMarkdown code {
    color: #ffffff !important;
}
.stChatMessage [data-testid="stChatMessageAvatarIcon"] {
    filter: brightness(1.2);
}
</style>
""", unsafe_allow_html=True)

if "messages" not in st.session_state:
    st.session_state.messages = []
if "agent_network" not in st.session_state:
    st.session_state.agent_urls = {
        "OrderQueryAssistant": "http://localhost:5005",
        "LogisticsQueryAssistant": "http://localhost:5006",
        "TicketHandleAssistant": "http://localhost:5007"
    }
    network = AgentNetwork(name="Customer Service Network")
    network.add("OrderQueryAssistant", "http://localhost:5005")
    network.add("LogisticsQueryAssistant", "http://localhost:5006")
    network.add("TicketHandleAssistant", "http://localhost:5007")
    st.session_state.agent_network = network
    st.session_state.llm = ChatOpenAI(
        model=conf.model_name,
        api_key=conf.api_key,
        base_url=conf.base_url,
        temperature=0.1
    )
    st.session_state.conversation_history = ""


def intent_agent(user_input):
    chain = CustomerServicePrompts.intent_prompt() | st.session_state.llm
    current_date = datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d')
    intent_response = chain.invoke(
        {"conversation_history": '\n'.join(st.session_state.conversation_history.split("\n")[-6:]),
         "query": user_input,
         "current_date": current_date}).content.strip()
    intent_response = re.sub(r'^```json\s*|\s*```$', '', intent_response).strip()
    intent_output = json.loads(intent_response)
    intents = intent_output.get("intents", [])
    user_queries = intent_output.get("user_queries", {})
    follow_up_message = intent_output.get("follow_up_message", "")
    return intents, user_queries, follow_up_message


st.title("🤖 智能客服多Agent系统")
st.markdown("基于MCP+A2A协议 | 订单查询 · 物流追踪 · 工单处理")

col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("💬 对话")
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("请输入您的问题，例如：查询订单ORD001的状态..."):
        # 生成请求ID，贯穿全链路
        request_id = set_request_id()
        logger.info(f"用户提问，request_id={request_id}，问题={prompt}")

        with st.chat_message("user"):
            st.markdown(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.session_state.conversation_history += f"\nUser: {prompt}"

        llm = st.session_state.llm

        with st.spinner("正在分析您的意图..."):
            try:
                intents, user_queries, follow_up_message = intent_agent(prompt)

                if "out_of_scope" in intents:
                    response = follow_up_message
                    st.session_state.conversation_history += f"\nAssistant: {response}"
                elif follow_up_message != "":
                    response = follow_up_message
                    st.session_state.conversation_history += f"\nAssistant: {response}"
                else:
                    responses = []
                    routed_agents = []
                    for intent in intents:
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
                            agent = st.session_state.agent_network.get_agent(agent_name)
                            chat_history = '\n'.join(st.session_state.conversation_history.split("\n")[-7:-1]) + f'\nUser: {query_str}'
                            message = Message(content=TextContent(text=chat_history), role=MessageRole.USER)
                            task = Task(id="task-" + str(uuid.uuid4()), message=message.to_dict())
                            raw_response = asyncio.run(agent.send_task_async(task))

                            if raw_response.status.state == 'completed':
                                agent_result = raw_response.artifacts[0]['parts'][0]['text']
                            else:
                                agent_result = raw_response.status.message['content']['text']

                            if agent_name == "OrderQueryAssistant":
                                chain = CustomerServicePrompts.summarize_order_prompt() | llm
                                final_response = chain.invoke(
                                    {"query": query_str, "raw_response": agent_result}).content.strip()
                            elif agent_name == "LogisticsQueryAssistant":
                                chain = CustomerServicePrompts.summarize_logistics_prompt() | llm
                                final_response = chain.invoke(
                                    {"query": query_str, "raw_response": agent_result}).content.strip()
                            else:
                                final_response = agent_result

                            responses.append(final_response)
                            routed_agents.append(agent_name)
                        else:
                            responses.append("暂不支持此业务。")

                    response = "\n\n".join(responses)
                    st.session_state.conversation_history += f"\nAssistant: {response}"

                with st.chat_message("assistant"):
                    st.markdown(response)
                st.session_state.messages.append({"role": "assistant", "content": response})
            except json.JSONDecodeError as json_err:
                error_message = f"意图识别解析失败：{str(json_err)}。请重试。"
                with st.chat_message("assistant"):
                    st.markdown(error_message)
                st.session_state.messages.append({"role": "assistant", "content": error_message})
            except Exception as e:
                error_message = f"处理失败：{str(e)}。请重试。"
                with st.chat_message("assistant"):
                    st.markdown(error_message)
                st.session_state.messages.append({"role": "assistant", "content": error_message})

with col2:
    st.subheader("🛠️ AgentCard")
    for agent_name in st.session_state.agent_network.agents.keys():
        agent_card = st.session_state.agent_network.get_agent_card(agent_name)
        agent_url = st.session_state.agent_urls.get(agent_name, "未知地址")
        with st.expander(f"Agent: {agent_name}", expanded=False):
            st.markdown(f"**技能**：{agent_card.skills}")
            st.markdown(f"**描述**：{agent_card.description}")
            st.markdown(f"**地址**：{agent_url}")
            st.markdown(f"**状态**：在线")

st.markdown("---")
st.markdown("Powered by 智能客服多Agent系统 v1.0 | MCP + A2A + Text-to-SQL")
