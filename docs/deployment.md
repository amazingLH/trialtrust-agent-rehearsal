# 源码托管、构建与公开部署

## 发布状态补记（2026-10-19）

代码版本v0.6.1已通过本地回归及一次公开交互验收；随后平台自动回退了6个文件，提交信息为“sensitive file content or message”。平台没有给出具体触发原因。公开运行实例在最新检查中仍匹配v0.6.1，但远端源码已不同，**不能据此声明稳定部署完成，也不要直接重建**。

本次未覆盖平台回退，未重复提交被拒代码。历史截图和API记录仅证明当时的运行结果。当前状态见[发布状态记录](../evals/results/deployment-status-v0.6.1.json)，复核信息与本地使用方式见[发布复核说明](hosting-review.md)。

## 当前入口与历史部署

对外链接、仓库主页和新部署统一使用[trialtrust-workbench](https://www.modelscope.cn/studios/L666H666Better/trialtrust-workbench)。原`trialtrust`空间仅保留历史部署及旧匿名记录，不再推荐使用。删除旧空间前，应先导出需要保留的报告，并确认新版已完成平台复核及稳定重部署；删除空间不会把历史数据迁移到新版。

## Git、GitHub和魔搭各自负责什么

Git是本地版本管理工具；GitHub和魔搭都可以提供Git远程仓库。GitHub保存项目代码、文档与变更记录，魔搭创空间保存用于构建应用的代码并提供运行资源。二者不需要先后依赖。

当前公开演示的部署链路是：

```mermaid
flowchart LR
    L[本地应用工程] -->|Git push| M[魔搭创空间Git仓库]
    M --> B[平台构建安装依赖]
    B --> E[app.py Gradio与FastAPI]
    E --> U[公开体验地址]
    L --> P[整理公开文档与源代码快照]
    P -->|Git push| G[GitHub仓库与CI]
```

魔搭远程为`https://modelscope.cn/studios/L666H666Better/trialtrust-workbench.git`。推送源码后调用平台部署接口，由平台安装依赖、运行入口并发布到`https://l666h666better-trialtrust-workbench.ms.show`。这次没有通过GitHub导入，也没有上传ZIP来部署。

GitHub提交不会自动同步到魔搭；修改应用后，需要将同一经过验证的代码更新到部署仓库，再执行部署和验收。

## 独立Docker入口

```bash
docker build -t trialtrust:0.6.1 .
docker run --rm -p 7860:7860 trialtrust:0.6.1
```

默认离线。核心入口为`trialtrust.webapp:app`，容器端口7860。需要保留状态时挂载`/mnt/workspace/trialtrust`；需要真实模型时通过托管Secret或安全的环境注入方式配置，不把密钥写进镜像。

## 魔搭托管入口

- `app.py`为Gradio 6.2入口，`requirements.txt`包含托管依赖。
- `ms_deploy.json`记录SDK、基础镜像、端口与所选CPU资源。
- 平台的公开Gradio前端读取`/config`，因此配置必须包含实际工作台，而不是只挂载状态页。
- 托管适配避免独立网页的`/assets`路由遮挡Gradio资源。
- 平台每次部署可能改变内部FC域名；适配接受观察到的平台内部后缀，但外部Origin固定为应用域名，不以任意转发头决定可信来源。
- 跨站iframe可能阻止Strict Cookie，因此托管版提供同源匿名会话能力令牌；JSON导出通过同一请求通道生成文件。

密钥放在创空间Secret；`DASHSCOPE_API_KEY`供模型使用。`ALIPAY_MODELSCOPE_KEY`仅用于运营者本地管理/诊断，不需要交给普通访客，也不应放进前端。

常用服务端变量：

| 变量 | 用途 |
|---|---|
| `TRIALTRUST_RUNTIME` | 持久化运行目录 |
| `TRIALTRUST_ENABLE_LIVE` | 是否开放真实模型模式 |
| `TRIALTRUST_PUBLIC_ORIGIN` | 明确的公开HTTPS来源 |
| `TRIALTRUST_STUDIO_URL` | 当前创空间页面地址，保持全屏链接与部署一致 |
| `TRIALTRUST_ALLOWED_HOSTS` | 独立入口或公共网关的Host白名单 |
| `TRIALTRUST_BUDGET_CNY` | 每个应用账本的保守估算费用上限 |
| `TRIALTRUST_TOKEN_LIMIT` | 每个账本的token上限 |

## 验收与版本

以下为v0.4历史部署说明。2026年10月16日，平台公开状态和无账号API验收通过。部署代码来自此前魔搭Git提交`f9a2b60ed96c4599d9a5befd79b5fd1c5fc3e68f`，此标识保留在原始验收清单；它不是本GitHub仓库的提交号。GitHub公开仓库从同一应用源文件的v0.4快照开始，后续记录独立版本历史。

```bash
python tools/deployment_smoke.py
```

默认检查公开页面所需上下文，不使用所有者SDK密钥或账号登录Cookie；离线检查会创建合成记录并测试审阅/导出。`--live`才调用模型与Embedding；`--owner-gateway`明确切换所有者诊断，不能冒充匿名访问验证。

测试中的审阅标记由自动化发送，不代表真实用户评价。v0.5已在公开门户实际验证桌面、390×844手机布局、取消确认拦截、自助餐170元对照涨价无草稿、Skills事件和审阅保存。云端原生下载尚未捕获文件完成回执；本地下载和云端导出接口已通过，因此新增同会话鉴权的只读JSON查看/复制入口（最终云端已实际展开完整报告）。平台Running和健康接口200均不能单独证明全部交互正常。

## 运行维护

当前应用面向受限演示，为单进程状态模型。长期开放前需验证资源休眠、持久目录、模型额度、错误恢复及访问稳定性。免费资源的可用时长以平台为准，不承诺永久在线；多个独立部署的费用账本不会自动合并。

GitHub CI只运行离线检查，不部署魔搭，也不读取任何模型密钥。


v0.5继续使用两个独立Git历史；同步应用源文件后分别正常提交，不强推。Gradio适配另取消外层main额外padding与overflow裁切，保留产品自身footer和手机宽度。新版验收与旧版证据分别记录，不用旧截图证明新部署。


## 轻量工作台入口

推荐体验入口为 `https://l666h666better-trialtrust-workbench.ms.show/api/workbench`，与Gradio入口共用同一HTML、CSS、JS、匿名会话和费用账本，资源位于独立的`/api/workbench-assets/`，避免Gradio资源路径冲突。

浏览器实测表明：魔搭会将该地址转到官方门户，保留`app_path`，再通过iframe显示，所以不能把接口返回200当作绕过门户的证明。托管版仅允许自身和两个魔搭官方域名嵌入，轻量页面保留同源脚本、样式、连接的严格CSP；独立Docker版仍禁止外部嵌入。会话和Origin校验保持一致。

原Gradio入口和根`/config`继续提供。门户缩放观察与自动化兼容性单独记录，实际显示与点击结果见[新版验证记录](validation-v0.5.md)。

自有`portal_viewport.js`只接收实际父窗口、官方魔搭域名或同源父窗口的iframe-resizer初始化和有界尺寸信息，再用CSS容器查询排版。不会接收任务或执行命令，不发送条件文本、凭据；不加载第三方运行代码。来源、消息长度、尺寸和布局用途有3项Node回归。保留早期被裁切的失败截图，不能用它冒充已通过的手机效果。


## v0.6.1 发布入口

当前部署仓库为`trialtrust-workbench`。此前`trialtrust`多次重建仍返回旧快照，资源字节校验拦截了这类假阳性，因此建立独立默认CPU部署入口，原空间和匿名记录保留。两处数据不自动迁移；浏览器模板也按站点保存。代码主仓库仍是同一个GitHub项目。

公共网关明确拒绝PATCH和DELETE，会话操作使用同源POST路径`/api/conversations/{id}/rename`与`/api/conversations/{id}/delete`；删除必须传严格布尔确认。标准方法继续供独立服务使用，所有入口共用身份和运行中校验。

发布验收需匹配实际`app.js`、`style.css`、`workbench_tools.js`，并实际测试页面与API。单独Running或HTTP200不足以确认部署正确。详情见[v0.6验证记录](validation-v0.6.md)。
