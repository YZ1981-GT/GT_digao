"""FastAPI应用主入口"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

from .config import settings
from .routers import config, document, outline, content, search, expand, knowledge
from .routers import review, generate, prompt, template, project, analysis
from .routers import report_review

# 创建FastAPI应用实例
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="基于FastAPI的审计底稿智能复核与文档生成后端API"
)

# 添加CORS中间件（根据环境使用不同配置）
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_allow_origin_regex or None,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=settings.cors_allow_headers,
)

# 注册路由（必须在静态文件路由之前）
app.include_router(config.router)
app.include_router(document.router)
app.include_router(outline.router)
app.include_router(content.router)
app.include_router(search.router)
app.include_router(expand.router)
app.include_router(knowledge.router)
app.include_router(review.router)
app.include_router(generate.router)
app.include_router(prompt.router)
app.include_router(template.router)
app.include_router(project.router)
app.include_router(analysis.router)
app.include_router(report_review.router)

# 健康检查端点
@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "app_name": settings.app_name,
        "version": settings.app_version
    }

# 静态文件服务（用于服务前端构建文件）
# 注意：这些路由必须在API路由之后注册，以避免冲突
static_dir = "backend/static" if os.path.exists("backend/static") else "static"
if os.path.exists(static_dir):
    # 挂载静态资源文件夹
    app.mount("/static", StaticFiles(directory=f"{static_dir}/static"), name="static")
    
    # 处理React应用的根路径
    @app.get("/", include_in_schema=False)
    async def read_index():
        """根路径，返回前端首页"""
        return FileResponse(f"{static_dir}/index.html")
    
    # 处理前端资源文件（不使用通配符，避免与API冲突）
    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return FileResponse(f"{static_dir}/favicon.ico")
    
    @app.get("/manifest.json", include_in_schema=False)
    async def manifest():
        return FileResponse(f"{static_dir}/manifest.json")
    
    @app.get("/robots.txt", include_in_schema=False)
    async def robots():
        return FileResponse(f"{static_dir}/robots.txt")
    
    # 处理前端图片资源
    @app.get("/{filename:path}.{ext:(png|jpg|jpeg|gif|svg|ico)}", include_in_schema=False)
    async def serve_images(filename: str, ext: str):
        file_path = f"{static_dir}/{filename}.{ext}"
        if os.path.exists(file_path):
            return FileResponse(file_path)
        return FileResponse(f"{static_dir}/index.html")
    
    # 处理前端路由（仅限非API路径）
    # 注意：不使用通配符，而是明确列出前端路由
    frontend_routes = ["/document-analysis", "/outline-edit", "/content-edit"]
    for _route in frontend_routes:
        @app.get(_route, include_in_schema=False)
        async def serve_frontend_route(_r: str = _route):
            return FileResponse(f"{static_dir}/index.html")
else:
    # 如果没有静态文件，返回API信息
    @app.get("/")
    async def read_root():
        """根路径，返回API信息"""
        return {
            "message": f"欢迎使用 {settings.app_name} API",
            "version": settings.app_version,
            "docs": "/docs",
            "health": "/health"
        }