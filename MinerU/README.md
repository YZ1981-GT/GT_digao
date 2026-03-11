# MinerU 本地部署

PDF 文档解析工具，将 PDF 转换为 Markdown，支持文字、图片、表格、公式提取。

## 环境信息

- MinerU 2.7.6 | Python 3.12.4 | PyTorch 2.5.1 (CUDA 12.1)
- GPU: NVIDIA GeForce RTX 3060 Ti (8GB)

## 使用方式

### Web 界面

双击 `启动Web界面.bat`，浏览器访问 http://localhost:7860

### 命令行

```bash
# 激活环境
.\mineru_env\Scripts\activate

# 基础解析（快速，推荐日常使用）
mineru -p input.pdf -o output -b pipeline

# 高精度解析（首次需下载约 10GB 模型）
mineru -p input.pdf -o output -b hybrid-auto-engine

# 批量处理
mineru -p test_pdfs -o test_output -b pipeline

# 指定中文语言提高 OCR 准确度
mineru -p input.pdf -o output -b pipeline -l ch

# 指定页码范围（从 0 开始）
mineru -p input.pdf -o output -b pipeline -s 0 -e 10

# 国内用户加速模型下载（默认已配置）
mineru -p input.pdf -o output --source modelscope
```

## 后端对比

| 后端 | 精度 | 首次模型下载 | 适用场景 |
|------|------|-------------|----------|
| pipeline | 82+ | ~2GB | 日常使用，快速测试 |
| hybrid-auto-engine | 90+ | ~10GB | 复杂文档，高质量需求 |
| vlm-auto-engine | 95+ | ~20GB | 学术论文，最高精度 |

## 输出文件

- `*.md` — Markdown 文档内容
- `images/` — 提取的图片

## 相关链接

- [GitHub](https://github.com/opendatalab/MinerU) | [官方文档](https://opendatalab.github.io/MinerU/)
