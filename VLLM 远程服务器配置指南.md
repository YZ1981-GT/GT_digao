# VLLM 远程服务器配置指南

## 概述

本指南详细说明如何在**远程服务器**上部署 VLLM 服务，并让本地 GT_digao 投标程序通过 HTTP API 调用远程 VLLM，实现分布式 AI 推理。

## 架构设计

```
┌────────────────────────────────────────────────┐
│  本地电脑 (你的工作站)                          │
│  ┌──────────────────────────────────────────┐  │
│  │ GT_digao 投标程序                         │  │
│  │ 前端：http://localhost:3030               │  │
│  │ 后端：http://localhost:9980               │  │
│  └──────────────┬───────────────────────────┘  │
│                   │                              │
│                   │ HTTP/HTTPS API 调用          │
│                   ↓                              │
└───────────────────┼──────────────────────────────┘
                     │
                     │ Internet / 内网
                     │
                     ↓
┌────────────────────────────────────────────────┐
│  远程服务器 (GPU 服务器)                          │
│  ┌──────────────────────────────────────────┐  │
│  │ VLLM 服务                                  │  │
│  │ 端口：8000                                 │  │
│  │ 模型：Kbenkhaled/Qwen3.5-27B-NVFP4        │  │
│  │ GPU: NVIDIA A100 / V100 / RTX 4090 等      │  │
│  └──────────────────────────────────────────┘  │
└────────────────────────────────────────────────┘
```

## 第一部分：远程服务器准备

### 1.1 服务器环境要求

**硬件要求**：
- GPU：NVIDIA GPU（推荐 A100/V100/RTX 4090 等）
- 显存：至少 16GB（27B 模型推荐 24GB+）
- 内存：32GB+
- 存储：100GB+（模型文件 + 日志）

**软件要求**：
- 操作系统：Ubuntu 20.04+ / Windows 10+
- Python：3.10+
- CUDA：12.1+
- 驱动：最新 NVIDIA 驱动

### 1.2 安装 VLLM

**Linux 环境**：

```bash
# 创建虚拟环境
python3 -m venv vllm_env
source vllm_env/bin/activate

# 安装 VLLM
pip install vllm

# 验证安装
vllm --version
```

**Windows 环境**：

```powershell
# 创建虚拟环境
python -m venv vllm_env
.\vllm_env\Scripts\activate

# 安装 VLLM
pip install vllm

# 验证安装
vllm --version
```

### 1.3 下载模型

**方法一：使用 huggingface-cli（推荐）**

```bash
# 安装 huggingface_hub
pip install huggingface_hub

# 下载模型到指定目录
huggingface-cli download Kbenkhaled/Qwen3.5-27B-NVFP4 \
  --local-dir /models/Qwen3.5-27B-NVFP4
```

### 1.4 启动 VLLM 服务

**基础启动命令**：

```bash
# 关键：使用 --host 0.0.0.0 允许远程连接
vllm serve /models/Qwen3.5-27B-NVFP4 \
  --host 0.0.0.0 \
  --port 8000 \
  --dtype auto \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.95 \
  --max-num-seqs 256
```

**参数详解**：

| 参数 | 说明 | 推荐值 |
|------|------|--------|
| `--host 0.0.0.0` | 监听所有网络接口 | 必须 |
| `--port 8000` | API 端口 | 8000 |
| `--dtype auto` | 自动选择精度 | auto |
| `--max-model-len` | 上下文窗口 | 32768 |
| `--gpu-memory-utilization` | GPU 内存使用率 | 0.90-0.95 |
| `--max-num-seqs` | 最大并发序列数 | 256-512 |

## 第二部分：网络配置

### 2.1 防火墙配置

**Linux (Ubuntu/Debian)**：

```bash
# 使用 ufw
sudo ufw allow 8000/tcp
sudo ufw status
```

**Windows**：

```powershell
# 创建防火墙规则
New-NetFirewallRule -DisplayName "VLLM API" \
  -Direction Inbound -LocalPort 8000 \
  -Protocol TCP -Action Allow
```

### 2.2 云服务商安全组配置

**阿里云/腾讯云/AWS**：
- 添加入站规则
- 协议：TCP
- 端口：8000
- 源：0.0.0.0/0 或指定你的 IP

## 第三部分：GT_digao 配置

### 3.1 通过前端界面配置

1. **打开 GT_digao 前端**：http://localhost:3030
2. **进入配置页面**
3. **添加远程 VLLM 供应商**：
   - 供应商名称：`VLLM 远程服务器`
   - Base URL: `http://远程 IP:8000/v1` 或 `https://域名/v1`
   - API Key: `vllm-remote`（任意值）
4. **选择模型**：`vllm-local/Kbenkhaled/Qwen3.5-27B-NVFP4`

### 3.2 直接编辑配置文件

编辑 `~/.gt_audit_helper/user_config.json`：

```json
{
  "providers": {
    "vllm-remote": {
      "name": "VLLM 远程服务器",
      "api_key": "vllm-remote",
      "base_url": "http://远程 IP:8000/v1",
      "created_at": "2026-03-31 14:38"
    }
  },
  "active_provider": "vllm-remote",
  "model_name": "vllm-local/Kbenkhaled/Qwen3.5-27B-NVFP4",
  "word_count": 100000
}
```

## 第四部分：测试与验证

### 4.1 测试 VLLM API

```bash
# 测试模型列表
curl http://远程 IP:8000/v1/models

# 测试聊天接口
curl http://远程 IP:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Kbenkhaled/Qwen3.5-27B-NVFP4",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": false
  }'
```

### 4.2 测试 GT_digao 集成

1. **打开 GT_digao**：http://localhost:3030
2. **选择远程 VLLM 供应商**
3. **生成文档内容**
4. **观察生成速度和结果**

## 第五部分：故障排查

### 问题 1：无法连接到远程 VLLM

**排查步骤**：
```bash
# 1. 检查 VLLM 服务状态
ssh user@remote-server "systemctl status vllm"

# 2. 测试网络连通性
telnet 远程 IP 8000

# 3. 检查防火墙和安全组
```

### 问题 2：GPU 内存不足

**解决**：
```bash
# 降低 GPU 内存使用率
vllm serve ... --gpu-memory-utilization 0.80

# 或减小上下文窗口
vllm serve ... --max-model-len 16384
```

## 快速部署脚本

创建 `deploy-vllm.sh`：

```bash
#!/bin/bash
MODEL_PATH="/models/Qwen3.5-27B-NVFP4"
PORT=8000

# 启动 VLLM
nohup vllm serve $MODEL_PATH \
  --host 0.0.0.0 \
  --port $PORT \
  --dtype auto \
  > /var/log/vllm.log 2>&1 &

echo "VLLM 服务运行在 http://0.0.0.0:$PORT/v1"
```

## 总结

### 配置检查清单

- [ ] 远程服务器 GPU 环境准备
- [ ] VLLM 安装和模型下载
- [ ] VLLM 服务启动（--host 0.0.0.0）
- [ ] 防火墙和安全组配置
- [ ] GT_digao 配置远程 VLLM 供应商
- [ ] 测试 API 连接

### 关键要点

1. **网络配置**：`--host 0.0.0.0` 允许远程调用
2. **GT_digao 配置**：Base URL 指向远程 VLLM
3. **模型选择**：`vllm-local/Kbenkhaled/Qwen3.5-27B-NVFP4`
