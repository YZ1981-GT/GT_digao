"""后端服务启动脚本"""
import uvicorn
import os
import logging

if __name__ == "__main__":
    # 确保在正确的目录中运行
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    # 尽早加载 .env 文件，确保 MINERU_HOME 等变量在模块导入前生效
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_file):
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    key, value = key.strip(), value.strip()
                    if value and key not in os.environ:
                        os.environ[key] = value

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
