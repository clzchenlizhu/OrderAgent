import mysql.connector
import json
from datetime import datetime
from mcp.server.fastmcp import FastMCP

from config import Config
from create_logger import logger

conf = Config()

ticket_mcp = FastMCP(name="TicketTools",
                     instructions="售后工单操作工具，支持创建工单和查询工单进度。",
                     log_level="ERROR",
                     host="127.0.0.1", port=8003)


@ticket_mcp.tool(
    name="create_ticket",
    description="创建售后工单，需要订单号、工单类型和问题描述"
)
def create_ticket(order_id: str, ticket_type: str, description: str) -> str:
    '''
    Args:
        order_id (str): 订单号，如 'ORD001'
        ticket_type (str): 工单类型，如 '退款'/'退货'/'换货'/'投诉'/'发票'
        description (str): 问题描述，如 '商品有瑕疵要求退款'
    '''
    logger.info(f"创建工单: order={order_id}, type={ticket_type}, desc={description}")
    try:
        conn = mysql.connector.connect(
            host=conf.host, port=conf.port,
            user=conf.user, password=conf.password, database=conf.database
        )
        cursor = conn.cursor()
        sql = "INSERT INTO tickets (order_id, type, description, status, create_time) VALUES (%s, %s, %s, %s, %s)"
        cursor.execute(sql, (order_id, ticket_type, description, "待处理", datetime.now()))
        conn.commit()
        ticket_id = cursor.lastrowid
        cursor.close()
        conn.close()
        logger.info(f"工单创建成功，工单号: {ticket_id}")
        return f"工单创建成功！工单号: {ticket_id}，订单: {order_id}，类型: {ticket_type}，状态: 待处理，我们会尽快处理。"
    except Exception as e:
        logger.error(f"创建工单失败: {e}")
        return f"创建工单失败: {str(e)}"


@ticket_mcp.tool(
    name="query_ticket",
    description="根据工单号或订单号查询工单进度"
)
def query_ticket(ticket_id: int = None, order_id: str = None) -> str:
    '''
    Args:
        ticket_id (int): 工单号，如 1
        order_id (str): 订单号，如 'ORD001'
    '''
    logger.info(f"查询工单: ticket_id={ticket_id}, order_id={order_id}")
    try:
        conn = mysql.connector.connect(
            host=conf.host, port=conf.port,
            user=conf.user, password=conf.password, database=conf.database
        )
        cursor = conn.cursor(dictionary=True)
        if ticket_id:
            cursor.execute("SELECT * FROM tickets WHERE ticket_id = %s", (ticket_id,))
        elif order_id:
            cursor.execute("SELECT * FROM tickets WHERE order_id = %s", (order_id,))
        else:
            return "请提供工单号或订单号。"
        results = cursor.fetchall()
        cursor.close()
        conn.close()
        if not results:
            return "未找到相关工单记录。"
        output = []
        for r in results:
            output.append(f"工单号: {r['ticket_id']}，订单: {r['order_id']}，类型: {r['type']}，描述: {r['description']}，状态: {r['status']}，创建时间: {r['create_time']}")
        return "\n".join(output)
    except Exception as e:
        logger.error(f"查询工单失败: {e}")
        return f"查询失败: {str(e)}"


def create_ticket_mcp_server():
    logger.info("=== 工单操作MCP服务器启动 ===")
    try:
        print("工单MCP已启动: http://127.0.0.1:8003/mcp")
        ticket_mcp.run(transport="streamable-http")
    except Exception as e:
        print(f"启动失败: {e}")


if __name__ == '__main__':
    create_ticket_mcp_server()
