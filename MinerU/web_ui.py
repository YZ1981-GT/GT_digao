# -*- coding: utf-8 -*-
"""
MinerU Web 界面
基于 Gradio 的简单 PDF 解析界面，直接调用 Python API
"""

import os
import sys

# 设置环境变量（需在导入 mineru 之前）
os.environ.setdefault('MINERU_DEVICE_MODE', 'cuda')
os.environ.setdefault('MINERU_MODEL_SOURCE', 'modelscope')

import gradio as gr
from pathlib import Path

from mineru.cli.common import do_parse, read_fn
from mineru.utils.config_reader import get_device
from mineru.utils.model_utils import get_vram

# 项目根目录和输出目录
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = str(BASE_DIR / "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 初始化 GPU 显存限制
if os.getenv('MINERU_VIRTUAL_VRAM_SIZE') is None:
    os.environ['MINERU_VIRTUAL_VRAM_SIZE'] = str(get_vram(os.environ['MINERU_DEVICE_MODE']))


def parse_pdf(pdf_file, backend, language, enable_formula, enable_table):
    """解析 PDF 文件"""
    if pdf_file is None:
        return "请上传 PDF 文件", None, None

    try:
        # 获取 PDF 文件路径
        pdf_path = pdf_file if isinstance(pdf_file, str) else pdf_file.name
        file_name = Path(pdf_path).stem
        pdf_bytes = read_fn(Path(pdf_path))

        # 直接调用 MinerU Python API
        do_parse(
            output_dir=OUTPUT_DIR,
            pdf_file_names=[file_name],
            pdf_bytes_list=[pdf_bytes],
            p_lang_list=[language],
            backend=backend,
            parse_method='auto',
            formula_enable=enable_formula,
            table_enable=enable_table,
            f_draw_layout_bbox=False,
            f_draw_span_bbox=False,
            f_dump_md=True,
            f_dump_middle_json=False,
            f_dump_model_output=False,
            f_dump_orig_pdf=False,
            f_dump_content_list=False,
        )

        # 查找生成的 Markdown 文件
        md_files = list(Path(OUTPUT_DIR).rglob(f"{file_name}*.md"))

        if md_files:
            md_file = md_files[0]
            with open(md_file, 'r', encoding='utf-8') as f:
                markdown_content = f.read()

            # 查找图片
            images_dir = md_file.parent / "images"
            image_files = []
            if images_dir.exists():
                image_files = [str(f) for f in images_dir.glob("*")
                               if f.suffix.lower() in ['.png', '.jpg', '.jpeg']]

            status = (f"✓ 解析成功！\n\n"
                      f"文件: {Path(pdf_path).name}\n"
                      f"输出目录: {OUTPUT_DIR}\n"
                      f"提取图片: {len(image_files)} 张")

            return status, markdown_content, image_files if image_files else None
        else:
            return "✗ 解析完成但未找到输出文件", None, None

    except Exception as e:
        return f"✗ 发生错误: {str(e)}", None, None


def parse_local_path(local_path, backend, language, enable_formula, enable_table):
    """通过本地路径解析 PDF 文件或整个文件夹"""
    if not local_path or not local_path.strip():
        return "请输入本地文件或文件夹路径", None, None

    local_path = local_path.strip().strip('"').strip("'")
    p = Path(local_path)

    if not p.exists():
        return f"✗ 路径不存在: {local_path}", None, None

    try:
        # 收集要解析的文件
        pdf_suffixes = {'.pdf', '.png', '.jpg', '.jpeg'}
        if p.is_file():
            if p.suffix.lower() not in pdf_suffixes:
                return f"✗ 不支持的文件格式: {p.suffix}", None, None
            files = [p]
        else:
            files = [f for f in p.glob('*') if f.suffix.lower() in pdf_suffixes]
            if not files:
                return f"✗ 文件夹中没有找到 PDF/图片文件: {local_path}", None, None

        file_names = [f.stem for f in files]
        pdf_bytes_list = [read_fn(f) for f in files]
        lang_list = [language] * len(files)

        do_parse(
            output_dir=OUTPUT_DIR,
            pdf_file_names=file_names,
            pdf_bytes_list=pdf_bytes_list,
            p_lang_list=lang_list,
            backend=backend,
            parse_method='auto',
            formula_enable=enable_formula,
            table_enable=enable_table,
            f_draw_layout_bbox=False,
            f_draw_span_bbox=False,
            f_dump_md=True,
            f_dump_middle_json=False,
            f_dump_model_output=False,
            f_dump_orig_pdf=False,
            f_dump_content_list=False,
        )

        # 收集所有生成的 Markdown
        all_md = []
        total_images = 0
        for name in file_names:
            md_files = list(Path(OUTPUT_DIR).rglob(f"{name}*.md"))
            if md_files:
                with open(md_files[0], 'r', encoding='utf-8') as f:
                    all_md.append(f"## {name}\n\n{f.read()}")
                img_dir = md_files[0].parent / "images"
                if img_dir.exists():
                    total_images += len([f for f in img_dir.glob("*") if f.suffix.lower() in ['.png', '.jpg', '.jpeg']])

        # 收集所有图片
        image_files = []
        for name in file_names:
            md_files = list(Path(OUTPUT_DIR).rglob(f"{name}*.md"))
            if md_files:
                img_dir = md_files[0].parent / "images"
                if img_dir.exists():
                    image_files.extend([str(f) for f in img_dir.glob("*") if f.suffix.lower() in ['.png', '.jpg', '.jpeg']])

        status = (f"✓ 解析成功！\n\n"
                  f"文件数: {len(files)}\n"
                  f"文件: {', '.join(f.name for f in files)}\n"
                  f"输出目录: {OUTPUT_DIR}\n"
                  f"提取图片: {total_images} 张")

        markdown_content = "\n\n---\n\n".join(all_md) if all_md else "未生成 Markdown 内容"
        return status, markdown_content, image_files if image_files else None

    except Exception as e:
        return f"✗ 发生错误: {str(e)}", None, None


def create_ui():
    """创建 Gradio 界面"""

    with gr.Blocks(title="MinerU PDF 解析器") as demo:
        gr.Markdown("""
        # 🚀 MinerU PDF 解析器

        将 PDF 文档转换为 Markdown 格式，支持文字、图片、表格、公式提取

        **GPU 加速已启用**: NVIDIA GeForce RTX 3060 Ti (8GB) | **直接 Python API 调用，速度更快**
        """)

        # 共享的解析选项
        gr.Markdown("### ⚙️ 解析选项")
        backend = gr.Radio(
            choices=["pipeline", "hybrid-auto-engine", "vlm-auto-engine"],
            value="pipeline",
            label="后端选择",
            info="pipeline: 快速 | hybrid: 高精度 | vlm: 最高精度"
        )
        language = gr.Dropdown(
            choices=["ch", "en", "ch_server", "korean", "japan"],
            value="ch",
            label="语言",
            info="选择文档主要语言以提高 OCR 准确度"
        )
        with gr.Row():
            enable_formula = gr.Checkbox(label="解析公式", value=True)
            enable_table = gr.Checkbox(label="解析表格", value=True)

        with gr.Tabs():
            # Tab 1: 上传文件
            with gr.TabItem("📤 上传文件"):
                pdf_input = gr.File(
                    label="选择 PDF 文件",
                    file_types=[".pdf"],
                    type="filepath"
                )
                upload_btn = gr.Button("🔄 开始解析", variant="primary", size="lg")

            # Tab 2: 本地路径
            with gr.TabItem("📂 本地路径"):
                local_path_input = gr.Textbox(
                    label="输入本地文件或文件夹路径",
                    placeholder=r"例如: E:\pdfs\report.pdf 或 E:\pdfs",
                    lines=1
                )
                local_btn = gr.Button("🔄 开始解析", variant="primary", size="lg")

        # 输出区域
        status_output = gr.Textbox(label="状态", lines=5, interactive=False)

        with gr.Row():
            with gr.Column(scale=2):
                gr.Markdown("### 📄 解析结果")
                markdown_output = gr.Textbox(
                    label="Markdown 内容",
                    lines=20,
                    max_lines=30,
                    interactive=False
                )
            with gr.Column(scale=1):
                gr.Markdown("### 🖼️ 提取的图片")
                images_output = gr.Gallery(label="图片", columns=3, height="auto")

        with gr.Accordion("💡 使用说明", open=False):
            gr.Markdown("""
            ### 两种解析方式

            - **上传文件**: 通过浏览器上传 PDF 文件
            - **本地路径**: 直接输入本地文件路径或文件夹路径，支持批量解析

            ### 后端说明

            - **pipeline**: 速度快，无需下载大模型，推荐首次使用
            - **hybrid-auto-engine**: 高精度，首次需下载约 10GB 模型
            - **vlm-auto-engine**: 最高精度，首次需下载约 20GB 模型

            ### 注意事项

            - 首次使用 hybrid/vlm 后端会下载模型
            - 如遇显存不足，请使用 pipeline 后端
            - 解析结果保存在 output 目录下
            """)

        # 绑定事件
        upload_btn.click(
            fn=parse_pdf,
            inputs=[pdf_input, backend, language, enable_formula, enable_table],
            outputs=[status_output, markdown_output, images_output]
        )
        local_btn.click(
            fn=parse_local_path,
            inputs=[local_path_input, backend, language, enable_formula, enable_table],
            outputs=[status_output, markdown_output, images_output]
        )

        gr.Markdown("""
        ---
        **MinerU 2.7.6** | [GitHub](https://github.com/opendatalab/MinerU) | [文档](https://opendatalab.github.io/MinerU/)
        """)

    return demo


if __name__ == "__main__":
    print("=" * 60)
    print("MinerU Web 界面启动中...")
    print(f"输出目录: {OUTPUT_DIR}")
    print("GPU 加速: 已启用 (NVIDIA GeForce RTX 3060 Ti)")
    print("启动后请访问: http://localhost:7860")
    print("按 Ctrl+C 停止服务")
    print("=" * 60)

    demo = create_ui()
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_error=True
    )
