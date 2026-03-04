"""配置相关API路由 - 支持多供应商管理与使用统计"""
import re
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
from ..models.schemas import ConfigRequest, ConfigResponse, ModelListResponse
from ..services.openai_service import OpenAIService
from ..utils.config_manager import config_manager, PRESET_PROVIDERS

router = APIRouter(prefix="/api/config", tags=["配置管理"])


# ─── 供应商管理 ───

class ProviderRequest(BaseModel):
    """供应商配置请求"""
    id: str = Field(default='', description="供应商ID，留空则自动从 base_url 推断")
    name: str = Field(default='', description="显示名称，留空则自动推断")
    api_key: str = Field(default='', description="API Key（空字符串表示不更新）")
    base_url: str = Field(default='', description="Base URL")


@router.get("/providers")
async def get_providers():
    """获取所有已保存的供应商列表"""
    try:
        providers = config_manager.get_providers()
        return {
            "success": True,
            "providers": providers,
            "presets": [
                {"id": k, "name": v["name"], "base_url": v["base_url"]}
                for k, v in PRESET_PROVIDERS.items()
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/providers/save")
async def save_provider(req: ProviderRequest):
    """保存或更新供应商配置"""
    try:
        # 自动推断 ID 和名称
        provider_id = req.id or config_manager._guess_provider_id(req.base_url)
        name = req.name
        if not name:
            preset = PRESET_PROVIDERS.get(provider_id)
            name = preset['name'] if preset else provider_id

        success = config_manager.save_provider(
            provider_id=provider_id,
            name=name,
            api_key=req.api_key,
            base_url=req.base_url,
        )
        return {"success": success, "message": "供应商配置已保存" if success else "保存失败"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/providers/{provider_id}")
async def delete_provider(provider_id: str):
    """删除供应商配置"""
    try:
        success = config_manager.delete_provider(provider_id)
        return {"success": success, "message": "已删除" if success else "供应商不存在"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/providers/activate/{provider_id}")
async def activate_provider(provider_id: str):
    """切换当前使用的供应商"""
    try:
        success = config_manager.set_active_provider(provider_id)
        return {"success": success, "message": "已切换" if success else "供应商不存在"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── 使用统计 ───

@router.get("/usage")
async def get_usage_stats():
    """获取使用统计"""
    try:
        stats = config_manager.get_usage_stats()
        return {"success": True, **stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── 兼容旧版接口 ───

@router.post("/save", response_model=ConfigResponse)
async def save_config(config: ConfigRequest):
    """保存配置（兼容旧版）"""
    try:
        # 如果 api_key 是掩码值，视为空（不更新）
        api_key = config.api_key or ''
        if re.search(r'\*{3,}', api_key):
            api_key = ''

        success = config_manager.save_config(
            api_key=api_key,
            base_url=config.base_url or "",
            model_name=config.model_name,
            word_count=config.word_count,
        )
        if success:
            return ConfigResponse(success=True, message="配置保存成功")
        return ConfigResponse(success=False, message="配置保存失败")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/load", response_model=dict)
async def load_config():
    """加载当前配置（兼容旧版）"""
    try:
        config = config_manager.load_config()
        api_key = config.get('api_key', '')
        has_key = bool(api_key)
        if api_key and len(api_key) > 8:
            config['api_key'] = api_key[:4] + '*' * (len(api_key) - 8) + api_key[-4:]
        elif api_key:
            config['api_key'] = '*' * len(api_key)
        config['has_api_key'] = has_key

        # 附带供应商列表，方便前端展示
        config['providers'] = config_manager.get_providers()
        return config
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models", response_model=ModelListResponse)
async def get_available_models(config: ConfigRequest):
    """获取可用的模型列表 - 使用当前激活供应商的配置"""
    try:
        # 始终使用当前激活供应商的真实配置
        active_config = config_manager.get_active_provider_config()
        api_key = active_config.get('api_key', '')
        base_url = active_config.get('base_url', '')

        if not api_key:
            return ModelListResponse(models=[], success=False, message="当前供应商未配置 API Key")

        openai_service = OpenAIService(
            api_key=api_key,
            base_url=base_url,
            model_name=config.model_name,
        )
        models = await openai_service.get_available_models()
        return ModelListResponse(models=models, success=True, message=f"获取到 {len(models)} 个模型")
    except Exception as e:
        return ModelListResponse(models=[], success=False, message=f"获取模型列表失败: {str(e)}")
