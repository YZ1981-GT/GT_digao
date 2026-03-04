"""复核提示词管理服务。

预置提示词从项目 TSJ/ 目录加载 markdown 文件，按会计科目分类。
支持用户对预置提示词进行修改、替换和追加补充。
每个提示词携带来源标识（preset/user_modified/user_replaced/user_appended）。

用户自定义提示词存储路径：~/.gt_audit_helper/prompts/
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import uuid4

from ..models.audit_schemas import (
    PromptSource,
    ReviewPromptDetail,
    ReviewPromptInfo,
)
from .prompt_git_service import PromptGitService

logger = logging.getLogger(__name__)

# 文件占位符，复核时替换为实际底稿文件列表
FILE_PLACEHOLDER = "{{#sys.files#}}"

# 预置提示词按会计科目分类
PRESET_CATEGORIES: Dict[str, str] = {
    "monetary_funds": "货币资金",
    "accounts_receivable": "应收账款",
    "inventory": "存货",
    "fixed_assets": "固定资产",
    "long_term_equity_investment": "长期股权投资",
    "revenue": "收入",
    "cost": "成本",
    "intangible_assets": "无形资产",
    "employee_compensation": "职工薪酬",
    "taxes_payable": "应交税费",
    "other_payables": "其他应付款",
    "accounts_payable": "应付账款",
    "construction_in_progress": "在建工程",
    "investment_property": "投资性房地产",
    "borrowings": "借款",
    "equity": "所有者权益",
    "audit_plan": "审计方案",
    "overall_strategy": "总体审计策略及具体审计计划",
    "other": "其他",
}

# 会计科目关键词映射（从文件名中的中文名推断分类 key）
# 值为 PRESET_CATEGORIES 中的中文名 → key
SUBJECT_KEYWORDS: Dict[str, str] = {
    "货币资金": "monetary_funds",
    "应收账款": "accounts_receivable",
    "应收票据": "accounts_receivable",
    "应收款项融资": "accounts_receivable",
    "预付账款": "accounts_receivable",
    "其他应收款": "other_payables",
    "存货": "inventory",
    "合同资产": "revenue",
    "固定资产": "fixed_assets",
    "在建工程": "construction_in_progress",
    "无形资产": "intangible_assets",
    "开发支出": "intangible_assets",
    "长期股权投资": "long_term_equity_investment",
    "投资性房地产": "investment_property",
    "长期待摊费用": "other",
    "递延所得税资产": "taxes_payable",
    "递延所得税负债": "taxes_payable",
    "使用权资产": "fixed_assets",
    "商誉": "other",
    "长期应收款": "accounts_receivable",
    "债权投资": "long_term_equity_investment",
    "其他债权投资": "long_term_equity_investment",
    "其他非流动资产": "other",
    "其他流动资产": "other",
    "其他权益工具": "equity",
    "交易性金融资产": "long_term_equity_investment",
    "交易性金融负债": "borrowings",
    "衍生金融资产": "long_term_equity_investment",
    "持有待售资产": "other",
    "持有待售负债": "other",
    "一年内到期的非流动资产": "other",
    "一年内到期的非流动负债": "borrowings",
    "短期借款": "borrowings",
    "应付票据": "accounts_payable",
    "应付账款": "accounts_payable",
    "合同负债": "revenue",
    "应付职工薪酬": "employee_compensation",
    "长期应付职工薪酬": "employee_compensation",
    "应交税费": "taxes_payable",
    "其他应付款": "other_payables",
    "其他流动负债": "other",
    "其他非流动负债": "other",
    "长期借款": "borrowings",
    "应付债券": "borrowings",
    "长期应付款": "other",
    "预计负债": "other",
    "递延收益": "revenue",
    "租赁负债": "borrowings",
    "实收资本": "equity",
    "股本": "equity",
    "资本公积": "equity",
    "盈余公积": "equity",
    "专项储备": "equity",
    "其他综合收益": "equity",
    "收入": "revenue",
    "成本": "cost",
    "销售费用": "cost",
    "管理费用": "cost",
    "财务费用": "cost",
    "研发费用": "cost",
    "所得税费用": "taxes_payable",
    "投资收益": "long_term_equity_investment",
    "公允价值变动收益": "long_term_equity_investment",
    "资产处置收益": "fixed_assets",
    "资产减值损失": "other",
    "信用减值损失": "accounts_receivable",
    "营业外收入": "other",
    "营业外支出": "other",
    "其他收益": "other",
    "审计方案": "audit_plan",
    "总体审计策略": "overall_strategy",
    "审计计划": "overall_strategy",
}


def _generate_prompt_id(filename: str) -> str:
    """根据文件名生成稳定的提示词 ID（md5前12位）。"""
    return hashlib.md5(filename.encode("utf-8")).hexdigest()[:12]


class PromptLibrary:
    """复核提示词管理服务。

    预置提示词从项目 TSJ/ 目录加载 markdown 文件，按会计科目分类。
    每个 markdown 文件是一个独立的预置提示词。
    提示词中的 {{#sys.files#}} 占位符在复核时替换为实际上传的底稿文件列表。

    支持用户对预置提示词进行修改（保留原始版本）、替换（完全替换内容）和追加补充。
    每个提示词携带来源标识（preset/user_modified/user_replaced/user_appended）。
    通过 PromptGitService 实现与远程 Git 仓库的同步。
    """

    # TSJ 目录路径（预置提示词来源）
    TSJ_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "TSJ")

    # 用户自定义提示词存储路径
    CUSTOM_PROMPT_DIR = os.path.join(
        os.path.expanduser("~"), ".gt_audit_helper", "prompts"
    )

    def __init__(self) -> None:
        self._preset_prompts: Optional[List[ReviewPromptInfo]] = None
        self.git_service = PromptGitService()
        os.makedirs(self.CUSTOM_PROMPT_DIR, exist_ok=True)

    # ─── 预置提示词加载 ───

    def _load_preset_prompts(self) -> List[ReviewPromptInfo]:
        """从 TSJ/ 目录扫描并加载所有 markdown 格式的预置提示词文件。"""
        prompts: List[ReviewPromptInfo] = []
        tsj_dir = os.path.normpath(self.TSJ_DIR)

        if not os.path.isdir(tsj_dir):
            logger.warning("TSJ directory not found: %s", tsj_dir)
            return prompts

        for filename in sorted(os.listdir(tsj_dir)):
            if not filename.endswith(".md"):
                continue

            filepath = os.path.join(tsj_dir, filename)
            if not os.path.isfile(filepath):
                continue

            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                logger.error("Failed to read TSJ file %s: %s", filename, e)
                continue

            prompt_id = _generate_prompt_id(filename)
            name = os.path.splitext(filename)[0]
            subject_key = self._classify_by_subject(filename)
            subject_label = PRESET_CATEGORIES.get(subject_key, "其他")
            summary = content[:100].replace("\n", " ").strip()

            # Check if user has a custom version
            custom_data = self._load_custom_json(prompt_id)
            source = PromptSource.PRESET
            usage_count = 0
            if custom_data:
                source = PromptSource(custom_data.get("source", PromptSource.PRESET))
                usage_count = custom_data.get("usage_count", 0)

            prompts.append(
                ReviewPromptInfo(
                    id=prompt_id,
                    name=name,
                    subject=subject_label,
                    source_file=filename,
                    summary=summary,
                    source=source,
                    is_preset=True,
                    usage_count=usage_count,
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
            )

        self._preset_prompts = prompts
        return prompts

    def _classify_by_subject(self, filename: str) -> str:
        """根据文件名推断会计科目分类。

        匹配 SUBJECT_KEYWORDS 中的中文关键词，返回对应的分类 key。
        未匹配到则返回 'other'。
        """
        name = os.path.splitext(filename)[0]
        # Try longest match first to avoid partial matches
        for keyword in sorted(SUBJECT_KEYWORDS.keys(), key=len, reverse=True):
            if keyword in name:
                return SUBJECT_KEYWORDS[keyword]
        return "other"

    # ─── 自定义提示词 JSON 存储 ───

    def _custom_json_path(self, prompt_id: str) -> str:
        return os.path.join(self.CUSTOM_PROMPT_DIR, f"{prompt_id}.json")

    def _load_custom_json(self, prompt_id: str) -> Optional[Dict]:
        path = self._custom_json_path(prompt_id)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Failed to load custom prompt %s: %s", prompt_id, e)
            return None

    def _save_custom_json(self, data: Dict) -> None:
        path = self._custom_json_path(data["id"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _delete_custom_json(self, prompt_id: str) -> bool:
        path = self._custom_json_path(prompt_id)
        if os.path.isfile(path):
            os.remove(path)
            return True
        return False

    # ─── 预置提示词 TSJ 文件读取 ───

    def _read_tsj_content(self, filename: str) -> Optional[str]:
        """Read content from a TSJ preset file."""
        filepath = os.path.join(os.path.normpath(self.TSJ_DIR), filename)
        if not os.path.isfile(filepath):
            return None
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error("Failed to read TSJ file %s: %s", filename, e)
            return None

    def _find_preset_info(self, prompt_id: str) -> Optional[ReviewPromptInfo]:
        """Find a preset prompt info by ID."""
        presets = self.get_preset_prompts()
        for p in presets:
            if p.id == prompt_id:
                return p
        return None

    # ─── 公开接口 ───

    def get_preset_prompts(self) -> List[ReviewPromptInfo]:
        """获取所有预置提示词（从 TSJ 目录加载，带缓存）。"""
        if self._preset_prompts is None:
            self._load_preset_prompts()
        return self._preset_prompts or []

    def list_prompts(self, subject: Optional[str] = None) -> List[ReviewPromptInfo]:
        """列出提示词（预置 + 自定义），可按会计科目筛选。

        Args:
            subject: 会计科目分类 key（如 'monetary_funds'）或中文名（如 '货币资金'）。
        """
        # Collect preset prompts
        all_prompts: List[ReviewPromptInfo] = list(self.get_preset_prompts())

        # Collect user-appended custom prompts
        for filename in os.listdir(self.CUSTOM_PROMPT_DIR):
            if not filename.endswith(".json"):
                continue
            prompt_id = filename[:-5]  # strip .json
            data = self._load_custom_json(prompt_id)
            if data is None:
                continue
            # Only include user_appended prompts here; modified/replaced are
            # already represented by their preset entry with updated source.
            if data.get("source") != PromptSource.USER_APPENDED:
                continue
            all_prompts.append(
                ReviewPromptInfo(
                    id=data["id"],
                    name=data["name"],
                    subject=data.get("subject"),
                    source_file=None,
                    summary=data.get("content", "")[:100].replace("\n", " ").strip(),
                    source=PromptSource.USER_APPENDED,
                    is_preset=False,
                    usage_count=data.get("usage_count", 0),
                    created_at=data.get("created_at", ""),
                )
            )

        # Filter by subject if provided
        if subject:
            # Resolve subject: could be a key or a Chinese label
            target_label = PRESET_CATEGORIES.get(subject, subject)
            all_prompts = [
                p for p in all_prompts if p.subject == target_label
            ]

        return all_prompts

    def get_prompt(self, prompt_id: str) -> Optional[ReviewPromptDetail]:
        """获取提示词完整内容。

        对于预置提示词，从 TSJ 文件读取原始内容。
        若用户有自定义版本（修改/替换），返回自定义版本作为 content，
        原始 TSJ 内容作为 original_content。
        """
        # Check if it's a preset prompt
        preset_info = self._find_preset_info(prompt_id)
        custom_data = self._load_custom_json(prompt_id)

        if preset_info:
            # It's a preset prompt
            original_content = self._read_tsj_content(preset_info.source_file or "")
            if original_content is None:
                return None

            content = original_content
            source = PromptSource.PRESET
            has_custom = False
            usage_count = 0

            if custom_data and custom_data.get("source") in (
                PromptSource.USER_MODIFIED,
                PromptSource.USER_REPLACED,
            ):
                content = custom_data.get("content", original_content)
                source = PromptSource(custom_data["source"])
                has_custom = True
                usage_count = custom_data.get("usage_count", 0)
            elif custom_data:
                usage_count = custom_data.get("usage_count", 0)

            return ReviewPromptDetail(
                id=prompt_id,
                name=preset_info.name,
                subject=preset_info.subject,
                source_file=preset_info.source_file,
                content=content,
                original_content=original_content,
                has_file_placeholder=FILE_PLACEHOLDER in content,
                has_custom_version=has_custom,
                source=source,
                is_preset=True,
                usage_count=usage_count,
            )

        # Check if it's a user-appended custom prompt
        if custom_data and custom_data.get("source") == PromptSource.USER_APPENDED:
            content = custom_data.get("content", "")
            return ReviewPromptDetail(
                id=prompt_id,
                name=custom_data.get("name", ""),
                subject=custom_data.get("subject"),
                content=content,
                original_content=None,
                has_file_placeholder=FILE_PLACEHOLDER in content,
                has_custom_version=False,
                source=PromptSource.USER_APPENDED,
                is_preset=False,
                usage_count=custom_data.get("usage_count", 0),
            )

        return None

    def save_custom_prompt(
        self, name: str, content: str, subject: Optional[str] = None
    ) -> ReviewPromptInfo:
        """保存用户追加的自定义提示词（source=USER_APPENDED）。"""
        prompt_id = uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()

        data = {
            "id": prompt_id,
            "name": name,
            "content": content,
            "subject": subject,
            "source": PromptSource.USER_APPENDED,
            "is_preset": False,
            "usage_count": 0,
            "created_at": now,
            "original_preset_id": None,
        }
        self._save_custom_json(data)

        return ReviewPromptInfo(
            id=prompt_id,
            name=name,
            subject=subject,
            source_file=None,
            summary=content[:100].replace("\n", " ").strip(),
            source=PromptSource.USER_APPENDED,
            is_preset=False,
            usage_count=0,
            created_at=now,
        )

    def edit_preset_prompt(self, prompt_id: str, new_content: str) -> ReviewPromptInfo:
        """编辑预置提示词，保存为用户修改版本（source=USER_MODIFIED）。

        保留原始 TSJ 版本可通过 restore_preset_default 恢复。
        Raises ValueError if prompt_id is not a preset prompt.
        """
        preset_info = self._find_preset_info(prompt_id)
        if not preset_info:
            raise ValueError(f"Preset prompt not found: {prompt_id}")

        existing = self._load_custom_json(prompt_id) or {}
        now = datetime.now(timezone.utc).isoformat()

        data = {
            "id": prompt_id,
            "name": preset_info.name,
            "content": new_content,
            "subject": preset_info.subject,
            "source": PromptSource.USER_MODIFIED,
            "is_preset": True,
            "usage_count": existing.get("usage_count", 0),
            "created_at": existing.get("created_at", now),
            "original_preset_id": prompt_id,
        }
        self._save_custom_json(data)

        # Invalidate cache so next list reflects updated source
        self._preset_prompts = None

        return ReviewPromptInfo(
            id=prompt_id,
            name=preset_info.name,
            subject=preset_info.subject,
            source_file=preset_info.source_file,
            summary=new_content[:100].replace("\n", " ").strip(),
            source=PromptSource.USER_MODIFIED,
            is_preset=True,
            usage_count=data["usage_count"],
            created_at=data["created_at"],
        )

    def replace_preset_prompt(
        self, prompt_id: str, new_content: str
    ) -> ReviewPromptInfo:
        """完全替换预置提示词（source=USER_REPLACED）。

        保留原始 TSJ 版本可通过 restore_preset_default 恢复。
        Raises ValueError if prompt_id is not a preset prompt.
        """
        preset_info = self._find_preset_info(prompt_id)
        if not preset_info:
            raise ValueError(f"Preset prompt not found: {prompt_id}")

        existing = self._load_custom_json(prompt_id) or {}
        now = datetime.now(timezone.utc).isoformat()

        data = {
            "id": prompt_id,
            "name": preset_info.name,
            "content": new_content,
            "subject": preset_info.subject,
            "source": PromptSource.USER_REPLACED,
            "is_preset": True,
            "usage_count": existing.get("usage_count", 0),
            "created_at": existing.get("created_at", now),
            "original_preset_id": prompt_id,
        }
        self._save_custom_json(data)

        self._preset_prompts = None

        return ReviewPromptInfo(
            id=prompt_id,
            name=preset_info.name,
            subject=preset_info.subject,
            source_file=preset_info.source_file,
            summary=new_content[:100].replace("\n", " ").strip(),
            source=PromptSource.USER_REPLACED,
            is_preset=True,
            usage_count=data["usage_count"],
            created_at=data["created_at"],
        )

    def restore_preset_default(self, prompt_id: str) -> ReviewPromptInfo:
        """恢复预置提示词为 TSJ 目录原始版本。

        删除用户的自定义修改或替换版本。
        Raises ValueError if prompt_id is not a preset prompt.
        """
        preset_info = self._find_preset_info(prompt_id)
        if not preset_info:
            raise ValueError(f"Preset prompt not found: {prompt_id}")

        # Delete custom version if exists
        self._delete_custom_json(prompt_id)

        # Invalidate cache
        self._preset_prompts = None

        # Re-read original content for summary
        original_content = self._read_tsj_content(preset_info.source_file or "") or ""

        return ReviewPromptInfo(
            id=prompt_id,
            name=preset_info.name,
            subject=preset_info.subject,
            source_file=preset_info.source_file,
            summary=original_content[:100].replace("\n", " ").strip(),
            source=PromptSource.PRESET,
            is_preset=True,
            usage_count=0,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def delete_prompt(self, prompt_id: str) -> bool:
        """删除自定义提示词。

        预置提示词不可删除，尝试删除预置提示词会抛出 ValueError。
        """
        preset_info = self._find_preset_info(prompt_id)
        if preset_info:
            raise ValueError("预置提示词不可删除")

        # Must be a user-appended custom prompt
        deleted = self._delete_custom_json(prompt_id)
        if not deleted:
            raise ValueError(f"Prompt not found: {prompt_id}")
        return True

    def resolve_file_placeholder(
        self, prompt_content: str, uploaded_files: List[Dict[str, str]]
    ) -> str:
        """将 {{#sys.files#}} 占位符替换为实际底稿文件列表。

        Args:
            prompt_content: 原始提示词内容
            uploaded_files: 已上传底稿文件列表
                [{'filename': '...', 'parse_status': '...'}]

        Returns:
            替换占位符后的提示词内容
        """
        if FILE_PLACEHOLDER not in prompt_content:
            return prompt_content

        if not uploaded_files:
            file_list_str = "（无已上传底稿文件）"
        else:
            lines = []
            for i, f in enumerate(uploaded_files, 1):
                fname = f.get("filename", "未知文件")
                status = f.get("parse_status", "unknown")
                lines.append(f"{i}. {fname}（解析状态：{status}）")
            file_list_str = "\n".join(lines)

        return prompt_content.replace(FILE_PLACEHOLDER, file_list_str)

    def refresh_presets(self) -> None:
        """重新扫描 TSJ 目录，同步更新预置提示词列表。

        若用户已对某提示词进行过修改或替换，保留用户的自定义版本。
        """
        # Simply invalidate cache; next access will re-scan TSJ directory.
        # Custom versions are stored separately in CUSTOM_PROMPT_DIR and
        # are automatically picked up during _load_preset_prompts.
        self._preset_prompts = None
        self._load_preset_prompts()
        logger.info("Preset prompts refreshed from TSJ directory")

    def increment_usage_count(self, prompt_id: str) -> None:
        """增加提示词使用次数。

        For preset prompts without a custom JSON, creates a minimal tracking entry.
        For custom prompts, updates the existing JSON.
        """
        custom_data = self._load_custom_json(prompt_id)

        if custom_data:
            custom_data["usage_count"] = custom_data.get("usage_count", 0) + 1
            self._save_custom_json(custom_data)
        else:
            # Preset prompt with no custom version yet — create a tracking entry
            preset_info = self._find_preset_info(prompt_id)
            if preset_info is None:
                logger.warning("Cannot increment usage: prompt %s not found", prompt_id)
                return

            data = {
                "id": prompt_id,
                "name": preset_info.name,
                "content": None,  # No custom content, just tracking usage
                "subject": preset_info.subject,
                "source": PromptSource.PRESET,
                "is_preset": True,
                "usage_count": 1,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "original_preset_id": prompt_id,
            }
            self._save_custom_json(data)

        # Invalidate cache so usage count is reflected
        self._preset_prompts = None
