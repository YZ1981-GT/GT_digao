"""
绿色便携包打包脚本
==================
将项目打包为免安装的绿色便携包，核心业务文件编译为 .pyc 字节码保护。

用法：
  python pack_portable.py

产出：
  dist/致同AI审计助手/   （可直接压缩为 zip 发给客户）

要求：
  - 当前 Python 环境已安装所有 backend/requirements.txt 依赖
  - frontend 已构建到 backend/static/（运行 npm run build 后 copy）
"""
import os
import sys
import shutil
import compileall
import py_compile
import subprocess
from pathlib import Path

# ─── 配置 ───
DIST_NAME = "致同AI审计助手"
DIST_DIR = Path("dist") / DIST_NAME

# 需要编译保护的核心文件（相对于 backend/app/）
PROTECTED_FILES = [
    "utils/prompt_manager.py",
    "services/openai_service.py",
    "services/knowledge_service.py",
    "services/search_service.py",
    "services/word_service.py",
    "utils/outline_util.py",
    "utils/config_manager.py",
]

# 不需要复制的文件/文件夹
EXCLUDE_PATTERNS = [
    "__pycache__",
    ".pyc",
    ".git",
    ".venv",
    ".vscode",
    ".env",
    "node_modules",
    "frontend",          # 前端源码不需要，只要 backend/static
    "screenshots",
    "CLAUDE.md",
    "TSC.txt",
    ".gitignore",
    "build",             # 打包工具目录
    "pack_portable.py",
    "backend/mcp",       # MCP 服务端不需要
    "backend/downloaded_files",
    "backend/uploads",
    "backend/.env.example",
    "uploads",
    "LICENSE",
    "README.md",
]


def should_exclude(path: str) -> bool:
    """判断路径是否应该排除"""
    parts = Path(path).parts
    for pattern in EXCLUDE_PATTERNS:
        if pattern in parts or path.endswith(pattern):
            return True
    return False


def clean_dist():
    """清理旧的输出目录"""
    if DIST_DIR.exists():
        print(f"清理旧目录: {DIST_DIR}")
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir(parents=True, exist_ok=True)


def copy_backend():
    """复制后端文件"""
    print("\n[1/5] 复制后端文件...")
    src = Path("backend")
    dst = DIST_DIR / "backend"

    for item in src.rglob("*"):
        rel = item.relative_to(src)
        rel_str = str(rel)

        # 排除不需要的
        if should_exclude(rel_str):
            continue
        # 排除 __pycache__
        if "__pycache__" in rel_str:
            continue

        dst_path = dst / rel
        if item.is_dir():
            dst_path.mkdir(parents=True, exist_ok=True)
        else:
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dst_path)

    # 确保 uploads 目录存在
    (dst / "uploads").mkdir(exist_ok=True)

    print(f"  后端文件已复制到 {dst}")


def check_static():
    """检查前端构建文件是否存在"""
    static_dir = DIST_DIR / "backend" / "static"
    index_html = static_dir / "index.html"
    if not index_html.exists():
        print("  ⚠ 前端构建文件不存在！请先运行:")
        print("    cd frontend && npm run build")
        print("    Copy-Item -Path frontend\\build\\* -Destination backend\\static\\ -Recurse -Force")
        sys.exit(1)
    print("  ✓ 前端构建文件已就绪")


def compile_protected_files():
    """将核心文件编译为 .pyc 并删除 .py 源码"""
    print("\n[2/5] 编译保护核心文件...")
    app_dir = DIST_DIR / "backend" / "app"
    import importlib

    compiled = 0
    for rel_path in PROTECTED_FILES:
        py_file = app_dir / rel_path
        if not py_file.exists():
            print(f"  ⚠ 文件不存在，跳过: {rel_path}")
            continue

        try:
            # 编译为 .pyc，使用 UNCHECKED_HASH 模式
            # 这样 Python 不会检查 .py 源文件是否与 .pyc 匹配
            cache_dir = py_file.parent / "__pycache__"
            cache_dir.mkdir(exist_ok=True)

            stem = py_file.stem
            tag = sys.implementation.cache_tag  # 如 cpython-312
            cache_pyc = cache_dir / f"{stem}.{tag}.pyc"

            py_compile.compile(
                str(py_file),
                cfile=str(cache_pyc),
                doraise=True,
                invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
            )

            # 将 .py 替换为空壳（保留文件让 import 机制能找到模块，但隐藏源码）
            py_file.write_text("# compiled\n", encoding="utf-8")

            compiled += 1
            print(f"  ✓ {rel_path} → .pyc (源码已替换为空壳)")

        except py_compile.PyCompileError as e:
            print(f"  ✗ 编译失败 {rel_path}: {e}")

    print(f"  共编译 {compiled}/{len(PROTECTED_FILES)} 个核心文件")


def create_launcher():
    """创建启动脚本"""
    print("\n[3/5] 创建启动脚本...")

    # start.bat - 双击启动
    bat_content = r"""@echo off
chcp 65001 >nul
title 致同AI审计底稿复核与文档生成
color 0B

echo ================================================
echo   致同AI审计底稿复核与文档生成
echo ================================================
echo.

:: 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10 或更高版本
    echo 下载地址: https://www.python.org/downloads/
    echo 安装时请勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

:: 检查依赖是否已安装
echo [1/3] 检查依赖...
python -c "import fastapi, uvicorn, openai" >nul 2>&1
if %errorlevel% neq 0 (
    echo [1/3] 首次运行，正在安装依赖（约2-5分钟）...
    pip install -r backend\requirements.txt -q
    if %errorlevel% neq 0 (
        echo [错误] 依赖安装失败，请检查网络连接
        pause
        exit /b 1
    )
    echo [1/3] 依赖安装完成
) else (
    echo [1/3] 依赖已就绪
)

:: 清理端口
echo [2/3] 清理端口占用...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8080" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
)

:: 启动服务
echo [3/3] 启动服务...
echo.
echo ================================================
echo   服务地址: http://localhost:8080
echo   关闭此窗口即可停止服务
echo ================================================
echo.

:: 延迟打开浏览器
start "" cmd /c "timeout /t 4 /nobreak >nul && start http://localhost:8080"

cd backend
python run.py

echo.
echo 服务已关闭
pause
"""
    bat_path = DIST_DIR / "启动.bat"
    bat_path.write_text(bat_content.strip(), encoding="utf-8")
    print(f"  ✓ {bat_path.name}")

    # 使用说明
    readme_content = """致同AI审计底稿复核与文档生成 - 使用说明
====================================

【系统要求】
- Windows 10/11 (64位)
- Python 3.10 或更高版本（首次需安装）
- 至少 4GB 内存

【Python 安装】
如果电脑上没有 Python，请按以下步骤安装：
1. 访问 https://www.python.org/downloads/
2. 下载最新版 Python（推荐 3.12）
3. 安装时务必勾选 "Add Python to PATH"（非常重要）
4. 安装完成后重启电脑

【启动方式】
双击「启动.bat」即可。
首次启动会自动安装依赖（约2-5分钟），之后启动只需几秒。

【首次配置】
1. 启动后浏览器会自动打开 http://localhost:8080
2. 在左侧配置面板中：
   - 选择 AI 供应商（推荐 SiliconFlow 硅基流动）
   - 填入 API Key
   - 选择模型（推荐 deepseek-ai/DeepSeek-V3.2）
3. 点击「保存配置」

【使用流程】
第一步：选择工作模式（底稿复核 或 文档生成）
第二步：按工作流步骤完成操作
第三步：查看复核报告或导出生成文档

【关闭服务】
直接关闭命令行窗口即可。

【数据存储】
- 用户配置保存在: C:\\Users\\你的用户名\\.gt_audit_helper\\
- 知识库文件保存在同一目录下
- 编辑中的内容自动保存在浏览器本地存储中
"""
    readme_path = DIST_DIR / "使用说明.txt"
    readme_path.write_text(readme_content.strip(), encoding="utf-8")
    print(f"  ✓ {readme_path.name}")


def cleanup_dist():
    """清理打包目录中的多余文件"""
    print("\n[4/5] 清理多余文件...")
    backend_dir = DIST_DIR / "backend"

    # 删除不需要的顶级目录/文件
    remove_paths = [
        "backend/.env.example",
        "backend/mcp",
        "backend/downloaded_files",
    ]
    for f in remove_paths:
        p = DIST_DIR / f
        if p.exists():
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
            print(f"  ✓ 删除 {f}")

    # ─── 清理非保护文件的 __pycache__（纯缓存，运行时会自动重建） ───
    protected_stems = {Path(f).stem for f in PROTECTED_FILES}
    removed_cache = 0
    for cache_dir in list(backend_dir.rglob("__pycache__")):
        for f in list(cache_dir.iterdir()):
            stem = f.stem.split(".")[0]  # e.g. 'config' from 'config.cpython-312'
            if stem not in protected_stems:
                f.unlink()
                removed_cache += 1
        # 如果 __pycache__ 目录空了就删掉
        if cache_dir.exists() and not any(cache_dir.iterdir()):
            cache_dir.rmdir()
    if removed_cache:
        print(f"  ✓ 删除 {removed_cache} 个非核心 .pyc 缓存文件")

    # ─── 清理多余的静态图片 ───
    # index.html 引用: favicon.ico, logo192.png
    # manifest.json 引用: favicon.ico, logo192.png, logo512.png
    # JS 代码引用: gt-logo.png
    # 其余图片均为旧版/未使用
    keep_images = {"favicon.ico", "logo192.png", "logo512.png", "gt-logo.png",
                   "index.html", "asset-manifest.json", "manifest.json", "robots.txt"}
    static_root = backend_dir / "static"
    removed_img = 0
    for f in list(static_root.iterdir()):
        if f.is_file() and f.name not in keep_images:
            size_kb = f.stat().st_size / 1024
            print(f"  ✓ 删除多余图片 {f.name} ({size_kb:.0f} KB)")
            f.unlink()
            removed_img += 1

    # ─── 清理 static/static/ 中的旧版本 JS/CSS ───
    static_js = backend_dir / "static" / "static" / "js"
    static_css = backend_dir / "static" / "static" / "css"

    manifest_path = backend_dir / "static" / "asset-manifest.json"
    if manifest_path.exists():
        import json
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        referenced = set()
        for v in manifest.get("files", {}).values():
            if isinstance(v, str):
                referenced.add(Path(v).name)
        # 去掉 .map 文件引用（不需要 source map）
        referenced = {n for n in referenced if not n.endswith(".map")}

        for folder in [static_js, static_css]:
            if not folder.exists():
                continue
            removed = 0
            for f in list(folder.iterdir()):
                if f.name not in referenced:
                    f.unlink()
                    removed += 1
            if removed:
                print(f"  ✓ {folder.name}/ 删除 {removed} 个旧文件，保留 {len(list(folder.iterdir()))} 个")

    # ─── 清理 requirements.txt 中不需要的依赖 ───
    req_path = backend_dir / "requirements.txt"
    if req_path.exists():
        lines = req_path.read_text(encoding="utf-8").splitlines()
        remove_deps = ["duckduckgo-search", "mcp=="]
        cleaned = [l for l in lines if not any(d in l for d in remove_deps)]
        removed_count = len(lines) - len(cleaned)
        if removed_count:
            req_path.write_text("\n".join(cleaned) + "\n", encoding="utf-8")
            print(f"  ✓ requirements.txt 移除 {removed_count} 个无用依赖")

    print("  ✓ 清理完成")


def show_summary():
    """显示打包结果"""
    print("\n[5/5] 打包完成！")
    print("=" * 50)

    # 计算目录大小
    total_size = 0
    file_count = 0
    for f in DIST_DIR.rglob("*"):
        if f.is_file():
            total_size += f.stat().st_size
            file_count += 1

    size_mb = total_size / (1024 * 1024)
    print(f"  输出目录: {DIST_DIR.resolve()}")
    print(f"  文件数量: {file_count}")
    print(f"  总大小:   {size_mb:.1f} MB")
    print()
    print("  下一步:")
    print(f"  1. 将 dist\\{DIST_NAME} 文件夹压缩为 zip")
    print(f"  2. 发送给客户，解压后双击「启动.bat」即可使用")
    print(f"  3. 客户需要自行安装 Python 3.10+（首次）")
    print("=" * 50)


def main():
    print("=" * 50)
    print("致同AI审计助手 - 绿色便携包打包")
    print("=" * 50)

    # 确保在项目根目录
    if not Path("backend").exists():
        print("请在项目根目录运行此脚本")
        sys.exit(1)

    # 检查 backend/static 是否存在
    if not Path("backend/static/index.html").exists():
        print("前端构建文件不存在，请先运行:")
        print("  cd frontend && npm run build")
        print("  Copy-Item -Path frontend\\build\\* -Destination backend\\static\\ -Recurse -Force")
        sys.exit(1)

    clean_dist()
    copy_backend()
    check_static()
    compile_protected_files()
    create_launcher()
    cleanup_dist()
    show_summary()


if __name__ == "__main__":
    main()
