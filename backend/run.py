"""后端服务启动脚本"""
import uvicorn
import os
import logging
from dotenv import load_dotenv

if __name__ == "__main__":
    # 确保在正确的目录中运行
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    # 尽早加载 .env 文件，确保 MINERU_HOME 等变量在模块导入前生效
    # override=False: 不覆盖已存在的环境变量
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    load_dotenv(env_file, override=False)

    # 配置日志级别，确保应用日志可见
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=9980,
        reload=False,
        log_level="info",
        workers=1  # 纯异步应用使用单进程，避免多进程各自初始化知识库缓存浪费内存
    )
