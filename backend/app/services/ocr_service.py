"""智能 OCR 服务。

根据文档类型和内容自动选择最优 OCR 策略：
1. 图文层 PDF → 直接提取文本（pdfplumber/PyMuPDF），无需 OCR
2. 扫描版 PDF / 纯图片 → 优先 pytesseract 轻量 OCR，失败则兜底 MinerU
3. Word/Excel 中嵌入图片 → pytesseract 提取图片文字
4. 图片文件（jpg/png/tiff/bmp）→ pytesseract，复杂场景兜底 MinerU

MinerU 通过子进程调用其独立虚拟环境中的 CLI，不污染当前项目环境。
"""
import asyncio
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─── 可选依赖检测 ───
try:
    import pytesseract
    from PIL import Image
    HAS_TESSERACT = True
    # 自动检测 Tesseract 可执行文件路径（Windows 常见安装位置）
    _tesseract_candidates = [
        os.environ.get("TESSERACT_CMD", ""),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for _tc in _tesseract_candidates:
        if _tc and os.path.isfile(_tc):
            pytesseract.pytesseract.tesseract_cmd = _tc
            logger.info("Tesseract 路径: %s", _tc)
            break
    else:
        # 检查是否在 PATH 中
        if not shutil.which("tesseract"):
            logger.warning("Tesseract 未在 PATH 或常见位置找到，pytesseract OCR 可能不可用")
except ImportError:
    HAS_TESSERACT = False
    logger.info("pytesseract 未安装，轻量 OCR 不可用，将直接使用 MinerU 兜底")

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False


# MinerU 环境路径检测
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # GT_digao/
_MINERU_DIR = _PROJECT_ROOT / "MinerU"

def _find_mineru_cli() -> Tuple[Optional[Path], Optional[Path]]:
    """查找 MinerU CLI 路径，按优先级尝试多个位置。

    优先级：
    1. 环境变量 MINERU_HOME（用户可自定义）
    2. 项目内 GT_digao/MinerU/mineru_env
    3. 从项目内 pyvenv.cfg 解析原始 venv 路径
    4. 系统 PATH
    """
    candidates = []

    # 1. 环境变量 MINERU_HOME（最高优先级，便于不同机器配置）
    mineru_home = os.environ.get("MINERU_HOME")
    if mineru_home:
        mh = Path(mineru_home)
        candidates.append(
            (mh / "mineru_env" / "Scripts" / "mineru.exe",
             mh / "mineru_env" / "Scripts" / "python.exe"))
        candidates.append(
            (mh / "mineru_env" / "bin" / "mineru",
             mh / "mineru_env" / "bin" / "python"))
        # 也支持直接指向 venv 目录
        candidates.append(
            (mh / "Scripts" / "mineru.exe", mh / "Scripts" / "python.exe"))
        candidates.append(
            (mh / "bin" / "mineru", mh / "bin" / "python"))

    # 2. 项目内 MinerU venv
    candidates.append(
        (_MINERU_DIR / "mineru_env" / "Scripts" / "mineru.exe",
         _MINERU_DIR / "mineru_env" / "Scripts" / "python.exe"))
    candidates.append(
        (_MINERU_DIR / "mineru_env" / "bin" / "mineru",
         _MINERU_DIR / "mineru_env" / "bin" / "python"))

    # 3. 从 pyvenv.cfg 读取原始 venv 路径（可能在项目外）
    pyvenv_cfg = _MINERU_DIR / "mineru_env" / "pyvenv.cfg"
    if pyvenv_cfg.exists():
        try:
            for line in pyvenv_cfg.read_text(encoding="utf-8").splitlines():
                if line.startswith("command"):
                    parts = line.split()
                    for part in parts:
                        p = Path(part)
                        if "mineru_env" in str(p):
                            candidates.append(
                                (p / "Scripts" / "mineru.exe", p / "Scripts" / "python.exe"))
                            candidates.append(
                                (p / "bin" / "mineru", p / "bin" / "python"))
                            break
        except Exception:
            pass

    for cli_path, python_path in candidates:
        if cli_path.exists():
            return cli_path, python_path

    # 4. 检查系统 PATH 中是否有 mineru（需验证可用性）
    mineru_in_path = shutil.which("mineru")
    if mineru_in_path:
        return Path(mineru_in_path), None

    return None, None

_MINERU_CLI_PATH, _MINERU_PYTHON_PATH = _find_mineru_cli()
HAS_MINERU = _MINERU_CLI_PATH is not None
# MinerU 工作目录：CLI 所在 venv 的上级目录
_MINERU_CWD = _MINERU_CLI_PATH.parent.parent.parent if _MINERU_CLI_PATH else _MINERU_DIR
if HAS_MINERU:
    logger.info("MinerU 已检测到: %s (cwd: %s)", _MINERU_CLI_PATH, _MINERU_CWD)
else:
    logger.info("MinerU 未检测到，复杂 OCR 兜底不可用")


class OCRService:
    """智能 OCR 服务"""

    # 支持的图片格式
    IMAGE_FORMATS = {'.jpg', '.jpeg', '.png', '.tiff', '.tif', '.bmp', '.webp'}

    @staticmethod
    def is_image_file(ext: str) -> bool:
        """判断是否为图片文件"""
        return ext.lower() in OCRService.IMAGE_FORMATS

    @staticmethod
    async def detect_pdf_type(file_path: str) -> str:
        """检测 PDF 类型：text（图文层）、scanned（扫描版）、mixed（混合）

        策略：抽样前 5 页，统计每页文本字符数。
        - 所有页面文本 > 50 字符 → text
        - 所有页面文本 < 10 字符 → scanned
        - 其他 → mixed
        """
        if not HAS_PYMUPDF:
            return "unknown"

        def _detect(fp: str) -> str:
            try:
                doc = fitz.open(fp)
                total_pages = min(doc.page_count, 5)
                text_pages = 0
                empty_pages = 0

                for i in range(total_pages):
                    page = doc[i]
                    text = page.get_text().strip()
                    char_count = len(re.sub(r'\s+', '', text))
                    if char_count > 50:
                        text_pages += 1
                    elif char_count < 10:
                        empty_pages += 1

                doc.close()

                if text_pages == total_pages:
                    return "text"
                elif empty_pages == total_pages:
                    return "scanned"
                else:
                    return "mixed"
            except Exception as e:
                logger.warning("PDF 类型检测失败: %s", e)
                return "unknown"

        return await asyncio.to_thread(_detect, file_path)

    @staticmethod
    async def ocr_image_tesseract(image_path: str, lang: str = "chi_sim+eng") -> str:
        """使用 pytesseract 对单张图片做 OCR"""
        if not HAS_TESSERACT:
            return ""

        def _ocr(path: str) -> str:
            try:
                img = Image.open(path)
                text = pytesseract.image_to_string(img, lang=lang)
                return text.strip()
            except Exception as e:
                logger.warning("pytesseract OCR 失败 (%s): %s", path, e)
                return ""

        return await asyncio.to_thread(_ocr, image_path)

    @staticmethod
    async def ocr_image_bytes_tesseract(
        image_data: bytes, lang: str = "chi_sim+eng"
    ) -> str:
        """对内存中的图片字节做 pytesseract OCR"""
        if not HAS_TESSERACT:
            return ""

        def _ocr(data: bytes) -> str:
            try:
                import io
                img = Image.open(io.BytesIO(data))
                text = pytesseract.image_to_string(img, lang=lang)
                return text.strip()
            except Exception as e:
                logger.warning("pytesseract 图片字节 OCR 失败: %s", e)
                return ""

        return await asyncio.to_thread(_ocr, image_data)


    @staticmethod
    async def ocr_pdf_scanned_pages(
        file_path: str, lang: str = "chi_sim+eng"
    ) -> str:
        """对扫描版 PDF 的每一页渲染为图片后做 pytesseract OCR"""
        if not HAS_PYMUPDF or not HAS_TESSERACT:
            return ""

        def _ocr_pages(fp: str) -> str:
            import io
            texts = []
            try:
                doc = fitz.open(fp)
                for i in range(doc.page_count):
                    page = doc[i]
                    # 渲染页面为图片（300 DPI）
                    mat = fitz.Matrix(300 / 72, 300 / 72)
                    pix = page.get_pixmap(matrix=mat)
                    img_data = pix.tobytes("png")
                    pix = None

                    try:
                        img = Image.open(io.BytesIO(img_data))
                        text = pytesseract.image_to_string(img, lang=lang)
                        if text.strip():
                            texts.append(f"\n--- 第 {i + 1} 页 ---\n{text.strip()}")
                    except Exception as e:
                        logger.warning("OCR 第 %d 页失败: %s", i + 1, e)

                doc.close()
            except Exception as e:
                logger.error("扫描版 PDF OCR 失败: %s", e)
            return "\n".join(texts)

        return await asyncio.to_thread(_ocr_pages, file_path)

    @staticmethod
    async def ocr_pdf_image_pages(
        file_path: str, lang: str = "chi_sim+eng"
    ) -> str:
        """仅对含有嵌入图片的 PDF 页面做整页渲染 OCR。

        与 ocr_pdf_scanned_pages 不同，此方法只处理包含图片的页面，
        用于补充 MinerU/pdfplumber 无法识别的截图内容。
        整页渲染后 OCR 可以识别截图中的文字。
        """
        if not HAS_PYMUPDF or not HAS_TESSERACT:
            return ""

        def _find_image_pages(fp: str) -> List[int]:
            """找出包含有意义图片的页面"""
            pages_with_images = []
            try:
                doc = fitz.open(fp)
                for i in range(doc.page_count):
                    page = doc[i]
                    images = page.get_images(full=True)
                    for img_info in images:
                        try:
                            xref = img_info[0]
                            pix = fitz.Pixmap(doc, xref)
                            if pix.width >= 40 and pix.height >= 40:
                                pages_with_images.append(i)
                                pix = None
                                break
                            pix = None
                        except Exception:
                            continue
                doc.close()
            except Exception as e:
                logger.warning("检测图片页面失败: %s", e)
            return pages_with_images

        image_pages = await asyncio.to_thread(_find_image_pages, file_path)
        if not image_pages:
            return ""

        logger.info("发现 %d 个含图片页面，进行整页 OCR: %s",
                    len(image_pages), image_pages[:10])

        def _ocr_image_pages(fp: str, pages: List[int]) -> str:
            import io
            texts = []
            try:
                doc = fitz.open(fp)
                for i in pages:
                    page = doc[i]
                    mat = fitz.Matrix(300 / 72, 300 / 72)
                    pix = page.get_pixmap(matrix=mat)
                    img_data = pix.tobytes("png")
                    pix = None

                    try:
                        img = Image.open(io.BytesIO(img_data))
                        text = pytesseract.image_to_string(img, lang=lang)
                        if text.strip():
                            texts.append(
                                f"\n--- 第 {i + 1} 页 (图片OCR) ---\n{text.strip()}"
                            )
                    except Exception as e:
                        logger.warning("整页 OCR 第 %d 页失败: %s", i + 1, e)

                doc.close()
            except Exception as e:
                logger.error("图片页面 OCR 失败: %s", e)
            return "\n".join(texts)

        return await asyncio.to_thread(_ocr_image_pages, file_path, image_pages)

    @staticmethod
    async def ocr_with_mineru(
        file_path: str,
        backend: str = "pipeline",
        lang: str = "ch",
    ) -> str:
        """调用 MinerU CLI 做高精度 OCR（子进程，独立虚拟环境）

        Args:
            file_path: 输入文件路径（PDF 或图片）
            backend: pipeline / hybrid-auto-engine / vlm-auto-engine
            lang: 语言代码（ch / en）

        Returns:
            提取的 Markdown 文本内容
        """
        if not HAS_MINERU:
            logger.warning("MinerU 不可用，无法执行高精度 OCR")
            return ""

        # 创建临时输出目录
        output_dir = tempfile.mkdtemp(prefix="mineru_ocr_")

        try:
            cmd = [
                str(_MINERU_CLI_PATH),
                "-p", str(file_path),
                "-o", output_dir,
                "-b", backend,
                "-l", lang,
            ]

            logger.info("调用 MinerU: %s", " ".join(cmd))

            # 设置 MinerU 环境变量
            env = os.environ.copy()
            env["MINERU_DEVICE_MODE"] = env.get("MINERU_DEVICE_MODE", "cuda")
            env["MINERU_MODEL_SOURCE"] = env.get("MINERU_MODEL_SOURCE", "modelscope")

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=str(_MINERU_CWD),
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=600  # 10 分钟超时（大文件需要更多时间）
            )

            # MinerU 可能因 FontBBox 等非致命警告返回非零 exit code，
            # 不能仅靠 returncode 判断失败，需检查是否生成了 md 文件
            if proc.returncode != 0:
                err_msg = stderr.decode("utf-8", errors="ignore")
                logger.warning("MinerU 返回非零退出码 (code=%d)，检查是否仍有输出...", proc.returncode)
                logger.debug("MinerU stderr: %s", err_msg[:500])

            # 优先使用 content_list.json（包含页码信息），按页组织输出
            import json as _json
            content_list_files = list(Path(output_dir).rglob("*content_list*.json"))
            if content_list_files:
                try:
                    content_list_path = content_list_files[0]
                    content_list_dir = content_list_path.parent
                    with open(content_list_path, "r", encoding="utf-8") as f:
                        content_list = _json.load(f)

                    # 收集需要 OCR 的图片项
                    image_ocr_tasks = []
                    for idx, item in enumerate(content_list):
                        if item.get("type") == "image" and item.get("img_path"):
                            img_file = content_list_dir / item["img_path"]
                            if img_file.exists():
                                image_ocr_tasks.append((idx, str(img_file)))

                    # 批量对图片做 pytesseract OCR
                    if image_ocr_tasks and HAS_TESSERACT:
                        logger.info("MinerU 输出含 %d 张图片，进行 OCR 识别...", len(image_ocr_tasks))
                        for task_idx, (item_idx, img_path) in enumerate(image_ocr_tasks):
                            try:
                                ocr_text = await OCRService.ocr_image_tesseract(img_path)
                                if ocr_text and len(ocr_text.strip()) > 2:
                                    content_list[item_idx]["text"] = ocr_text.strip()
                                    content_list[item_idx]["_ocr_source"] = "pytesseract"
                            except Exception as e:
                                logger.debug("图片 OCR 失败 (%s): %s", img_path, e)

                    # 按 page_idx 分组
                    page_contents: dict = {}
                    for item in content_list:
                        page_idx = item.get("page_idx", 0)
                        page_num = page_idx + 1  # 转为 1-based
                        text = (item.get("text") or "").strip()
                        item_type = item.get("type", "text")

                        if not text:
                            continue

                        if page_num not in page_contents:
                            page_contents[page_num] = []

                        if item_type == "table":
                            page_contents[page_num].append(f"[表格]\n{text}\n[表格结束]")
                        elif item_type == "image":
                            page_contents[page_num].append(f"[图片内容: {text}]")
                        else:
                            page_contents[page_num].append(text)

                    if page_contents:
                        result_parts = []
                        for page_num in sorted(page_contents.keys()):
                            result_parts.append(f"\n--- 第 {page_num} 页 ---\n")
                            result_parts.append("\n".join(page_contents[page_num]))

                        result = "\n".join(result_parts).strip()
                        logger.info("MinerU content_list 解析成功: %d 页, %d 字符, %d 张图片已OCR",
                                    len(page_contents), len(result), len(image_ocr_tasks))
                        return result
                except Exception as e:
                    logger.warning("MinerU content_list.json 解析失败，回退到 md: %s", e)

            # 回退：读取 Markdown 文件（无页码信息）
            md_files = list(Path(output_dir).rglob("*.md"))
            if not md_files:
                logger.warning("MinerU 未生成任何输出")
                return ""

            texts = []
            for md_file in sorted(md_files):
                with open(md_file, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        texts.append(content)

            return "\n\n".join(texts)

        except asyncio.TimeoutError:
            logger.error("MinerU 执行超时（10分钟）")
            return ""
        except Exception as e:
            logger.error("MinerU 调用异常: %s", e)
            return ""
        finally:
            # 清理临时目录
            try:
                shutil.rmtree(output_dir, ignore_errors=True)
            except Exception:
                pass


    @staticmethod
    async def extract_images_ocr_from_word(file_path: str) -> str:
        """提取 Word 文档中嵌入图片的 OCR 文本"""
        if not HAS_TESSERACT:
            return ""

        from .file_service import FileService
        images = FileService.extract_images_from_docx(file_path)
        if not images:
            return ""

        texts = []
        for img_data, ext, img_index in images:
            text = await OCRService.ocr_image_bytes_tesseract(img_data)
            if text:
                texts.append(f"[Word嵌入图片{img_index} OCR内容]\n{text}")

        return "\n\n".join(texts)

    @staticmethod
    async def extract_images_ocr_from_excel(file_path: str) -> str:
        """提取 Excel 中嵌入图片的 OCR 文本（openpyxl 支持）"""
        if not HAS_TESSERACT:
            return ""

        def _extract(fp: str) -> List[Tuple[bytes, str]]:
            results = []
            try:
                import openpyxl
                wb = openpyxl.load_workbook(fp)
                for ws in wb.worksheets:
                    for img in getattr(ws, '_images', []):
                        try:
                            img_data = img._data()
                            results.append((img_data, ws.title))
                        except Exception:
                            pass
                wb.close()
            except Exception as e:
                logger.warning("Excel 图片提取失败: %s", e)
            return results

        images = await asyncio.to_thread(_extract, file_path)
        if not images:
            return ""

        texts = []
        for i, (img_data, sheet_name) in enumerate(images, 1):
            text = await OCRService.ocr_image_bytes_tesseract(img_data)
            if text:
                texts.append(f"[Excel工作表「{sheet_name}」图片{i} OCR内容]\n{text}")

        return "\n\n".join(texts)

    @staticmethod
    async def smart_parse(
        file_path: str,
        filename: str,
        ext: str,
        skip_embedded_image_ocr: bool = False,
    ) -> Tuple[str, str]:
        """智能解析入口：根据文件类型和内容自动选择最优策略。

        Args:
            file_path: 文件路径
            filename: 文件名
            ext: 文件扩展名
            skip_embedded_image_ocr: 若为 True，跳过 PDF 嵌入图片 OCR
                （当调用方已在文本提取阶段内联完成图片 OCR 时使用，避免重复）

        Returns:
            (content_text, ocr_method) — 提取的文本内容和使用的 OCR 方法描述
        """
        ext = ext.lower()

        # ─── 1. 纯图片文件 ───
        if OCRService.is_image_file(ext):
            logger.info("[OCR] 图片文件 %s，尝试 pytesseract", filename)
            text = await OCRService.ocr_image_tesseract(file_path)
            if text and len(text.strip()) > 20:
                return text, "pytesseract"

            # pytesseract 效果不佳，兜底 MinerU
            if HAS_MINERU:
                logger.info("[OCR] pytesseract 效果不佳，兜底 MinerU: %s", filename)
                text = await OCRService.ocr_with_mineru(file_path)
                if text:
                    return text, "MinerU"

            return text or "", "pytesseract(效果有限)"

        # ─── 2. PDF 文件 ───
        if ext == '.pdf':
            pdf_type = await OCRService.detect_pdf_type(file_path)
            logger.info("[OCR] PDF 类型检测: %s → %s", filename, pdf_type)

            if pdf_type == "text":
                # 图文层 PDF：文本层由常规解析器提取。
                # 如果调用方已在 pdfplumber/pymupdf 阶段内联了图片 OCR，
                # 则跳过重复的嵌入图片 OCR。
                if skip_embedded_image_ocr:
                    logger.info("[OCR] 图文层 PDF，调用方已内联图片 OCR，跳过: %s", filename)
                    return "", "direct_text(无需OCR)"

                img_ocr = await OCRService.ocr_pdf_embedded_images(file_path)
                if img_ocr and OCRService._is_ocr_quality_ok(img_ocr):
                    logger.info("[OCR] 图文层 PDF 中发现嵌入图片文字: %s", filename)
                    return img_ocr, "pytesseract(PDF嵌入图片)"

                # pytesseract 图片 OCR 失败或质量差，MinerU 兜底
                if HAS_MINERU:
                    has_images = await OCRService._pdf_has_images(file_path)
                    if has_images:
                        logger.info("[OCR] 图文层 PDF 图片 OCR 质量不佳，兜底 MinerU: %s", filename)
                        mineru_text = await OCRService.ocr_with_mineru(file_path)
                        if mineru_text:
                            return mineru_text, "MinerU(PDF嵌入图片)"

                return img_ocr or "", "direct_text(无需OCR)" if not img_ocr else "pytesseract(PDF嵌入图片,质量有限)"

            if pdf_type == "scanned":
                # 扫描版 PDF：先试 pytesseract
                if HAS_TESSERACT:
                    logger.info("[OCR] 扫描版 PDF，尝试 pytesseract: %s", filename)
                    text = await OCRService.ocr_pdf_scanned_pages(file_path)
                    if text and OCRService._is_ocr_quality_ok(text, min_len=50):
                        return text, "pytesseract"
                    elif text:
                        logger.info("[OCR] pytesseract 结果质量不佳 (len=%d), 尝试 MinerU 兜底", len(text.strip()))

                # pytesseract 不可用或效果差，兜底 MinerU
                if HAS_MINERU:
                    logger.info("[OCR] 兜底 MinerU 处理扫描版 PDF: %s", filename)
                    mineru_text = await OCRService.ocr_with_mineru(file_path)
                    if mineru_text:
                        return mineru_text, "MinerU"

                # MinerU 也失败了，返回 pytesseract 的结果（即使质量差也比没有好）
                if HAS_TESSERACT:
                    text = await OCRService.ocr_pdf_scanned_pages(file_path)
                    if text:
                        return text, "pytesseract(质量有限)"

                return "", "ocr_failed"

            if pdf_type == "mixed":
                # 混合 PDF：文本层直接读取 + 扫描页 OCR + 嵌入图片 OCR
                ocr_parts: List[str] = []
                method = "direct_text"

                # 1) 对文本稀少的页面做整页 OCR
                if HAS_TESSERACT and HAS_PYMUPDF:
                    empty_page_ocr = await OCRService._ocr_empty_pages(file_path)
                    if empty_page_ocr:
                        ocr_parts.append(empty_page_ocr)
                        method = "direct_text+pytesseract"

                # 2) 对所有页面的嵌入图片做 OCR（捕获图表等）
                #    如果调用方已内联完成，则跳过
                if not skip_embedded_image_ocr:
                    img_ocr = await OCRService.ocr_pdf_embedded_images(file_path)
                    if img_ocr and img_ocr.strip():
                        ocr_parts.append(img_ocr)
                        method = method.replace("direct_text", "direct_text+图片OCR") if "pytesseract" not in method else method + "+图片OCR"

                ocr_text = "\n".join(ocr_parts)

                # pytesseract 结果为空或质量差，MinerU 兜底
                if (not ocr_text or not OCRService._is_ocr_quality_ok(ocr_text)) and HAS_MINERU:
                    logger.info("[OCR] 混合 PDF pytesseract 效果不佳，兜底 MinerU: %s", filename)
                    mineru_text = await OCRService.ocr_with_mineru(file_path)
                    if mineru_text:
                        # MinerU 结果更好则替换，否则保留 pytesseract 结果
                        if not ocr_text or len(mineru_text.strip()) > len(ocr_text.strip()) * 1.5:
                            ocr_text = mineru_text
                            method = "MinerU"
                        else:
                            # 两者合并
                            ocr_text = ocr_text + "\n\n--- MinerU 补充 ---\n" + mineru_text
                            method = method + "+MinerU"

                return ocr_text, method

            # unknown 类型，尝试提取嵌入图片，失败则 MinerU 兜底
            if not skip_embedded_image_ocr:
                img_ocr = await OCRService.ocr_pdf_embedded_images(file_path)
                if img_ocr and OCRService._is_ocr_quality_ok(img_ocr):
                    return img_ocr, "pytesseract(PDF嵌入图片)"
            else:
                img_ocr = ""

            if HAS_MINERU:
                logger.info("[OCR] unknown PDF 兜底 MinerU: %s", filename)
                mineru_text = await OCRService.ocr_with_mineru(file_path)
                if mineru_text:
                    return mineru_text, "MinerU"

            return img_ocr or "", "direct_text" if not img_ocr else "pytesseract(质量有限)"

        # ─── 3. Word 文档中的嵌入图片 ───
        if ext in ('.docx', '.doc'):
            img_text = await OCRService.extract_images_ocr_from_word(file_path)
            if img_text:
                return img_text, "pytesseract(Word嵌入图片)"
            return "", "no_images"

        # ─── 4. Excel 中的嵌入图片 ───
        if ext in ('.xlsx', '.xls'):
            img_text = await OCRService.extract_images_ocr_from_excel(file_path)
            if img_text:
                return img_text, "pytesseract(Excel嵌入图片)"
            return "", "no_images"

        return "", "unsupported"

    @staticmethod
    async def _ocr_empty_pages(file_path: str, lang: str = "chi_sim+eng") -> str:
        """仅对 PDF 中文本稀少的页面做 OCR"""
        if not HAS_PYMUPDF or not HAS_TESSERACT:
            return ""

        def _process(fp: str) -> str:
            import io
            texts = []
            try:
                doc = fitz.open(fp)
                for i in range(doc.page_count):
                    page = doc[i]
                    text = page.get_text().strip()
                    char_count = len(re.sub(r'\s+', '', text))

                    if char_count < 20:
                        # 该页文本稀少，需要 OCR
                        mat = fitz.Matrix(300 / 72, 300 / 72)
                        pix = page.get_pixmap(matrix=mat)
                        img_data = pix.tobytes("png")
                        pix = None

                        try:
                            img = Image.open(io.BytesIO(img_data))
                            ocr_text = pytesseract.image_to_string(img, lang=lang)
                            if ocr_text.strip():
                                texts.append(
                                    f"\n--- 第 {i + 1} 页 (OCR) ---\n{ocr_text.strip()}"
                                )
                        except Exception as e:
                            logger.warning("OCR 第 %d 页失败: %s", i + 1, e)

                doc.close()
            except Exception as e:
                logger.error("混合 PDF OCR 失败: %s", e)
            return "\n".join(texts)

        return await asyncio.to_thread(_process, file_path)

    @staticmethod
    def _is_ocr_quality_ok(text: str, min_len: int = 20) -> bool:
        """判断 OCR 结果质量是否可接受。

        检查：
        - 文本长度是否达到最低要求
        - 乱码率（非中英文数字标点的字符占比）是否过高
        """
        if not text or len(text.strip()) < min_len:
            return False

        cleaned = text.strip()
        # 统计有效字符（中文、英文字母、数字、常见标点）
        valid_chars = len(re.findall(
            '[\\u4e00-\\u9fff\\u3000-\\u303fa-zA-Z0-9\\s'
            '，。、；：！？""''（）【】《》—…·.,;:!?()\\[\\]{}'
            '/\\\\+=@#$%^&*~`\\\'"<>|_-]',
            cleaned,
        ))
        total = len(cleaned)
        if total == 0:
            return False

        valid_ratio = valid_chars / total
        # 有效字符占比低于 60% 视为乱码过多
        if valid_ratio < 0.6:
            logger.debug("OCR 质量检查: 有效字符率 %.1f%% < 60%%，判定质量不佳", valid_ratio * 100)
            return False

        return True

    @staticmethod
    async def _pdf_has_images(file_path: str) -> bool:
        """快速检测 PDF 是否包含有意义的嵌入图片（非装饰性小图）"""
        if not HAS_PYMUPDF:
            return False

        def _check(fp: str) -> bool:
            try:
                doc = fitz.open(fp)
                pages_to_check = min(doc.page_count, 10)
                for i in range(pages_to_check):
                    page = doc[i]
                    images = page.get_images(full=True)
                    for img_info in images:
                        try:
                            xref = img_info[0]
                            pix = fitz.Pixmap(doc, xref)
                            # 只要有一张 >= 40x40 的图片就认为有图
                            if pix.width >= 40 and pix.height >= 40:
                                pix = None
                                doc.close()
                                return True
                            pix = None
                        except Exception:
                            continue
                doc.close()
            except Exception:
                pass
            return False

        return await asyncio.to_thread(_check, file_path)

    @staticmethod
    async def ocr_pdf_embedded_images(
        file_path: str, lang: str = "chi_sim+eng",
        min_image_size: int = 1500,
    ) -> str:
        """提取 PDF 中每页的嵌入图片并做 OCR。

        与 _ocr_empty_pages 不同，此方法专门处理 **有文本层** 的页面中
        嵌入的图片（图表、扫描插图等），确保图片中的文字不会丢失。

        Args:
            file_path: PDF 文件路径
            lang: OCR 语言
            min_image_size: 最小图片字节数，过小的图片（图标/装饰）跳过

        Returns:
            各页图片 OCR 文本拼接结果
        """
        if not HAS_PYMUPDF or not HAS_TESSERACT:
            return ""

        def _process(fp: str) -> str:
            import io
            texts: List[str] = []
            try:
                doc = fitz.open(fp)
                for page_idx in range(doc.page_count):
                    page = doc[page_idx]
                    image_list = page.get_images(full=True)
                    if not image_list:
                        continue

                    page_img_texts: List[str] = []
                    for img_idx, img_info in enumerate(image_list):
                        xref = img_info[0]
                        try:
                            pix = fitz.Pixmap(doc, xref)
                            # 跳过过小的图片（图标、装饰线等）
                            raw_bytes = pix.tobytes("png")
                            if len(raw_bytes) < min_image_size:
                                pix = None
                                continue
                            # 跳过尺寸过小的图片（宽或高 < 40px）
                            if pix.width < 40 or pix.height < 40:
                                pix = None
                                continue
                            # 转 RGB
                            if pix.n - pix.alpha >= 4:
                                pix = fitz.Pixmap(fitz.csRGB, pix)
                            img_data = pix.tobytes("png")
                            pix = None

                            img = Image.open(io.BytesIO(img_data))
                            ocr_text = pytesseract.image_to_string(img, lang=lang)
                            ocr_text = ocr_text.strip()
                            # 过滤掉 OCR 结果过短的（可能是纯图形/logo）
                            if ocr_text and len(ocr_text) > 3:
                                page_img_texts.append(ocr_text)
                        except Exception as e:
                            logger.debug(
                                "PDF 第 %d 页图片 %d OCR 失败: %s",
                                page_idx + 1, img_idx + 1, e,
                            )

                    if page_img_texts:
                        header = f"\n--- 第 {page_idx + 1} 页 嵌入图片内容 ---"
                        texts.append(header)
                        texts.extend(page_img_texts)

                doc.close()
            except Exception as e:
                logger.error("PDF 嵌入图片 OCR 失败: %s", e)
            return "\n".join(texts)

        return await asyncio.to_thread(_process, file_path)


# 单例
ocr_service = OCRService()
