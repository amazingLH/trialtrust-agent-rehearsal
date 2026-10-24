# 魔搭托管、Docker与SQLite持久化

唯一维护空间：[trialtrust](https://www.modelscope.cn/studios/L666H666Better/trialtrust)。GitHub记录开发与CI，魔搭仓库负责源码发布，推送GitHub不会自动更新魔搭。

## 两种启动方式

| 环境 | 框架和入口 | 用途 |
|---|---|---|
| 魔搭创空间（当前） | Docker，Dockerfile | 从master构建项目镜像，启动trialtrust.managed，监听7860 |
| 自行运行容器 | Dockerfile → python -m trialtrust.managed | 独立部署；锁定Python镜像与依赖，非root用户，端口7860 |

README的deployspec.entry_file与ms_deploy.json和控制台框架必须一致。当前魔搭采用Dockerfile；app.py保留为可选Gradio入口。不能把Docker框架参数交给只支持Gradio的studio-launcher。2026-10-20的旧sbuild缓存故障详见发布记录；恢复发布需重新核对实际构建源码，配置保存不代表上线成功。

```bash
docker build -t trialtrust:0.7 .
docker volume create trialtrust-data
docker run --rm -p 7860:7860 -v trialtrust-data:/mnt/workspace/trialtrust trialtrust:0.7
```

Docker和可选Gradio入口共用FastAPI业务，账号鉴权默认开启。/api/workbench提供独立页面以避开Gradio前端资源命名冲突。托管入口设置文件创建权限，固定公共Origin和受信Host，保留跨站iframe会话头兼容。

## 数据和密钥

两种入口均使用TRIALTRUST_RUNTIME=/mnt/workspace/trialtrust/web。web.sqlite保存账号和历史，子目录保存报告及检查点，上层usage.sqlite保存用量；这些文件不写入镜像或Git。启动前生成最近3日的一致性私有备份，与原库同盘。删除、转移创空间前另行备份，不保证平台删除或存储损坏后的恢复。

DASHSCOPE_API_KEY仅供模型后端；ALIPAY_MODELSCOPE_KEY仅用于本地部署管理，不进入前端、源码和日志。资源仍为免费CPU。应用默认不设累计Token和估算费用上限，保留usage.sqlite的历史记录；旧TRIALTRUST_TOKEN_LIMIT、TRIALTRUST_BUDGET_CNY环境变量不再生效。模型调用按服务商账户的免费额度、计费和访问规则执行。

## 发布与验收

开发流程负责修改、测试、源码同步、部署和实际验收；维护者无需手动反复尝试发布。GitHub CI只测试，不直接自动部署。正常推送魔搭master后确认SDK与入口一致，再调用平台发布流程，不强推、不创建备用空间、不删除运行数据。

发布后必须验证公开HTML/JS/CSS与Git对象匹配、未登录拒绝业务接口、测试账号登录、历史保留、一次离线完整流程及真实浏览器手机布局。必要时在私有验收期间验证账号边界，通过后恢复公开访问。不能用所有者凭据访问结果冒充匿名公开验证。

当前Docker入口验收使用tools/deployment_smoke.py --managed-docker；可选原生Gradio入口不加该参数。--account-state必须指向runtime内的私有测试账号文件，以比较storage_id和旧会话；--live才调用真实模型。本轮修复无需付费模型调用。

当前与历史证据分别见[账号验证](validation-accounts.md)、[紧凑流程验证](validation-workflow-ui.md)和[发布记录](hosting-review.md)。

## 版本核验

2026-10-20已恢复公开运行，恢复前的旧工作区故障及当前验收见[恢复记录](hosting-support.md)。使用官方OpenAPI：POST https://modelscope.cn/openapi/v1/studios/L666H666Better/trialtrust/deploy，凭据仅从本机环境读取。构建成功后需等待启动完成，再核对页面；不要在构建成功时立即重复重建。

```bash
python tools/check_hosted_source.py --revision HEAD --output runtime/public-source.json
```

该只读工具对比Git对象中的6份HTML/JS/CSS并检查未登录401；版本不符时退出码非零。公开检查不发送所有者凭据；--private-owner仅供私有检查，不代表已公开。源码一致后再运行完整账号和离线流程验收，测试账号状态始终保存在被Git忽略的runtime内。
