# Docker部署与SQLite持久化

当前唯一维护入口：[trialtrust](https://www.modelscope.cn/studios/L666H666Better/trialtrust)，名称“试托·Agent委托前试运行工作台”。GitHub记录开发与CI；魔搭独立Git仓库负责构建发布，推送GitHub不会自动更新魔搭。

## 构建与启动

```bash
docker build -t trialtrust:0.7 .
docker volume create trialtrust-data
docker run --rm -p 7860:7860 -v trialtrust-data:/mnt/workspace/trialtrust trialtrust:0.7
```

Dockerfile锁定Python镜像与依赖，使用非root用户，监听0.0.0.0:7860。生产入口trialtrust.managed默认账号鉴权；TRIALTRUST_MANAGED_STUDIO=1启用魔搭iframe适配，公共Origin及允许Host由托管Secret配置。ms_deploy.json记录Docker与免费CPU资源，不创建第二个空间。

## 数据和密钥

TRIALTRUST_RUNTIME=/mnt/workspace/trialtrust/web：web.sqlite保存账号与历史，子目录保存报告和LangGraph检查点，上层usage.sqlite保存用量。SQLite数据写入平台持久目录，不写入镜像或Git。启动前生成最近3日的一致性私有备份；与原库同盘，不保证平台删除或存储损坏后的恢复。账号与具体持久化边界见[账号文档](accounts.md)。

DASHSCOPE_API_KEY仅供模型后端。ALIPAY_MODELSCOPE_KEY只供本地部署管理，不进入前端或应用公开配置。默认费用估值上限仍为3元/20万tokens，未提高硬件或购买服务。

## 发布验收

正常提交和推送魔搭仓库，调用平台部署后，核对公开HTML及app.js/auth.js/style.css/workbench_tools.js与Git对象一致。Running或HTTP200不代表实际交互通过。

使用tools/deployment_smoke.py --managed-docker完成公开门户上下文下的注册登录及完整离线流程；--account-state必须指向runtime中的私有测试账号文件，用于重新部署后验证同一账号与历史。不得把该文件当作公开证据上传。--live才调用模型，本轮不需要。

应实际验证：未登录拒绝API、注册/登录/退出、恢复码、账号隔离、重命名/删除、刷新、手机布局，以及重新部署后存储标识和历史保留。当前记录见[账号验证](validation-accounts.md)；此前故障与回退记录保留在[历史发布记录](hosting-review.md)。GitHub CI只测试，不自动部署。
