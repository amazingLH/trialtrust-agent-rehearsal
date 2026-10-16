# 源码托管、构建与公开部署

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

魔搭远程为`https://modelscope.cn/studios/L666H666Better/trialtrust.git`。推送源码后调用平台部署接口，由平台安装依赖、运行入口并发布到`https://l666h666better-trialtrust.ms.show`。这次没有通过GitHub导入，也没有上传ZIP来部署。

ZIP是独立准备的参赛源工程备份，不能代替平台运行。后续GitHub提交不会自动同步到魔搭；修改应用后，需要将同一经过验证的代码更新到部署仓库，再执行部署和验收。

## 独立Docker入口

```bash
docker build -t trialtrust:0.5 .
docker run --rm -p 7860:7860 trialtrust:0.5
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
| `TRIALTRUST_ALLOWED_HOSTS` | 独立入口或公共网关的Host白名单 |
| `TRIALTRUST_BUDGET_CNY` | 每个应用账本的保守估算费用上限 |
| `TRIALTRUST_TOKEN_LIMIT` | 每个账本的token上限 |

## 验收与版本

2026年10月16日，平台公开状态和无账号API验收通过。部署代码来自此前魔搭Git提交`f9a2b60ed96c4599d9a5befd79b5fd1c5fc3e68f`，此标识保留在原始验收清单；它不是本GitHub仓库的提交号。GitHub公开仓库从同一应用源文件的v0.4快照开始，后续记录独立版本历史。

```bash
python tools/deployment_smoke.py
```

默认检查公开页面所需上下文，不使用所有者SDK密钥或账号登录Cookie；离线检查会创建合成记录并测试审阅/导出。`--live`才调用模型与Embedding；`--owner-gateway`明确切换所有者诊断，不能冒充匿名访问验证。

测试中的审阅接受标记由脚本发送，不代表真实用户评价。远程门户的自动浏览器读取不稳定，因此云端可视化体验仍待人工验收；本地相同托管界面已验证对照、审阅和实际下载。平台Running和健康接口200均不能单独证明全部交互正常。

## 运行维护

当前应用面向受限演示，为单进程状态模型。长期开放前需验证资源休眠、持久目录、模型额度、错误恢复及访问稳定性。免费资源的可用时长以平台为准，不承诺永久在线；多个独立部署的费用账本不会自动合并。

GitHub CI只运行离线检查，不部署魔搭，不读取任何模型密钥，也不会自动提交赛事作品。


v0.5继续使用两个独立Git历史；同步应用源文件后分别正常提交，不强推。Gradio适配另取消外层main额外padding与overflow裁切，保留产品自身footer和手机宽度。新版验收与旧版证据分别记录，不用旧截图证明新部署。
