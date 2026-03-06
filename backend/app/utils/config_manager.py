"""配置管理工具 - 支持多供应商配置与使用统计"""
import json
import os
import base64
import logging
from datetime import datetime
from typing import Dict, List, Optional

from ..config import settings

logger = logging.getLogger(__name__)


def _obfuscate(value: str) -> str:
    """对敏感值做 Base64 编码（简单混淆，非加密）"""
    if not value:
        return value
    return base64.b64encode(value.encode("utf-8")).decode("utf-8")


def _deobfuscate(value: str) -> str:
    """还原 Base64 编码的值"""
    if not value:
        return value
    try:
        return base64.b64decode(value.encode("utf-8")).decode("utf-8")
    except Exception:
        return value


# 预置供应商信息（仅用于前端展示提示，不强制）
PRESET_PROVIDERS = {
    'minimax': {'name': 'MiniMax', 'base_url': 'https://api.minimax.chat/v1'},
    'kimi': {'name': 'Kimi / Moonshot', 'base_url': 'https://api.moonshot.cn/v1'},
    'deepseek': {'name': 'DeepSeek', 'base_url': 'https://api.deepseek.com/v1'},
    'qwen': {'name': '通义千问 (Qwen)', 'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1'},
    'zhipu': {'name': '智谱GLM', 'base_url': 'https://open.bigmodel.cn/api/paas/v4'},
    'siliconflow': {'name': '硅基流动', 'base_url': 'https://api.siliconflow.cn/v1'},
    'aihubmix': {'name': 'AiHubMix', 'base_url': 'https://aihubmix.com/v1'},
    'ollama': {'name': 'Ollama (本地)', 'base_url': 'http://localhost:11434/v1'},
}


class ConfigManager:
    """用户配置管理器 - 支持多供应商"""

    # 使用统计写入缓冲：累积 N 次调用后才写磁盘
    _USAGE_FLUSH_INTERVAL = 10

    def __init__(self):
        home = os.path.expanduser("~")
        new_dir = os.path.join(home, ".gt_audit_helper")
        old_dir = os.path.join(home, ".ai_write_helper")
        # 自动迁移旧版数据目录
        if not os.path.exists(new_dir) and os.path.exists(old_dir):
            try:
                import shutil
                shutil.copytree(old_dir, new_dir)
            except Exception:
                pass
        self.config_dir = new_dir
        self.config_file = os.path.join(self.config_dir, "user_config.json")
        self.usage_file = os.path.join(self.config_dir, "usage_stats.json")
        os.makedirs(self.config_dir, exist_ok=True)
        # 使用统计内存缓冲
        self._usage_buffer: Optional[dict] = None
        self._usage_dirty_count = 0

    # ─── 兼容旧版：迁移单配置到多供应商格式 ───

    def _migrate_if_needed(self, data: dict) -> dict:
        """将旧版单配置格式迁移为多供应商格式"""
        if 'providers' in data:
            return data  # 已是新格式

        # 旧格式: {api_key, base_url, model_name, word_count}
        old_key = data.get('api_key', '')
        old_url = data.get('base_url', '')
        old_model = data.get('model_name', settings.default_model)
        old_word_count = data.get('word_count', 100000)

        new_data = {
            'providers': {},
            'active_provider': '',
            'model_name': old_model,
            'word_count': old_word_count,
        }

        if old_key:
            # 根据 base_url 猜测供应商 ID
            provider_id = self._guess_provider_id(old_url)
            new_data['providers'][provider_id] = {
                'name': PRESET_PROVIDERS.get(provider_id, {}).get('name', provider_id),
                'api_key': old_key,  # 保持原始编码状态
                'base_url': old_url,
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
            }
            new_data['active_provider'] = provider_id

        return new_data

    @staticmethod
    def _guess_provider_id(base_url: str) -> str:
        """根据 base_url 猜测供应商 ID"""
        if not base_url:
            return 'default'
        url_lower = base_url.lower()
        for pid, info in PRESET_PROVIDERS.items():
            if info['base_url'].split('//')[1].split('/')[0] in url_lower:
                return pid
        return 'custom'

    # ─── 底层读写 ───

    def _load_raw(self) -> dict:
        """读取原始配置文件"""
        if not os.path.exists(self.config_file):
            return {}
        try:
            with open(self.config_file, 'r', encoding='utf-8-sig') as f:
                return json.load(f)
        except Exception as e:
            logger.warning("读取配置文件失败: %s", e)
            return {}

    def _save_raw(self, data: dict) -> bool:
        """写入配置文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            try:
                import stat
                os.chmod(self.config_file, stat.S_IRUSR | stat.S_IWUSR)
            except (OSError, AttributeError):
                pass
            return True
        except Exception as e:
            logger.error("保存配置文件失败: %s", e)
            return False

    def _load_data(self) -> dict:
        """加载并自动迁移配置"""
        raw = self._load_raw()
        return self._migrate_if_needed(raw)

    # ─── 供应商管理 ───

    def get_providers(self) -> List[dict]:
        """获取所有已保存的供应商列表（api_key 做掩码处理）"""
        data = self._load_data()
        providers = data.get('providers', {})
        active = data.get('active_provider', '')
        result = []
        for pid, pinfo in providers.items():
            real_key = _deobfuscate(pinfo.get('api_key', ''))
            if real_key and len(real_key) > 8:
                masked = real_key[:4] + '*' * (len(real_key) - 8) + real_key[-4:]
            elif real_key:
                masked = '*' * len(real_key)
            else:
                masked = ''
            result.append({
                'id': pid,
                'name': pinfo.get('name', pid),
                'base_url': pinfo.get('base_url', ''),
                'api_key_masked': masked,
                'has_key': bool(real_key),
                'is_active': pid == active,
                'created_at': pinfo.get('created_at', ''),
            })
        return result

    def save_provider(self, provider_id: str, name: str, api_key: str, base_url: str) -> bool:
        """保存或更新一个供应商配置"""
        data = self._load_data()
        providers = data.setdefault('providers', {})

        existing = providers.get(provider_id, {})
        # api_key 为空时保留旧值
        if api_key:
            encoded_key = _obfuscate(api_key)
        else:
            encoded_key = existing.get('api_key', '')

        providers[provider_id] = {
            'name': name,
            'api_key': encoded_key,
            'base_url': base_url,
            'created_at': existing.get('created_at', datetime.now().strftime('%Y-%m-%d %H:%M')),
        }

        # 如果是第一个供应商或没有激活的，自动激活
        if not data.get('active_provider') or data['active_provider'] not in providers:
            data['active_provider'] = provider_id

        return self._save_raw(data)

    def delete_provider(self, provider_id: str) -> bool:
        """删除一个供应商配置"""
        data = self._load_data()
        providers = data.get('providers', {})
        if provider_id not in providers:
            return False
        del providers[provider_id]
        # 如果删除的是当前激活的，切换到第一个
        if data.get('active_provider') == provider_id:
            data['active_provider'] = next(iter(providers), '')
        return self._save_raw(data)

    def set_active_provider(self, provider_id: str) -> bool:
        """切换当前使用的供应商"""
        data = self._load_data()
        if provider_id not in data.get('providers', {}):
            return False
        data['active_provider'] = provider_id
        return self._save_raw(data)

    def get_active_provider_config(self) -> dict:
        """获取当前激活供应商的真实配置（含明文 api_key，仅后端内部使用）"""
        data = self._load_data()
        active_id = data.get('active_provider', '')
        providers = data.get('providers', {})
        pinfo = providers.get(active_id, {})
        return {
            'api_key': _deobfuscate(pinfo.get('api_key', '')),
            'base_url': pinfo.get('base_url', ''),
        }

    def get_provider_real_key(self, provider_id: str) -> str:
        """获取指定供应商的真实 api_key（仅后端内部使用）"""
        data = self._load_data()
        pinfo = data.get('providers', {}).get(provider_id, {})
        return _deobfuscate(pinfo.get('api_key', ''))

    # ─── 当前配置（兼容旧接口） ───

    def load_config(self) -> Dict:
        """加载当前激活的配置（兼容旧版调用）"""
        data = self._load_data()
        active_cfg = self.get_active_provider_config()
        return {
            'api_key': active_cfg['api_key'],
            'base_url': active_cfg['base_url'],
            'model_name': data.get('model_name', settings.default_model),
            'word_count': data.get('word_count', 100000),
        }

    def save_config(self, api_key: str, base_url: str, model_name: str, word_count: int = None) -> bool:
        """保存配置（兼容旧版调用，同时更新供应商和全局设置）"""
        data = self._load_data()

        # 更新全局设置
        data['model_name'] = model_name
        if word_count is not None:
            data['word_count'] = word_count

        # 更新当前激活供应商的 key 和 url
        active_id = data.get('active_provider', '')
        providers = data.setdefault('providers', {})

        if active_id and active_id in providers:
            existing = providers[active_id]
            if api_key:
                existing['api_key'] = _obfuscate(api_key)
            if base_url:  # 只有非空时才更新，防止覆盖已有值
                existing['base_url'] = base_url
        elif api_key:
            # 没有激活供应商，创建一个
            pid = self._guess_provider_id(base_url or '')
            providers[pid] = {
                'name': PRESET_PROVIDERS.get(pid, {}).get('name', pid),
                'api_key': _obfuscate(api_key),
                'base_url': base_url or '',
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
            }
            data['active_provider'] = pid

        return self._save_raw(data)

    # ─── 使用统计 ───

    def _load_usage(self) -> dict:
        """加载使用统计"""
        if not os.path.exists(self.usage_file):
            return {}
        try:
            with open(self.usage_file, 'r', encoding='utf-8-sig') as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_usage(self, usage: dict) -> None:
        """保存使用统计"""
        try:
            with open(self.usage_file, 'w', encoding='utf-8') as f:
                json.dump(usage, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("保存使用统计失败: %s", e)

    def record_usage(self, provider_id: str, model_name: str, input_tokens: int = 0, output_tokens: int = 0) -> None:
        """记录一次 API 调用（内存缓冲，累积后批量写磁盘）"""
        if self._usage_buffer is None:
            self._usage_buffer = self._load_usage()

        usage = self._usage_buffer
        today = datetime.now().strftime('%Y-%m-%d')

        # 按供应商统计
        provider_stats = usage.setdefault(provider_id, {})
        provider_stats.setdefault('total_calls', 0)
        provider_stats.setdefault('total_input_tokens', 0)
        provider_stats.setdefault('total_output_tokens', 0)
        provider_stats['total_calls'] += 1
        provider_stats['total_input_tokens'] += input_tokens
        provider_stats['total_output_tokens'] += output_tokens
        provider_stats['last_used'] = datetime.now().strftime('%Y-%m-%d %H:%M')

        # 按模型统计
        model_stats = provider_stats.setdefault('models', {})
        m = model_stats.setdefault(model_name, {})
        m.setdefault('calls', 0)
        m.setdefault('input_tokens', 0)
        m.setdefault('output_tokens', 0)
        m['calls'] += 1
        m['input_tokens'] += input_tokens
        m['output_tokens'] += output_tokens
        m['last_used'] = datetime.now().strftime('%Y-%m-%d %H:%M')

        # 按日统计
        daily = provider_stats.setdefault('daily', {})
        d = daily.setdefault(today, {'calls': 0, 'input_tokens': 0, 'output_tokens': 0})
        d['calls'] += 1
        d['input_tokens'] += input_tokens
        d['output_tokens'] += output_tokens

        self._usage_dirty_count += 1
        if self._usage_dirty_count >= self._USAGE_FLUSH_INTERVAL:
            self.flush_usage()

    def flush_usage(self) -> None:
        """将内存中的使用统计写入磁盘"""
        if self._usage_buffer is not None and self._usage_dirty_count > 0:
            self._save_usage(self._usage_buffer)
            self._usage_dirty_count = 0

    def get_usage_stats(self) -> dict:
        """获取使用统计摘要"""
        # 先刷新缓冲确保数据完整
        self.flush_usage()
        usage = self._usage_buffer if self._usage_buffer is not None else self._load_usage()
        data = self._load_data()
        providers = data.get('providers', {})
        result = []
        for pid, pinfo in providers.items():
            stats = usage.get(pid, {})
            model_list = []
            for mname, mstats in stats.get('models', {}).items():
                model_list.append({
                    'model': mname,
                    'calls': mstats.get('calls', 0),
                    'input_tokens': mstats.get('input_tokens', 0),
                    'output_tokens': mstats.get('output_tokens', 0),
                    'last_used': mstats.get('last_used', ''),
                })
            result.append({
                'provider_id': pid,
                'provider_name': pinfo.get('name', pid),
                'total_calls': stats.get('total_calls', 0),
                'total_input_tokens': stats.get('total_input_tokens', 0),
                'total_output_tokens': stats.get('total_output_tokens', 0),
                'last_used': stats.get('last_used', ''),
                'models': model_list,
            })
        return {'providers': result}


# 全局配置管理器实例
config_manager = ConfigManager()
