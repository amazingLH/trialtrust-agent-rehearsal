---
deployspec:
  entry_file: Dockerfile
---

# TrialTrust Agent Rehearsal · 试托

**试托是一个让AI先试办、再由你检查的工具。你填好要办的事、数量和预算，让AI在模拟资料中查价格、算费用、提出方案，再查看它有没有漏算费用、超过预算或尝试你没允许的操作，帮助你决定正式使用AI时哪些步骤需要自己把关。**

[![CI](https://github.com/amazingLH/trialtrust-agent-rehearsal/actions/workflows/ci.yml/badge.svg)](https://github.com/amazingLH/trialtrust-agent-rehearsal/actions/workflows/ci.yml)

[在线体验](https://www.modelscope.cn/studios/L666H666Better/trialtrust?mode=full&app_path=%2Fapi%2Fworkbench) · [魔搭创空间](https://www.modelscope.cn/studios/L666H666Better/trialtrust) · [产品设计](docs/product.md) · [系统架构](docs/architecture.md) · [开发过程](docs/development.md) · [复现指南](docs/reproducibility.md)

## 为什么做这个项目？它能帮你解决什么问题？

假设你想让AI帮忙安排一次聚餐、活动或上门服务。在真正让它预约、下单之前，你可能会担心：它有没有把钱算对？会不会漏掉服务费、邮费？价格查不清楚时会不会随口给出一个方案？会不会没经过你同意，就尝试预约或付款？只看AI最后给出的回答，往往看不清这些问题。

试托让你先在模拟场景中试一遍。你先选要办的事，填好人数或数量、服务方式和预算；工具会记录AI查了哪些资料、按什么价格计算、提出了什么方案，以及有没有尝试你没允许的操作。你还可以保持人数和预算不变，再模拟一次涨价或查不到价格的情况，看看它会怎样处理。

**用完后，你能看到这次AI是否算清费用、找到依据、遵守你的限制，以及哪里还需要补充资料或由你确认。** 这些记录帮助你判断本次表现是否符合要求，也方便修改条件后再试、对照前后的结果。

### 举个例子：4个人做陶艺，最多花300元

你在页面中选择“周末陶艺”，人数填4人，选择“到店自取”，总预算填300元。这次只让AI查资料、算费用和提出方案，不让它真的预约或付款。

使用默认模拟价格和免费演示时，会看到两次结果：

1. **先按每人70元试一次。** 4个人一共280元，没有超过300元预算，会生成一份供你检查的方案草稿。
2. **再把每人价格改成80元，其他条件不变。** 4个人就要320元，超过了原来的300元预算。这次不会生成通过费用检查的方案草稿，你可以查看停止的原因和计算过程。

通过这个例子，你可以看懂：费用变化后是否重新算钱、超过预算时是否停下来，以及结果依据是什么。选择真实模型时，则可以用同样的方法观察已接入AI的实际处理过程。

这里的价格可以自行调整，使用的都是模拟资料，不会产生真实订单。免费演示用于熟悉操作；真实模型模式才会调用AI自主处理任务。试运行通过只说明这一次表现符合条件，不能保证AI在真实网站上一定安全。

![试托账号入口：原创太空小托与登录注册](assets/v0.7/login-cloud.png)

> 托管状态（2026-10-20）：已恢复公开运行。线上6份页面资源与GitHub源码一致，未登录业务接口返回401；原有测试账号、SQLite及历史会话保留，离线对照、审阅和导出已通过。详见[恢复记录](docs/hosting-support.md)。

当前版本 **v0.7**：[四步使用教程](docs/usage.md) · [五项可信 Skills](docs/skills.md)。首页截图来自公开魔搭门户；桌面、手机、API与各版真实模型证据分别记录。

> v0.7新增独立登录注册入口与账号隔离，SQLite运行数据不进入镜像或Git。公开登录、账号隔离、云端深度重启数据保留及手机布局已验收；详情见[账号验证记录](docs/validation-accounts.md)，旧版本证据保留原版本标记。

当前托管入口为 **`L666H666Better/trialtrust`**，展示名称为“试托·Agent委托前试运行工作台”。

## 账号与工作台能力

- 账号入口：用户名/密码注册、bcrypt哈希、登录退出、密码修改和一次性恢复码；业务接口强制鉴权。
- SQLite持久化：账号归属的历史记录、同一浏览器注册绑定、启动前私有备份。详情见[账号与存储](docs/accounts.md)。
- 场景与条件：4大类、30个子分类、291个具体事项，支持两级菜单选择、示例与个人模板、模拟费用预览。
- 试验控制：显式选择执行者、检索方式、自动对照或手动测试，设置改变后重新确认。
- 证据与比较：实际调用轨迹、结果检查清单、会话内跨轮对照与人工审阅导出。
- 会话管理：新建、继续、持久化重命名和带确认的逻辑删除。

## 工作流

```mermaid
flowchart LR
    U[用户检查替身与未建模要求] --> M[确认不可变委托]
    M --> D[设计 Agent 选择一个变化]
    D --> B[原始条件 独立执行]
    D --> C[变化条件 独立执行]
    R[现行资料过滤 BM25 向量 RRF] --> B
    R --> C
    B --> V[独立费用 证据 授权核验]
    C --> V
    V --> A[只读审阅 Agent]
    A --> F[逐条核对事实值与类型]
    F --> H[人工审阅 导出记录]
```

原始和变化执行目前按顺序运行，状态相互隔离；图中的分支表示独立执行条件，不表示已实现并行调度。

## 已实现的核心能力

| 能力 | 实现 | 代码入口 |
|---|---|---|
| 真实模型与工具选择 | 百炼 `deepseek-v4.1-flash` 免费额度耗尽时自动切换 `qwen3.7-flash`；Function Calling、严格参数验证、有限轮次 | [provider.py](trialtrust/provider.py) |
| 多角色编排 | 设计、执行、审阅三种职责；同一执行器分别试做原始和变化条件 | [suite.py](trialtrust/suite.py) |
| Advanced RAG | 范围/现行版本预过滤、规则分面扩展、BM25＋真实稠密向量、两级RRF | [retrieval.py](trialtrust/retrieval.py) |
| 真实Embedding | `qwen3.7-text-embedding-flash`，内容与版本绑定缓存，维度/数值验证 | [provider.py](trialtrust/provider.py) |
| 独立核验 | Pydantic、Decimal、Z3；金额、数量、方式、附加费与已观测证据 | [sandbox.py](trialtrust/sandbox.py) |
| Harness | 自有合成服务环境、涨价/缺证据/注入/超时条件、行为与故障分别记录 | [scenarios.py](trialtrust/scenarios.py) |
| 状态与恢复 | LangGraph、SQLite Checkpointer、人审Interrupt、父图恢复时复用子图 | [cli.py](trialtrust/cli.py)、[suite.py](trialtrust/suite.py) |
| MCP | 可独立连接的两个只读stdio工具；主网页内部工具调用不经过该服务 | [mcp_server.py](trialtrust/mcp_server.py) |
| 应用内 Skills | 可信白名单、按需说明加载、JSON Schema、权限闸门、调用摘要与检查点恢复 | [skill_runtime.py](trialtrust/skill_runtime.py)、[技能说明](docs/skills.md) |
| 分层需求目录 | 景点、美食、旅行、生活分别有6、7、8、9个子分类，共291个具体事项；也可直接写目录外的需求，补齐条件后进入自定义试运行 | [catalog.py](trialtrust/catalog.py)、[catalog_groups.py](trialtrust/catalog_groups.py)、[request_analysis.py](trialtrust/request_analysis.py) |
| 服务与预算 | FastAPI、Gradio托管适配、匿名会话归属、同源校验、请求前费用预留 | [webapp.py](trialtrust/webapp.py)、[app.py](app.py) |

完整能力清单与尚未实现的部分见[架构文档](docs/architecture.md)。v0.5已实现应用内可信 Skills 运行时；尚无A2A、神经重排或任意第三方Agent接入。Skills 与只读 MCP 的不同职责见技能文档。

## 快速开始：无需密钥的离线模式

要求Python 3.11。以下命令在项目根目录运行：

```bash
git clone https://github.com/amazingLH/trialtrust-agent-rehearsal.git
cd trialtrust-agent-rehearsal
python -m venv .venv
```

激活环境：Windows PowerShell使用 `.\.venv\Scripts\Activate.ps1`；Linux/macOS使用 `source .venv/bin/activate`。然后：

```bash
python -m pip install -r requirements.lock
python -m uvicorn trialtrust.webapp:app --host 127.0.0.1 --port 8774
```

打开 <http://127.0.0.1:8774/>。选择离线示例、核对条件，再运行一次或一组对照。真实模型默认关闭，离线模式不消耗模型额度。

```bash
python -m pytest -q
python -m trialtrust.evaluate
python tools/verify_evidence.py
```

真实模型、语义检索、MCP客户端配置、Docker和魔搭部署见[复现指南](docs/reproducibility.md)与[部署说明](docs/deployment.md)。

## 验证证据

[v0.5.1会话与布局验证](docs/validation-v0.5.1.md)包含公开页面两轮继续操作、全屏/手机截图、静态资源指纹和一次跨部署匿名会话连续性检查。

- v0.5.1 Windows托管环境120项Python测试和3项Node测试通过；新增会话分组、owner隔离、旧库迁移、重启延续、过期及同源检查。新界面支持当前/历史会话、明确沿用条件和统一操作指引。

- v0.5 Windows开发环境：113项测试通过（新增70项，含12领域×5条件矩阵、技能权限、未知需求与确认拒绝）。
- v0.5 干净Linux核心Docker：112项通过、1项Gradio托管测试跳过。
- v0.5真实博物馆对照、真实Embedding、五项技能路由与未知需求分析已有[v0.5真实调用记录](docs/validation-v0.5.md)。
- v0.5云端无账号API完成目录、Skills、确认拒绝、未知需求、成对运行、审阅与导出；真实模型/Embedding的自助餐170元对照证据缺失无草稿有原始记录。公开门户桌面与390×844手机、取消确认、对照、实际技能和审阅保存已实操。
- 3项Node回归验证可信父窗口、消息边界及仅限布局的用途；CI在核心与托管两个矩阵均运行。
- 40条方案探针、24条检索问题及检索消融结果保存在[evals](evals/)。这些是AI编写的开发回归，尚无独立人工金标或真实用户研究。

[评测方法与反例](docs/evaluation.md)解释指标口径和失败案例；[v0.5验收清单](evals/results/deployment-v0.5.json)区分接口、实际浏览器和模型证据；v0.4原始记录保留作历史。云端原生下载尚未取得完成回执，页面提供同会话鉴权的只读JSON查看/复制入口（最终云端已实际展开完整报告）。自动测试写入的审阅标记不是实际用户评价。

## 当前边界

目录覆盖景点、美食、旅行、生活四类共291个事项，也接受目录外的自定义需求。开启大模型分析后，会从原话中整理想做的事、数量、服务方式和预算，只追问缺少的条件，并给出可补填的输入示例；补齐后可进入第二步，自行填写本次模拟价格。地点、时间和具体要求随条件保留，供AI查阅，但不核验真实商家、库存或可预约时间，也不执行预约、支付或通讯。格式替换不能保证完全匿名化。

检索对语料不支持的问题仍可能返回文档，尚无可靠的无答案校准。单次成对执行不能证明统计因果、模型排名或整体安全；额外角色是否改善质量也尚未完成对照验证。应用为单进程设计，免费托管需要持续维护。

## 文档导航

| 文档 | 内容 |
|---|---|
| [使用教程](docs/usage.md) | 四步操作、多轮会话、自定义需求与确认规则 |
| [Skills运行时](docs/skills.md) | 技能发现、加载、权限、真实执行、证据与限制 |
| [产品设计](docs/product.md) | 创意来源、目标用户、场景、差异与价值假设 |
| [系统架构](docs/architecture.md) | 状态流、Agent权限、工具、RAG、核验、恢复与技术取舍 |
| [开发过程](docs/development.md) | 从场景定义到云端验收的七个工程阶段与复现步骤 |
| [复现指南](docs/reproducibility.md) | 环境、运行命令、模型配置、MCP接入与常见问题 |
| [评测记录](docs/evaluation.md) | 数据来源、消融、指标定义、反例与原始记录 |
| [部署说明](docs/deployment.md) | GitHub、Git与魔搭的关系，构建入口和服务维护 |
| [演示与试用](docs/demo.md) | 可操作案例、预期行为、真实反馈记录模板 |
| [变更记录](CHANGELOG.md) | 版本能力和发布范围 |

开发与文档整理使用AI辅助；合成回归样本的来源和验证限制在评测文档中披露。项目当前未指定开源许可证；第三方依赖、引用与素材的说明见[NOTICE](NOTICE.md)。
