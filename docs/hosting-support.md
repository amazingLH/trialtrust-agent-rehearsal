# 魔搭构建工作区异常排障材料（2026-10-20）

空间：L666H666Better/trialtrust。保留同一个空间，未删除、改名或创建替代空间。排障期间为避免旧代码误运行，曾临时非公开并停止；现已恢复公开运行。免费CPU硬件未升级；修复过程未调用付费模型。

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

## 平台自动审核回退（补充）

远端新增b039a50和f3949aa，自动回退docs/deployment.md和ms_deploy.json，原因文本为sensitive file content or message，未提供具体触发项。已保留并接受这两次回退，没有强推或重交被回退内容。按平台保留的Gradio 6.2.0配置，将入口重新对齐app.py。以上Docker日志是故障发生时的配置；当前保留原生Gradio方案待构建节点正确取到最新源码后再验收。请平台同时说明这两个文件的触发原因与允许的配置更新方式。

## 14:30 续查的新证据

2026-10-20 北京时间14:30恢复排查，目标源码仍是0c50004fa507e12d30d7e7f7cafb6354fa5ac5aa。当前源码和接受的配置没有被重新覆盖。

| 构建开始 | 选择框架 | 输入分支 | 实际工作区/镜像提交 | 结果 |
|---|---|---|---|---|
| 14:31:48 | Gradio 6.2.0 | sbuild-369303-1792477902 | master / 42c89cff | 镜像为旧Docker应用，/config返回404，未恢复公开 |
| 14:35:56 | Docker（控制台设置，未重传被回退文件） | master | sbuild-369303-1792203728 / ca5e2305 | 旧studio-launcher不支持docker，启动失败 |
| 14:40:05 | Docker / 深度重启 | master | sbuild-369303-1792374764 / 6cb44700 | 14:40:59镜像构建步骤报告成功，随后状态仍停在CreatingBuildingImage；源码不符，不能发布 |

最新日志重复显示分支不一致时仅fetch目标分支，然后记录旧工作区提交。部署变更接口却把LastDeployCommitId记录为目标0c50004。这说明展示的部署提交号不能作为镜像来源的证明；需要平台核对工作树切换和构建完成状态回调。上述是日志支持的观察，并非已访问或修复平台内部实现。

对照验证：相同应用源码在本地Docker Desktop中构建成功，首次启动与容器重启后各完成一次离线完整验收，包含账号登录、同一SQLite storage_id和原会话保留、会话重命名/删除、审阅导出。没有连接或复制云端用户数据库，没有调用模型，也没有证明本轮云端恢复成功。

已增加只读校验工具tools/check_hosted_source.py：以Git提交对象为基准比对6份HTML/JS/CSS，另查未登录业务401；区分private_owner与public_guest。所有者管理凭据只发往官方viewer token接口，不放进应用请求或结果。版本校验失败会返回非零退出码；校验通过仍不替代完整功能验收。

请官方在保留同一空间与/mnt/workspace运行数据的前提下，处理构建工作区缓存和完成回调。当前材料仍仅保存，未擅自对外发送。

## 15:11 恢复公开运行

当前状态为Running、public，仍是同一个空间和免费CPU配置。恢复时通过官方OpenAPI设置Docker并重新部署；15:06:53构建日志显示输入分支和工作分支均为master，镜像来源为0c50004f。15:07:07镜像构建成功，随后等待平台完成启动，不再在镜像成功后立即重复重建。

运行后先通过所有者API核对6份资源和未登录401，再用原有测试账号完成离线对照、审阅、导出、会话重命名及逻辑删除测试。SQLite storage_id与恢复前相同，原会话仍存在，启动备份存在。随后恢复公开，并以不含所有者凭据的匿名请求再次核对6份资源：全部与GitHub main 1e4c0c0一致，账号入口存在，未登录业务401。完整公开功能验证单独记录，不把私有检查充作公开验收。

本轮完整本地检查为160项Python测试、11项Node测试通过，已有离线证据完整性检查通过；没有调用付费模型、删除云端数据库或创建替代空间。配置及文档更新不改变已核对的应用源码。后续发布使用官方OpenAPI的deploy接口，并用tools/check_hosted_source.py核验目标Git提交；不能仅凭Running或展示提交号判断上线版本正确。

历史失败的控制台重建仍出现旧sbuild工作区，因此本次恢复不代表已修复平台内部构建器。若后续资源不匹配，应先保持版本校验失败，不重复发布旧程序。

公开离线验收亦已通过，未使用所有者凭据；详见[本轮恢复证据](../evals/results/deployment-restored-2026-10-20.json)。本轮没有修改应用界面，未将浏览器截图重新验收计为完成。
