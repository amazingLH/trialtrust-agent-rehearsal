# 本地运行、真实模型与MCP接入

## 环境与依赖

核心环境使用Python 3.11和`requirements.lock`。以下路径均相对项目根目录；建议使用独立虚拟环境。

```bash
python -m venv .venv
```

Windows PowerShell激活：

```powershell
.\.venv\Scripts\Activate.ps1
```

Linux/macOS激活：

```bash
source .venv/bin/activate
```

安装、测试和运行：

```bash
python -m pip install -r requirements.lock
python -m pytest -q
python -m uvicorn trialtrust.webapp:app --host 127.0.0.1 --port 8774
```

打开 <http://127.0.0.1:8774/>，先注册用户名/密码并保存恢复码，再进入工作台。核心依赖不包含Gradio，托管测试会跳过；若需要托管入口，另外安装`requirements.txt`，完整测试会包含该项。

```bash
python -m pip install -r requirements.txt
python -m pytest -q
python -m uvicorn app:create_studio_app --factory --host 127.0.0.1 --port 8775
```

独立入口在8774、托管适配入口在8775，避免同时启动时端口冲突。数据默认写入忽略目录`runtime/`，不要将运行数据库提交到仓库。

## 离线运行与开发回归

```bash
python -m trialtrust.cli
python -m trialtrust.evaluate
python tools/verify_evidence.py
```

默认CLI运行预编程行为并停在人审状态，不会调用模型；不是对真实模型质量的测试。评测默认只跑方案核验和词法检索，输出到`runtime/`。原始发布记录放在`evals/results/`，新运行不应覆盖历史证据。

## 启用真实模型

在服务进程的环境中设置`DASHSCOPE_API_KEY`与`TRIALTRUST_ENABLE_LIVE=1`，再启动服务。不要将实际值写入代码、命令历史、仓库或客户端。程序不会自动从任意`.env`文件加载凭据。

Windows可以通过系统环境变量设置界面配置，然后重新打开终端；代码也支持读取同名用户/机器环境变量。Linux/macOS可在交互终端中读取密钥，避免把值写进命令文本：

```bash
read -s -p 'DASHSCOPE_API_KEY: ' DASHSCOPE_API_KEY
export DASHSCOPE_API_KEY
export TRIALTRUST_ENABLE_LIVE=1
python -m uvicorn trialtrust.webapp:app --host 127.0.0.1 --port 8774
```

在页面明确选择真实模型，再按需勾选语义检索。聊天先用`deepseek-v4.1-flash`，收到明确的免费额度耗尽错误后，将同一请求自动交给`qwen3.7-flash`继续处理。向量模型仍为`qwen3.7-text-embedding-flash`，百炼地域/权限需与模型可用性匹配。

自定义需求的确认项包括事项、数量与单位、服务方式、预算和时间；没有时间要求可明确填写“时间不限”。时间缺失由程序统一检查，每次只取当前原文，不沿用上一次分析的值，也不依赖模型是否主动提出缺项。

模型返回先由`brief_parser.py`整理可兼容的格式差异（附带单位、附加说明、空数组、数字字符串、JSON代码框等），再经过原文引用与必填条件校验。整理不会补造事实或修改授权；无法读取的结果停止确认，只向页面返回简短中文提示。输入接口和执行工具仍使用严格参数验证。

补充示例用自然话补齐关键条件，保留已经识别的预算、人数和时间，不再重复附加字段清单。显示前进行本地完整性与预算一致性检查，避免复制后再逐个追问。多个不同预算会要求确认；示例不会直接成为实际条件，需用户核对并重新提交。

要在免费额度耗尽时切换，请在百炼开启DeepSeek的“免费额度用完即停”，让服务返回`403 / AllocationQuota.FreeTierOnly`；Qwen保持按量付费可用（关闭该开关，或模型不支持开启）。若DeepSeek的开关关闭，服务商会直接为DeepSeek按量计费，应用不能从成功响应判断免费额度是否用完。额度由服务商管理，不按本地累计Token猜测。

切换后在原`usage.sqlite`中保存模型选择，新会话和服务重启后继续使用Qwen；只保存凭据摘要，不保存密钥。更换API Key不会继承旧Key的切换状态。核验结果与导出记录包含实际调用的模型。只对明确的免费额度耗尽进行一次切换，鉴权失败、网络超时和一般限流不会触发重复调用。Qwen兼容Function Calling；切换保留原始消息、工具参数、数量、预算和授权，不重放已执行的工具动作。

模型能力与价格见[Qwen3.7-Flash官方文档](https://help.aliyun.com/zh/model-studio/qwen3-7-flash)，额度规则见[百炼免费额度说明](https://help.aliyun.com/zh/model-studio/new-free-quota)。用量估值按支持模型的最高输出费率保守记录，不作为账户账单；应用默认无累计Token或金额上限。

显式真实向量消融：

```bash
python -m trialtrust.evaluate --dense --output runtime/evaluation-dense.json
```

这会访问百炼、消耗额度；相同内容会复用本地缓存。应用默认不设累计Token或估算费用上限，旧的`TRIALTRUST_BUDGET_CNY`、`TRIALTRUST_TOKEN_LIMIT`环境变量不再阻断调用。账本保留历史和本次的实测或预留用量，但不读取免费余额或实际出账。隔离评测可通过TokenLedger的显式构造器参数设置独立上限；生产入口不传入这些参数。

## MCP stdio服务

启动命令：

```bash
python -m trialtrust.mcp_server
```

stdio模式等待客户端通过协议通信，终端没有普通聊天界面属于正常现象。服务有两个工具：

| 工具 | 参数与用途 |
|---|---|
| `search_demo_terms` | `query`和可选`domain`，检索当前合成领域资料 |
| `check_demo_plan` | 金额、资料ID、领域、数量、方式及预算，核验方案；不创建草稿或真实操作 |

支持`pottery`、`cleaning`；清洗应使用`fulfillment="onsite"`。示例核验参数：

```json
{
  "total_yuan": 210,
  "source_ids": ["ac-price-v2", "ac-cancel-v2"],
  "domain": "cleaning",
  "quantity": 2,
  "fulfillment": "onsite",
  "budget_yuan": 220
}
```

工具的实际返回结果决定是否通过，不要把这个例子当预先保证。按支持本地stdio的客户端配置格式填写，例如：

```json
{
  "mcpServers": {
    "trialtrust": {
      "command": "C:/path/to/trialtrust/.venv/Scripts/python.exe",
      "args": ["-m", "trialtrust.mcp_server"],
      "cwd": "C:/path/to/trialtrust"
    }
  }
}
```

替换为实际的绝对路径；Linux/macOS使用虚拟环境的`.venv/bin/python`。不同客户端可能使用不同配置结构，`cwd`与解释器路径必须指向同一项目环境。协议验证：

```bash
python -m pytest tests/test_mcp_protocol.py -q
```

## 常见问题

- 找不到模块：确认在仓库根目录、使用同一虚拟环境，检查依赖安装是否成功。
- 真实模式不可选：启动进程未设置`TRIALTRUST_ENABLE_LIVE=1`，修改环境后需重启。
- 模型失败：先检查服务商账号的模型权限、地域和额度；应用不会把提供商完整错误或密钥传给浏览器。
- 预算停止：检查运行报告中的估算用量和账本范围，不要把免费额度未知当作消费为0。
- 浏览器历史不见：匿名会话有期限，且托管端可能按标签页隔离；已导出的JSON可用于保留记录。
- 测试跳过Gradio：核心安装路径的预期行为，不等于托管集成测试已经通过。
