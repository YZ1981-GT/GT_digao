"""审计底稿模板管理服务。

存储路径遵循现有 KnowledgeService 的文件系统模式：
~/.gt_audit_helper/templates/{template_id}/
  - meta.json   模板元数据
  - original.{ext}  原始模板文件
"""

import json
import logging
import os
import re
import shutil
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from ..models.audit_schemas import (
    TemplateInfo,
    TemplateSection,
    TemplateStructure,
    TemplateType,
)

logger = logging.getLogger(__name__)

# 支持的模板文件格式
SUPPORTED_FORMATS = {".docx", ".xlsx", ".xls", ".pdf"}


class TemplateManager:
    """审计底稿模板管理服务。"""

    TEMPLATE_DIR = os.path.join(
        os.path.expanduser("~"), ".gt_audit_helper", "templates"
    )

    TEMPLATE_TYPES: Dict[str, str] = {
        "audit_plan": "审计计划模板",
        "audit_summary": "审计小结模板",
        "due_diligence": "尽调报告模板",
        "audit_report": "审计报告模板",
        "custom": "其他自定义模板",
    }

    def __init__(self) -> None:
        os.makedirs(self.TEMPLATE_DIR, exist_ok=True)

    # ─── 内部工具方法 ───

    def _template_dir(self, template_id: str) -> str:
        return os.path.join(self.TEMPLATE_DIR, template_id)

    def _meta_path(self, template_id: str) -> str:
        return os.path.join(self._template_dir(template_id), "meta.json")

    def _original_path(self, template_id: str, ext: str) -> str:
        return os.path.join(
            self._template_dir(template_id), f"original{ext}"
        )

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _load_meta(self, template_id: str) -> Optional[Dict[str, Any]]:
        path = self._meta_path(template_id)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load template meta %s: %s", template_id, exc)
            return None

    def _save_meta(self, data: Dict[str, Any]) -> None:
        template_id = data["id"]
        tpl_dir = self._template_dir(template_id)
        os.makedirs(tpl_dir, exist_ok=True)
        path = self._meta_path(template_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _meta_to_info(data: Dict[str, Any]) -> TemplateInfo:
        structure = None
        if data.get("structure"):
            structure = TemplateStructure(**data["structure"])
        return TemplateInfo(
            id=data["id"],
            name=data["name"],
            template_type=TemplateType(data["template_type"]),
            file_format=data["file_format"],
            structure=structure,
            uploaded_at=data["uploaded_at"],
            file_size=data.get("file_size", 0),
        )

    # ─── 公开接口 ───

    async def upload_template(
        self, file_path: str, filename: str, template_type: str
    ) -> TemplateInfo:
        """上传并解析模板文件（docx/xlsx/xls/pdf）。

        1. 校验文件格式
        2. 复制原始文件到模板目录
        3. 解析模板结构
        4. 保存元数据
        """
        ext = os.path.splitext(filename)[1].lower()

        if ext not in SUPPORTED_FORMATS:
            raise ValueError(
                f"不支持的模板文件格式：{ext}，"
                f"支持格式：{', '.join(sorted(SUPPORTED_FORMATS))}"
            )

        if template_type not in self.TEMPLATE_TYPES:
            raise ValueError(
                f"不支持的模板类型：{template_type}，"
                f"支持类型：{', '.join(self.TEMPLATE_TYPES.keys())}"
            )

        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"文件不存在：{file_path}")

        file_size = os.path.getsize(file_path)
        template_id = str(uuid4())
        now = self._now_iso()

        # 复制原始文件
        tpl_dir = self._template_dir(template_id)
        os.makedirs(tpl_dir, exist_ok=True)
        dest = self._original_path(template_id, ext)
        shutil.copy2(file_path, dest)

        # 解析模板结构
        structure: Optional[TemplateStructure] = None
        parse_error: Optional[str] = None
        try:
            structure = await self.parse_template_structure(dest)
        except Exception as exc:
            logger.warning("模板结构解析失败 %s: %s", filename, exc)
            parse_error = str(exc)

        meta: Dict[str, Any] = {
            "id": template_id,
            "name": os.path.splitext(filename)[0],
            "template_type": template_type,
            "file_format": ext.lstrip("."),
            "file_size": file_size,
            "structure": structure.model_dump() if structure else None,
            "parse_error": parse_error,
            "uploaded_at": now,
            "updated_at": now,
        }
        self._save_meta(meta)

        logger.info("Uploaded template %s (%s)", template_id, filename)
        return self._meta_to_info(meta)

    async def parse_template_structure(self, file_path: str) -> TemplateStructure:
        """解析模板结构，提取章节标题、表格结构和填充区域。

        使用 WorkpaperParser 的解析能力提取文件内容，
        然后从解析结果中识别章节结构。
        """
        from .workpaper_parser import WorkpaperParser

        parser = WorkpaperParser()
        ext = os.path.splitext(file_path)[1].lower()

        sections: List[TemplateSection] = []
        tables: List[Dict[str, Any]] = []

        try:
            if ext == ".docx":
                word_result = await parser.parse_word(file_path)
                sections = self._extract_sections_from_word(word_result)
                tables = self._extract_tables_info(word_result.tables)

            elif ext in (".xlsx", ".xls"):
                excel_result = await parser.parse_excel(file_path, ext)
                sections = self._extract_sections_from_excel(excel_result)
                tables = self._extract_tables_from_excel(excel_result)

            elif ext == ".pdf":
                pdf_result = await parser.parse_pdf(file_path)
                sections = self._extract_sections_from_pdf(pdf_result)
                tables = [
                    {"rows": len(t), "columns": len(t[0]) if t else 0}
                    for t in pdf_result.tables
                ]

            else:
                raise ValueError(f"不支持的模板格式：{ext}")

        except ValueError:
            raise
        except Exception as exc:
            raise RuntimeError(f"模板结构解析失败：{exc}") from exc

        return TemplateStructure(
            sections=sections,
            tables=tables,
        )

    def list_templates(self) -> List[TemplateInfo]:
        """列出所有已上传模板。"""
        results: List[TemplateInfo] = []
        if not os.path.isdir(self.TEMPLATE_DIR):
            return results

        for entry in os.listdir(self.TEMPLATE_DIR):
            tpl_dir = os.path.join(self.TEMPLATE_DIR, entry)
            if not os.path.isdir(tpl_dir):
                continue
            data = self._load_meta(entry)
            if data is None:
                continue
            results.append(self._meta_to_info(data))

        # 按上传时间倒序
        results.sort(key=lambda t: t.uploaded_at, reverse=True)
        return results

    def get_template(self, template_id: str) -> Optional[TemplateInfo]:
        """获取模板详情。"""
        data = self._load_meta(template_id)
        if data is None:
            return None
        return self._meta_to_info(data)

    def delete_template(self, template_id: str) -> bool:
        """删除模板及其所有文件。"""
        tpl_dir = self._template_dir(template_id)
        if not os.path.isdir(tpl_dir):
            return False
        try:
            shutil.rmtree(tpl_dir)
            logger.info("Deleted template %s", template_id)
            return True
        except OSError as exc:
            logger.error("Failed to delete template %s: %s", template_id, exc)
            return False

    async def update_template(
        self, template_id: str, file_path: str, filename: str
    ) -> TemplateInfo:
        """更新模板（替换文件并重新解析结构）。"""
        data = self._load_meta(template_id)
        if data is None:
            raise ValueError(f"模板不存在：{template_id}")

        ext = os.path.splitext(filename)[1].lower()
        if ext not in SUPPORTED_FORMATS:
            raise ValueError(
                f"不支持的模板文件格式：{ext}，"
                f"支持格式：{', '.join(sorted(SUPPORTED_FORMATS))}"
            )

        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"文件不存在：{file_path}")

        file_size = os.path.getsize(file_path)

        # 删除旧的原始文件
        tpl_dir = self._template_dir(template_id)
        for f in os.listdir(tpl_dir):
            if f.startswith("original"):
                os.remove(os.path.join(tpl_dir, f))

        # 复制新文件
        dest = self._original_path(template_id, ext)
        shutil.copy2(file_path, dest)

        # 重新解析结构
        structure: Optional[TemplateStructure] = None
        parse_error: Optional[str] = None
        try:
            structure = await self.parse_template_structure(dest)
        except Exception as exc:
            logger.warning("模板结构解析失败 %s: %s", filename, exc)
            parse_error = str(exc)

        data["name"] = os.path.splitext(filename)[0]
        data["file_format"] = ext.lstrip(".")
        data["file_size"] = file_size
        data["structure"] = structure.model_dump() if structure else None
        data["parse_error"] = parse_error
        data["updated_at"] = self._now_iso()
        self._save_meta(data)

        logger.info("Updated template %s (%s)", template_id, filename)
        return self._meta_to_info(data)

    def get_template_file_path(self, template_id: str) -> Optional[str]:
        """获取模板原始文件路径。"""
        tpl_dir = self._template_dir(template_id)
        if not os.path.isdir(tpl_dir):
            return None
        for f in os.listdir(tpl_dir):
            if f.startswith("original"):
                return os.path.join(tpl_dir, f)
        return None

    # ─── 内部解析辅助方法 ───

    @staticmethod
    def _extract_sections_from_word(word_result) -> List[TemplateSection]:
        """从 Word 解析结果中提取章节结构。"""
        sections: List[TemplateSection] = []
        idx = 0

        for para in word_result.paragraphs:
            text = para.get("text", "").strip()
            if not text:
                continue

            level = para.get("level")
            if level is not None:
                # 检测该标题下是否有表格（简单启发式：标题后紧跟表格）
                has_table = False
                fillable = _detect_fillable_fields(text)

                sections.append(
                    TemplateSection(
                        index=idx,
                        title=text,
                        level=level,
                        has_table=has_table,
                        fillable_fields=fillable,
                    )
                )
                idx += 1

        # 标记包含表格的章节
        if word_result.tables and sections:
            sections[-1].has_table = True

        return sections

    @staticmethod
    def _extract_sections_from_excel(excel_result) -> List[TemplateSection]:
        """从 Excel 解析结果中提取章节结构。

        Excel 模板通常以工作表名作为章节。
        """
        sections: List[TemplateSection] = []
        for idx, sheet in enumerate(excel_result.sheets):
            fillable = []
            # 扫描第一列查找可能的填充字段
            for cell in sheet.cells:
                val = str(cell.value).strip() if cell.value else ""
                if val and ("填写" in val or "请输入" in val or val.endswith("：")):
                    fillable.append(val.rstrip("：:"))

            sections.append(
                TemplateSection(
                    index=idx,
                    title=sheet.name,
                    level=1,
                    has_table=True,  # Excel 本身就是表格
                    fillable_fields=fillable[:20],  # 限制数量
                )
            )
        return sections

    @staticmethod
    def _extract_sections_from_pdf(pdf_result) -> List[TemplateSection]:
        """从 PDF 解析结果中提取章节结构。

        通过正则匹配常见的中文章节标题模式。
        """
        sections: List[TemplateSection] = []
        text = pdf_result.text or ""
        idx = 0

        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue

            level = _detect_heading_level(line)
            if level is not None:
                fillable = _detect_fillable_fields(line)
                sections.append(
                    TemplateSection(
                        index=idx,
                        title=line,
                        level=level,
                        has_table=False,
                        fillable_fields=fillable,
                    )
                )
                idx += 1

        # 标记包含表格的章节
        if pdf_result.tables and sections:
            sections[-1].has_table = len(pdf_result.tables) > 0

        return sections

    @staticmethod
    def _extract_tables_info(
        tables: List[List[List[str]]],
    ) -> List[Dict[str, Any]]:
        """从 Word 表格数据中提取表格结构信息。"""
        result: List[Dict[str, Any]] = []
        for i, table in enumerate(tables):
            info: Dict[str, Any] = {
                "index": i,
                "rows": len(table),
                "columns": len(table[0]) if table else 0,
            }
            # 提取表头
            if table:
                info["headers"] = table[0]
            result.append(info)
        return result

    @staticmethod
    def _extract_tables_from_excel(excel_result) -> List[Dict[str, Any]]:
        """从 Excel 解析结果中提取表格结构信息。"""
        result: List[Dict[str, Any]] = []
        for i, sheet in enumerate(excel_result.sheets):
            max_row = 0
            max_col = 0
            for cell in sheet.cells:
                r = int(cell.row) if hasattr(cell, "row") else 0
                c = int(cell.column) if hasattr(cell, "column") else 0
                max_row = max(max_row, r)
                max_col = max(max_col, c)
            result.append({
                "index": i,
                "sheet_name": sheet.name,
                "rows": max_row,
                "columns": max_col,
            })
        return result


# ─── 模块级辅助函数 ───

# 中文章节标题模式
_HEADING_PATTERNS = [
    # 一级标题：第一章、第一部分、一、
    (1, re.compile(r"^第[一二三四五六七八九十百]+[章部分节篇]")),
    (1, re.compile(r"^[一二三四五六七八九十]+[、.]")),
    # 二级标题：（一）、(一)
    (2, re.compile(r"^[（(][一二三四五六七八九十]+[）)]")),
    # 三级标题：1.、1、
    (2, re.compile(r"^\d+[、.]")),
    # 四级标题：(1)、（1）
    (3, re.compile(r"^[（(]\d+[）)]")),
]


def _detect_heading_level(line: str) -> Optional[int]:
    """检测文本行是否为标题，返回标题层级或 None。"""
    line = line.strip()
    if not line or len(line) > 100:
        return None

    for level, pattern in _HEADING_PATTERNS:
        if pattern.match(line):
            return level
    return None


def _detect_fillable_fields(text: str) -> List[str]:
    """从文本中检测可能的填充字段。

    匹配 【xxx】、____、_______ 等占位符模式。
    """
    fields: List[str] = []

    # 【待补充】、【填写xxx】
    for m in re.finditer(r"【([^】]+)】", text):
        fields.append(m.group(1))

    # ______ 下划线占位
    if "____" in text:
        # 提取下划线前的标签文字
        parts = re.split(r"_{3,}", text)
        for part in parts:
            label = part.strip().rstrip("：:")
            if label and len(label) < 20:
                fields.append(label)

    return fields
