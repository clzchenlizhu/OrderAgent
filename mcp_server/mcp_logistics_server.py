import mysql.connector
import json
import re
import hashlib
import redis
from datetime import date, datetime, timedelta
from decimal import Decimal
from mcp.server.fastmcp import FastMCP

from config import Config
from create_logger import logger
from utils.format import DateEncoder, default_encoder

conf = Config()

# 初始化Redis（可选，连不上就跳过缓存）
try:
    redis_client = redis.Redis(
        host=conf.redis_host,
        port=conf.redis_port,
        db=conf.redis_db,
        decode_responses=True,
        socket_connect_timeout=2
    )
    redis_client.ping()
    logger.info("Redis连接成功，缓存已启用")
except Exception as e:
    redis_client = None
    logger.warning(f"Redis连接失败({e})，缓存功能跳过")

CACHE_EXPIRE = 300  # 缓存5分钟


class SqlSecurityError(Exception):
    """SQL安全校验异常"""
    pass


def sql_security_check(sql: str):
    """SQL只读安全网关：只允许SELECT查询，拦截写操作和注入"""
    sql_clean = sql.strip().rstrip(';').strip()

    # 只允许SELECT开头
    if not re.match(r'^\s*SELECT\s+', sql_clean, re.IGNORECASE):
        raise SqlSecurityError("只允许SELECT查询语句")

    # 拦截危险关键词
    danger_keywords = [
        'INSERT', 'UPDATE', 'DELETE', 'DROP', 'ALTER', 'CREATE',
        'TRUNCATE', 'GRANT', 'REVOKE', 'EXEC', 'EXECUTE',
        'UNION', 'INTO OUTFILE', 'INTO DUMPFILE',
        'LOAD_FILE', 'BENCHMARK', 'SLEEP',
    ]
    for kw in danger_keywords:
        if re.search(r'\b' + re.escape(kw) + r'\b', sql_clean, re.IGNORECASE):
            raise SqlSecurityError(f"检测到危险操作: {kw}")

    # 拦截注释
    if '--' in sql_clean or '/*' in sql_clean or '#' in sql_clean:
        raise SqlSecurityError("不允许SQL注释")

    return True


class LogisticsService:
    def __init__(self):
        self.conn = mysql.connector.connect(
            host=conf.host,
            port=conf.port,
            user=conf.user,
            password=conf.password,
            database=conf.database
        )

    def _get_cache_key(self, sql: str) -> str:
        """生成缓存key"""
        sql_hash = hashlib.md5(sql.encode()).hexdigest()
        return f"logistics:query:{sql_hash}"

    def execute_query(self, sql: str) -> str:
        try:
            # 1. SQL安全校验
            sql_security_check(sql)
            logger.info(f"SQL安全校验通过: {sql}")

            # 2. 查缓存（Redis可用时）
            cache_key = self._get_cache_key(sql)
            if redis_client:
                cached = redis_client.get(cache_key)
                if cached:
                    logger.info(f"物流查询命中缓存: {sql}")
                    return cached

            # 3. 查数据库
            cursor = self.conn.cursor(dictionary=True)
            cursor.execute(sql)
            results = cursor.fetchall()
            cursor.close()
            for result in results:
                for key, value in result.items():
                    if isinstance(value, (date, datetime, timedelta, Decimal)):
                        result[key] = default_encoder(value)

            result_json = json.dumps(
                {"status": "success", "data": results} if results else {"status": "no_data", "message": "未找到物流数据，请确认订单号。"},
                cls=DateEncoder, ensure_ascii=False
            )

            # 4. 写入缓存（Redis可用时）
            if redis_client:
                redis_client.setex(cache_key, CACHE_EXPIRE, result_json)
                logger.info(f"物流查询写入缓存，过期时间{CACHE_EXPIRE}秒")

            return result_json

        except SqlSecurityError as e:
            logger.error(f"SQL安全拦截: {e}, SQL: {sql}")
            return json.dumps({"status": "error", "message": f"安全拦截: {e}"}, ensure_ascii=False)
        except Exception as e:
            logger.error(f'物流查询失败：{e}')
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def create_logistics_mcp_server():
    logistics_mcp = FastMCP(name="LogisticsTools",
                            instructions="物流查询工具，基于 logistics 表，只支持SELECT查询。",
                            log_level="ERROR",
                            host="127.0.0.1", port=8001)

    service = LogisticsService()

    @logistics_mcp.tool(
        name="query_logistics",
        description="查询物流数据，输入SQL，如 SELECT * FROM logistics WHERE order_id = 'ORD001'"
    )
    def query_logistics(sql: str) -> str:
        logger.info(f"执行物流查询: {sql}")
        return service.execute_query(sql)

    logger.info("=== 物流查询MCP服务器启动 ===")
    try:
        print("物流MCP已启动: http://127.0.0.1:8001/mcp")
        logistics_mcp.run(transport="streamable-http")
    except Exception as e:
        print(f"启动失败: {e}")


if __name__ == '__main__':
    create_logistics_mcp_server()
