# 本机作为 VLLM 服务器配置指南

## 场景说明

你的需求：
- **本机**（当前电脑）作为 VLLM 服务器
- **GT_digao 投标程序** 通过 HTTP API 调用本机的 VLLM 服务
- 实现：本地 GPU 运行大模型，投标程序调用 API 生成文档

## 架构

```
[GT_digao 投标程序] --HTTP--> [本机 VLLM 服务]
     端口 3030/9980             端口 8000
          ↓                          ↓
     浏览器/后端                  本机 GPU
```

## 第一步：启动本机 VLLM 服务

### 1. 检查 GPU 和 VLLM 安装

```bash
# 检查 GPU
nvidia-smi

# 检查 VLLM 是否安装
vllm --version

# 如未安装，先安装
pip install vllm
```

### 2. 启动 VLLM 服务（监听所有网络接口）

```bash
# 关键：使用 --host 0.0.0.0 允许外部程序调用
vllm serve Kbenkhaled/Qwen3.5-27B-NVFP4 \
  --host 0.0.0.0 \
  --port 8000 \
  --dtype auto \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.95 \
  --max-num-seqs 256
```

**参数说明**：
- `--host 0.0.0.0`：监听所有网络接口（127.0.0.1 和局域网 IP）
- `--port 8000`：API 端口
- `--max-model-len 32768`：上下文窗口大小
- `--gpu-memory-utilization 0.95`：GPU 内存使用率

### 3. 验证 VLLM 服务

```bash
# 测试本地调用
curl http://127.0.0.1:8000/v1/models

# 测试聊天接口
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Kbenkhaled/Qwen3.5-27B-NVFP4",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": false
  }'
```

## 第二步：配置 GT_digao 投标程序

### 方式一：通过前端配置界面（推荐）

1. **打开 GT_digao 前端**（http://localhost:3030）
2. **进入配置页面**
3. **添加 VLLM 供应商**：
   - 供应商名称：`VLLM 本机服务器`
   - Base URL: `http://127.0.0.1:8000/v1`
   - API Key: `vllm-local`（任意值）
4. **选择模型**：`vllm-local/Kbenkhaled/Qwen3.5-27B-NVFP4`
5. **保存并激活**

### 方式二：直接编辑配置文件

编辑 `~/.gt_audit_helper/user_config.json`：

```json
{
  "providers": {
    "vllm-local": {
      "name": "VLLM 本机服务器",
      "api_key": "vllm-local",
      "base_url": "http://127.0.0.1:8000/v1",
      "created_at": "2026-03-31 14:38"
    }
  },
  "active_provider": "vllm-local",
  "model_name": "vllm-local/Kbenkhaled/Qwen3.5-27B-NVFP4",
  "word_count": 100000
}
```

## 第三步：测试完整流程

### 1. 确保 VLLM 服务运行

```bash
# 检查 VLLM 进程
netstat -an | grep 8000
```

### 2. 在 GT_digao 中测试

1. 打开 GT_digao 前端 http://localhost:3030
2. 创建新项目
3. 选择 VLLM 本机服务器作为模型供应商
4. 尝试生成文档内容
5. 观察是否成功调用 VLLM

## 高级配置

### 1. 多用户并发支持

```bash
vllm serve Kbenkhaled/Qwen3.5-27B-NVFP4 \
  --host 0.0.0.0 \
  --port 8000 \
  --max-num-seqs 512 \
  --max-num-batched-tokens 131072 \
  --gpu-memory-utilization 0.90
```

### 2. Windows 服务配置

创建 `start-vllm.bat`：

```batch
@echo off
cd /d D:\path\to\model
.\venv\Scripts\activate
vllm serve Kbenkhaled/Qwen3.5-27B-NVFP4 --host 0.0.0.0 --port 8000 --dtype auto
pause
```

## 故障排查

### 问题 1：GT_digao 无法连接到 VLLM

**排查**：
```bash
# 1. 检查 VLLM 是否运行
netstat -an | grep 8000

# 2. 测试 API 端点
curl http://127.0.0.1:8000/v1/models

# 3. 检查 GT_digao 配置
type %USERPROFILE%\.gt_audit_helper\user_config.json
```

### 问题 2：GPU 内存不足

**解决**：
```bash
# 降低 GPU 内存使用率
vllm serve ... --gpu-memory-utilization 0.80

# 或减小上下文窗口
vllm serve ... --max-model-len 16384
```

### 问题 3：端口冲突

**解决**：
```bash
# 查找占用 8000 端口的进程
netstat -ano | grep :8000
# 终止进程或修改 VLLM 端口
vllm serve ... --port 8001
```

## 性能优化

### 1. 批处理优化

```bash
vllm serve ... \
  --max-num-seqs 256 \
  --max-num-batched-tokens 65536
```

### 2. 启用连续批处理

```bash
vllm serve ... --enable-chunked-prefill
```

### 3. 监控资源使用

```bash
# 实时监控 GPU
watch -n 1 nvidia-smi
```

## 快速启动脚本

创建 `start-all.bat`：

```batch
@echo off
echo 启动 VLLM 服务...
cd /d D:\path\to\model
.\venv\Scripts\activate
start "VLLM Server" vllm serve Kbenkhaled/Qwen3.5-27B-NVFP4 --host 0.0.0.0 --port 8000 --dtype auto

echo 等待 VLLM 启动...
timeout /t 10 /nobreak

echo 启动 GT_digao...
cd /d D:\GT\GT_digao
.\start.bat
```

## 总结

### 配置要点

1. ✅ **VLLM 服务**：`--host 0.0.0.0` 允许 GT_digao 调用
2. ✅ **GT_digao 配置**：Base URL 设为 `http://127.0.0.1:8000/v1`
3. ✅ **模型选择**：`vllm-local/Kbenkhaled/Qwen3.5-27B-NVFP4`
4. ✅ **测试验证**：确保 API 调用成功

### 优势

- **零网络延迟**：本机调用，速度最快
- **完全控制**：模型、数据、配置全部在自己手中
- **成本最优**：无需支付 API 费用，利用自有 GPU 资源
- **数据隐私**：所有数据不离开本机

### 下一步

1. 启动 VLLM 服务（后台运行）
2. 配置 GT_digao 使用本机 VLLM
3. 开始生成投标文档
