"""应用配置管理"""
try:
    from pydantic_settings import BaseSettings
except ImportError:
    from pydantic import BaseSettings
import os


class Settings(BaseSettings):
    """应用设置"""
    app_name: str = "致同AI审计助手"
    app_version: str = "2.0.0"
    debug: bool = False
    
    # 环境标识：development / production
    environment: str = os.environ.get("APP_ENV", "development")
    
    # CORS设置 - 允许前端端口
    cors_origins: list = [
        "http://localhost:3030",
        "http://127.0.0.1:3030",
        "http://localhost:9980",
        "http://127.0.0.1:9980",
    ]
    
    @property
    def cors_allow_origin_regex(self) -> str:
        """根据环境返回不同的CORS正则"""
        if self.environment == "production":
            # 生产环境：仅允许同源请求（不使用正则通配）
            return ""
        # 开发环境：允许本地 3030/9980 端口
        return r"https?://(localhost|127\.0\.0\.1)(:(3030|9980))?"
    
    @property
    def cors_allow_headers(self) -> list:
        """根据环境返回不同的允许头"""
        if self.environment == "production":
            return ["Content-Type", "Authorization", "Accept"]
        return ["*"]
    
    # 文件上传设置
    max_file_size: int = 10 * 1024 * 1024  # 10MB
    allowed_extensions: list = ["pdf", "docx", "doc"]
    upload_dir: str = "uploads"
    
    # OpenAI默认设置
    default_model: str = "abab6.5s-chat"
    
    class Config:
        env_file = ".env"
        extra = "ignore"


# 全局设置实例
settings = Settings()

# 确保上传目录存在
os.makedirs(settings.upload_dir, exist_ok=True)