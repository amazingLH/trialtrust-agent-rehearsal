# 魔搭构建工作区异常排障材料（2026-10-20）

空间：L666H666Better/trialtrust。保留同一个空间，未删除、改名或创建替代空间。为避免旧代码误运行，当前临时非公开并已请求停止。免费CPU硬件未升级；修复过程未调用付费模型。

## 可复现的问题

远端master包含当前源码，Dockerfile存在且以python:3.11-slim开始；README的deployspec.entry_file= Dockerfile，SDK=docker。代码已通过本地回归与GitHub CI。

2026-10-20 10:50:06（北京时间）构建日志：

```text
input branch is master and currentBranch is sbuild-369303-1792374764
input branch not equal current branch: git fetch origin master
```

随后工作区仍构建旧Gradio启动镜像，镜像提交为6cb447009de4e95665f7ec3e786e046ff65a220f；构建时master应用目标已是cb718e26ab290bf9cc2c6caa3369cf611d7fd272。运行日志：

```text
[studio-launcher] config error: unsupported STUDIO_SDK_TYPE: "docker"
```

## 已排除与尝试

- 已核对远端master的Dockerfile、app.py和入口元数据，文件确实存在。
- 普通重新部署、深度重启、完整停止后启动、保存框架设置均复现。
- 通过平台文件编辑接口正常提交入口文件后重新部署，仍观察到旧工作区。
- 改用原生Gradio启动可到Running，但公开应用资产仍非当前源码，旧程序没有账号入口，且写历史时出现table conversations has 6 columns but 5 values were supplied。该版本未恢复公开。
- 原生Gradio适配器在当前源码中的默认鉴权、账号登录和应用重建后的历史保留已有独立回归通过；该SQL错误来自旧部署，不能通过删除现有数据库解决。

## 请求平台协助

请清理本空间在构建节点的Git工作区缓存，并核对“fetch后未checkout/reset到目标ref”的处理。请保证实际构建上下文来自目标master提交；不只是更新展示的提交号。请保留/mnt/workspace持久化目录和现有数据库，不要通过删除空间重建处理。

处理后需核对构建日志、公开HTML/JS/CSS、未登录业务请求401、旧测试账号登录和同一storage_id/历史保留。只有这些通过，才恢复公开访问。

本材料不含API密钥、密码、恢复码或用户数据，可以转交官方排障；尚未发送给任何第三方。[结构化记录](../evals/results/deployment-recovery-2026-10-20.json)。
