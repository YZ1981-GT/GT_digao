"""后端服务启动脚本"""
import uvicorn
import os
import logging

if __name__ == "__main__":
    # 配置日志级别，确保应用日志可见
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')

    # 确保在正确的目录中运行
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=9980,
        reload=False,
        log_level="info",
        workers=1  # 纯异步应用使用单进程，避免多进程各自初始化知识库缓存浪费内存
    )
