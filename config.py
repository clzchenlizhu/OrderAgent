import os
from dotenv import load_dotenv

# 项目根目录
project_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')

# 加载 .env 文件中的环境变量
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))


# 定义配置文件
class Config:
    def __init__(self):
        # 大模型配置
        self.base_url = os.getenv('DASHSCOPE_BASE_URL')
        self.api_key = os.getenv('DASHSCOPE_API_KEY')
        self.model_name = os.getenv('MODEL_NAME', 'qwen-plus')

        # 数据库配置
        self.host = os.getenv('DB_HOST', 'localhost')
        self.port = int(os.getenv('DB_PORT', 3306))
        self.user = os.getenv('DB_USER', 'root')
        self.password = os.getenv('DB_PASSWORD', '')
        self.database = os.getenv('DB_NAME', 'travel_rag')

        # Redis 配置
        self.redis_host = os.getenv('REDIS_HOST', 'localhost')
        self.redis_port = int(os.getenv('REDIS_PORT', 6379))
        self.redis_db = int(os.getenv('REDIS_DB', 0))

        # 日志配置
        self.log_file = 'logs/app2.log'


if __name__ == '__main__':
    cfg = Config()
    print(f"model: {cfg.model_name}")
    print(f"db: {cfg.host}:{cfg.port}/{cfg.database}")
    print(f"redis: {cfg.redis_host}:{cfg.redis_port}")
