---
inclusion: always
---

# Windows 命令执行规范

## Python 执行路径

在 Windows 上执行 Python 相关命令时：

- **始终使用 `python`** 而非 `python3`
- **禁止使用 `&&`** 连接多条命令。Windows 原生命令分隔符是 `;` 或换行。
  - ❌ `python -m pytest backend/tests/ && python -m mypy backend/`
  - ✅ `python -m pytest backend/tests/ ; python -m mypy backend/`
- 执行目录固定的命令时使用 `cwd` 参数，**禁止使用 `cd`** 切换目录：
  - ❌ `command: "cd backend && python -m pytest"`
  - ✅ `command: "python -m pytest"`, `cwd: "backend"`
- 长命令超时建议设为 `120000ms`（2分钟），以便完整测试套件运行

## Shell 类型

当前环境是 **Windows PowerShell 5.x**（`platform: win32`），不是 bash。执行外部命令时：

- 使用 PowerShell 语法：`Get-ChildItem`、`Remove-Item`、`$env:VAR`（不要用 `%VAR%`、`export`、`grep`、`cat <<EOF`）
- 控制台默认 GBK 编码：Python 输出中文前先设 `$env:PYTHONIOENCODING="utf-8"`，否则会出现 `UnicodeEncodeError` 或乱码
- 管道传中文给 Python（`git diff | python -c ...`）时，在 Python 里用 `sys.stdin.buffer.read().decode('utf-8')` 读取，不要依赖默认编码
- 多行 Python 逻辑写成临时 `.py` 文件执行后删除；不要用 `@'...'@ | python -` 传 here-string（PowerShell 会改写参数导致报错）
- Windows 自带的 `tar` 不支持从 stdin 解包；解包 `git archive` 输出请用 Python `tarfile`
- 路径分隔符：PowerShell 两种都接受，Python 代码中统一用 `/`

## 测试执行

- 运行 pytest：`python -m pytest`
- 运行单个测试文件：`python -m pytest backend/tests/test_file.py`
- 带详细输出：`python -m pytest backend/tests/ -v --tb=short`
- 使用 `;` 而非 `&&` 连接多个测试命令

## 文件操作

- Windows 不区分大小写路径，但代码中应保持一致的大小写
- 路径分隔符统一用 `/`（Python 自动处理）
