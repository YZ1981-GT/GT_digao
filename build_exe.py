"""
致同AI审计助手 - EXE 打包脚本
==============================
使用 PyInstaller 将项目打包为独立可执行文件（.exe），
用户无需安装 Python 或 Node.js 即可运行。

打包流程：
  1. 构建前端（npm run build）并复制到 backend/static/
  2. 收集后端所有依赖和资源文件
  3. 使用 PyInstaller 打包为单目录 EXE

前置要求：
  - Python 3.12+ 已安装所有 backend/requirements.txt 依赖
  - Node.js 18+（用于构建前端）
  - pip install pyinstaller

用法：
  cd GT_digao
  python build_exe.py

  可选参数：
    --skip-frontend    跳过前端构建（已有 backend/static/ 时）
    --onefile          打包为单个 EXE 文件（启动较慢，但便于分发）
    --clean            清理旧的打包缓存后重新打包

产出：
  dist/致同AI审计助手/致同AI审计助手.exe   （默认单目录模式）
  或
  dist/致同AI审计助手.exe                  （--onefile 模式）
"""

import os
import sys
import shutil
import subprocess
import argparse
import json
from pathlib import Path

# ─── 配置 ───
APP_NAME = "致同AI审计助手"
APP_VERSION = "2.0.0"
ENTRY_SCRIPT = "launcher.py"  # PyInstaller 入口脚本（自动生成）
ICON_FILE = None  # 可选：.ico 图标文件路径

# 后端需要收集的数据目录
DATA_DIRS = [
    ("backend/static", "static"),           # 前端构建产物
    ("backend/data", "data"),               # 内置模板
    ("backend/app", "app"),                 # 后端应用代码
    ("TSJ", "TSJ"),                         # 预置提示词库
]

# 需要排除的模块（减小体积）
# 注意：torch/scipy/pandas/matplotlib 等是环境中安装的重型库，
# 但审计助手本身不直接依赖，排除后可从 ~1GB 降至 ~200MB
EXCLUDE_MODULES = [
    "tkinter", "_tkinter", "turtle",
    "unittest", "test",
    "xmlrpc", "pydoc",
    "lib2to3",
    "ensurepip",
    "venv",
    # 重型科学计算/ML 库（审计助手不需要）
    "torch", "torchvision", "torchaudio",
    "tensorflow", "tensorboard",
    "scipy", "pandas", "numpy",
    "matplotlib", "mpl_toolkits",
    "cv2", "opencv",
    "sklearn", "scikit_learn",
    "sympy",
    "pyarrow",
    "dask",
    "altair",
    "gradio",
    "transformers", "tokenizers", "huggingface_hub",
    "onnxruntime",
    "boto3", "botocore", "s3transfer",
    "hypothesis",
    "pytest", "py", "pluggy", "_pytest",
]


def check_prerequisites():
    """检查打包前置条件"""
    print("=" * 60)
    print(f"  {APP_NAME} - EXE 打包工具")
    print("=" * 60)
    print()

    # 检查是否在项目根目录
    if not Path("backend").exists() or not Path("frontend").exists():
        print("[错误] 请在项目根目录（GT_digao/）运行此脚本")
        sys.exit(1)

    # 检查 PyInstaller
    try:
        import PyInstaller
        print(f"[✓] PyInstaller {PyInstaller.__version__}")
    except ImportError:
        print("[错误] 未安装 PyInstaller，请运行: pip install pyinstaller")
        sys.exit(1)

    # 检查关键依赖
    missing = []
    for mod in ["fastapi", "uvicorn", "openai", "pydantic"]:
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        print(f"[错误] 缺少后端依赖: {', '.join(missing)}")
        print("  请先运行: pip install -r backend/requirements.txt")
        sys.exit(1)
    print("[✓] 后端核心依赖已安装")


def build_frontend(skip=False):
    """构建前端并复制到 backend/static/"""
    static_dir = Path("backend/static")

    if skip:
        if not (static_dir / "index.html").exists():
            print("[错误] --skip-frontend 但 backend/static/index.html 不存在")
            print("  请先手动构建前端: cd frontend && npm run build")
            sys.exit(1)
        print("[✓] 跳过前端构建，使用已有 backend/static/")
        return

    print("\n[1/4] 构建前端...")

    # 检查 Node.js
    try:
        result = subprocess.run(
            ["node", "--version"],
            capture_output=True, text=True, check=True
        )
        print(f"  Node.js {result.stdout.strip()}")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("[错误] 未安装 Node.js，请安装 Node.js 18+")
        sys.exit(1)

    # 检查前端依赖
    if not Path("frontend/node_modules").exists():
        print("  安装前端依赖...")
        subprocess.run(
            ["npm", "install"],
            cwd="frontend", check=True, shell=True
        )

    # 构建前端
    print("  执行 npm run build...")
    env = os.environ.copy()
    env["REACT_APP_API_URL"] = ""  # 生产模式使用相对路径
    subprocess.run(
        ["npm", "run", "build"],
        cwd="frontend", check=True, shell=True, env=env
    )

    # 复制构建产物到 backend/static/
    if static_dir.exists():
        shutil.rmtree(static_dir)
    shutil.copytree("frontend/build", str(static_dir))
    print(f"  [✓] 前端构建完成 → {static_dir}")


def create_launcher_script():
    """生成 PyInstaller 入口脚本"""
    print("\n[2/4] 生成启动器脚本...")

    launcher_code = r'''"""
致同AI审计助手 - PyInstaller 启动器
无控制台窗口，通过系统托盘图标管理服务。
"""
import os
import sys
import webbrowser
import threading
import time
import socket
import signal

APP_NAME = "致同AI审计助手"
APP_VERSION = "2.0.0"
_server = None  # uvicorn Server 实例
_port = 9980

def get_base_path():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

def is_port_available(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False

def find_available_port(start_port=9980, max_tries=20):
    for i in range(max_tries):
        port = start_port + i
        if is_port_available(port):
            return port
    return start_port

def open_browser_delayed(port, delay=3):
    def _open():
        time.sleep(delay)
        webbrowser.open(f"http://localhost:{port}")
    threading.Thread(target=_open, daemon=True).start()

def create_tray_icon(port):
    """创建系统托盘图标（带完整错误保护）"""
    try:
        import pystray
        from PIL import Image, ImageDraw
    except Exception:
        return  # 依赖缺失则静默跳过

    def _run_tray():
        try:
            # 生成紫色圆形图标（不依赖字体文件）
            size = 64
            img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.ellipse([2, 2, size-2, size-2], fill=(75, 45, 119, 255))
            # 画一个简单的白色对勾
            draw.line([(18, 34), (28, 44), (46, 22)], fill=(255, 255, 255, 255), width=4)

            def on_open(icon, item):
                try:
                    webbrowser.open(f"http://localhost:{port}")
                except Exception:
                    pass

            def on_quit(icon, item):
                try:
                    icon.stop()
                except Exception:
                    pass
                os._exit(0)

            menu = pystray.Menu(
                pystray.MenuItem(f"服务运行中 (端口 {port})", None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("打开浏览器", on_open, default=True),
                pystray.MenuItem("退出服务", on_quit),
            )

            icon = pystray.Icon(APP_NAME, img, f"{APP_NAME} - 运行中", menu)
            icon.run()
        except Exception:
            pass  # 托盘失败不影响主服务

    # pystray 在 Windows 上需要独立线程，daemon=False 保持进程存活
    tray_thread = threading.Thread(target=_run_tray, daemon=False)
    tray_thread.start()

def main():
    global _port

    # --noconsole 模式下 sys.stdout/stderr 为 None，
    # uvicorn logging 初始化会调用 sys.stderr.isatty() 导致崩溃，
    # 必须在任何 import 之前重定向到 devnull。
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w', encoding='utf-8')
    if sys.stderr is None:
        sys.stderr = open(os.devnull, 'w', encoding='utf-8')

    base_path = get_base_path()
    os.environ['APP_ENV'] = 'production'

    if base_path not in sys.path:
        sys.path.insert(0, base_path)

    # 加载 .env
    exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else base_path
    env_file = os.path.join(exe_dir, '.env')
    if os.path.exists(env_file):
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, value = line.partition('=')
                    key, value = key.strip(), value.strip()
                    if value and key not in os.environ:
                        os.environ[key] = value

    os.makedirs(os.path.join(exe_dir, 'uploads'), exist_ok=True)
    os.chdir(base_path)

    _port = find_available_port(9980)

    # 创建系统托盘图标
    create_tray_icon(_port)

    # 延迟打开浏览器
    open_browser_delayed(_port)

    # 启动 uvicorn
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=_port,
        reload=False,
        log_level="warning",
        workers=1,
    )

if __name__ == "__main__":
    main()
'''

    launcher_path = Path(ENTRY_SCRIPT)
    launcher_path.write_text(launcher_code.strip(), encoding="utf-8")
    print(f"  [✓] {launcher_path}")
    return str(launcher_path)


def collect_hidden_imports():
    """收集 PyInstaller 需要的隐式导入"""
    print("\n[3/4] 收集依赖信息...")

    hidden_imports = [
        # FastAPI 及其依赖
        "fastapi",
        "fastapi.middleware",
        "fastapi.middleware.cors",
        "fastapi.staticfiles",
        "fastapi.responses",
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "starlette",
        "starlette.routing",
        "starlette.middleware",
        "starlette.responses",
        "starlette.staticfiles",
        "anyio",
        "anyio._backends",
        "anyio._backends._asyncio",
        # Pydantic
        "pydantic",
        "pydantic_settings",
        "pydantic.deprecated",
        "pydantic.deprecated.decorator",
        # OpenAI
        "openai",
        "httpx",
        "httpcore",
        # 文档处理
        "docx",
        "docx.opc",
        "docx.opc.constants",
        "openpyxl",
        "xlrd",
        "PyPDF2",
        "pdfplumber",
        "fitz",  # pymupdf
        "docx2python",
        "PIL",
        "PIL.Image",
        # 网络
        "aiohttp",
        "aiofiles",
        "requests",
        "multipart",
        "python_multipart",
        # 其他
        "dotenv",
        "bs4",
        "git",  # gitpython
        "weasyprint",
        "asyncio_throttle",
        "json",
        "logging",
        "email.mime.text",
        # 系统托盘
        "pystray",
        "pystray._win32",
        # 应用模块 - 路由
        "app",
        "app.main",
        "app.config",
        "app.models",
        "app.models.schemas",
        "app.models.audit_schemas",
        "app.models.analysis_schemas",
        "app.routers",
        "app.routers.config",
        "app.routers.document",
        "app.routers.outline",
        "app.routers.content",
        "app.routers.search",
        "app.routers.expand",
        "app.routers.knowledge",
        "app.routers.review",
        "app.routers.generate",
        "app.routers.prompt",
        "app.routers.template",
        "app.routers.project",
        "app.routers.analysis",
        "app.routers.report_review",
        # 应用模块 - 服务
        "app.services",
        "app.services.openai_service",
        "app.services.review_engine",
        "app.services.report_generator",
        "app.services.document_generator",
        "app.services.workpaper_parser",
        "app.services.template_service",
        "app.services.project_service",
        "app.services.prompt_library",
        "app.services.prompt_git_service",
        "app.services.knowledge_service",
        "app.services.knowledge_retriever",
        "app.services.knowledge_vector_service",
        "app.services.word_service",
        "app.services.analysis_service",
        "app.services.report_review_engine",
        "app.services.report_parser",
        "app.services.report_body_reviewer",
        "app.services.report_template_service",
        "app.services.note_content_reviewer",
        "app.services.ocr_service",
        "app.services.search_service",
        "app.services.file_service",
        "app.services.reconciliation_engine",
        "app.services.account_mapping_template",
        "app.services.statement_preset",
        "app.services.table_structure_analyzer",
        "app.services.text_quality_analyzer",
        # 应用模块 - 工具
        "app.utils",
        "app.utils.config_manager",
        "app.utils.prompt_manager",
        "app.utils.outline_util",
        "app.utils.json_util",
        "app.utils.docx_to_md",
        "app.utils.sse",
    ]

    print(f"  [✓] 收集到 {len(hidden_imports)} 个隐式导入")
    return hidden_imports


def build_pyinstaller_command(launcher_path, hidden_imports, onefile=False):
    """构建 PyInstaller 命令"""
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--noconfirm",
        "--clean" if "--clean" in sys.argv else "",
        "--noconsole",  # 隐藏控制台窗口，通过系统托盘管理
    ]
    # 移除空字符串
    cmd = [c for c in cmd if c]

    if onefile:
        cmd.append("--onefile")
    else:
        cmd.append("--onedir")

    # 图标
    if ICON_FILE and Path(ICON_FILE).exists():
        cmd.extend(["--icon", ICON_FILE])
    # 检查前端 favicon
    elif Path("backend/static/favicon.ico").exists():
        cmd.extend(["--icon", "backend/static/favicon.ico"])

    # 添加数据目录
    for src, dst in DATA_DIRS:
        src_path = Path(src)
        if src_path.exists():
            # PyInstaller 使用 ; 分隔符（Windows）
            sep = ";" if sys.platform == "win32" else ":"
            cmd.extend(["--add-data", f"{src}{sep}{dst}"])

    # 添加隐式导入
    for mod in hidden_imports:
        cmd.extend(["--hidden-import", mod])

    # 排除不需要的模块
    for mod in EXCLUDE_MODULES:
        cmd.extend(["--exclude-module", mod])

    # 入口脚本
    cmd.append(launcher_path)

    return cmd


def run_pyinstaller(cmd):
    """执行 PyInstaller 打包"""
    print("\n[4/4] 执行 PyInstaller 打包...")
    print(f"  命令: {' '.join(cmd[:6])}... ({len(cmd)} 个参数)")
    print()

    result = subprocess.run(cmd, cwd=".")
    if result.returncode != 0:
        print("\n[错误] PyInstaller 打包失败")
        sys.exit(1)


def post_build(onefile=False):
    """打包后处理"""
    print("\n" + "=" * 60)
    print("  打包完成!")
    print("=" * 60)

    if onefile:
        exe_path = Path("dist") / f"{APP_NAME}.exe"
    else:
        exe_path = Path("dist") / APP_NAME / f"{APP_NAME}.exe"

    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print(f"  EXE 路径: {exe_path.resolve()}")
        print(f"  EXE 大小: {size_mb:.1f} MB")
    else:
        print(f"  [警告] 未找到 EXE: {exe_path}")

    if not onefile:
        dist_dir = Path("dist") / APP_NAME
        if dist_dir.exists():
            total = sum(f.stat().st_size for f in dist_dir.rglob("*") if f.is_file())
            print(f"  目录总大小: {total / (1024*1024):.1f} MB")

        # 创建 .env 示例文件
        env_example = dist_dir / ".env.example"
        env_example.write_text(
            "# MinerU 安装根目录（可选）\n"
            "# MINERU_HOME=E:\\MinerU\n",
            encoding="utf-8"
        )

        # 创建 uploads 目录
        (dist_dir / "uploads").mkdir(exist_ok=True)

    print()
    print("  使用方式:")
    if onefile:
        print(f"    双击 dist\\{APP_NAME}.exe 即可运行")
    else:
        print(f"    双击 dist\\{APP_NAME}\\{APP_NAME}.exe 即可运行")
        print(f"    或将 dist\\{APP_NAME} 文件夹压缩为 zip 分发")
    print()
    print("  注意事项:")
    print("    - 首次启动需要在界面中配置 AI 供应商和 API Key")
    print("    - 可在 EXE 同级目录放置 .env 文件配置环境变量")
    print("    - 用户数据保存在 C:\\Users\\<用户名>\\.gt_audit_helper\\")
    print("=" * 60)

    # 清理临时启动器脚本
    launcher = Path(ENTRY_SCRIPT)
    if launcher.exists():
        launcher.unlink()
        print(f"  [✓] 已清理临时文件 {ENTRY_SCRIPT}")


def main():
    parser = argparse.ArgumentParser(description=f"{APP_NAME} EXE 打包工具")
    parser.add_argument("--skip-frontend", action="store_true",
                        help="跳过前端构建（已有 backend/static/ 时使用）")
    parser.add_argument("--onefile", action="store_true",
                        help="打包为单个 EXE 文件（启动较慢但便于分发）")
    parser.add_argument("--clean", action="store_true",
                        help="清理旧的打包缓存后重新打包")
    args = parser.parse_args()

    check_prerequisites()
    build_frontend(skip=args.skip_frontend)
    launcher_path = create_launcher_script()
    hidden_imports = collect_hidden_imports()
    cmd = build_pyinstaller_command(launcher_path, hidden_imports, onefile=args.onefile)
    run_pyinstaller(cmd)
    post_build(onefile=args.onefile)


if __name__ == "__main__":
    main()
