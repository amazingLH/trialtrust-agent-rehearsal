# 托管发布复核记录

## 最新状态（2026-10-19）

原trialtrust已采用Docker模式恢复新版界面，官方匿名门户中新建会话后，默认“自己选择需求”，第三和第四步标题及等待提示均可见。公开资源与已验证Git树c8570c1一致；离线对照、审阅、导出及未确认拦截通过，证据见evals/results/original-docker-assets.json、cloud-original-core.json。主仓库完整实现本地139项Python、11项Node通过；[应用CI](https://github.com/amazingLH/trialtrust-agent-rehearsal/actions/runs/39220093250)通过。

已知未完成项：公共网关仍拒绝PATCH/DELETE；新增加的带类型、明确确认和归属校验的POST适配器正常提交后，又被平台自动回退（59722a9、9ee8338、118627d、1dd4def、a3d5312）。理由仍为sensitive file content or message，没有更具体说明。本轮没有继续反复提交该被回退接口，已恢复此前实际上线的界面，避免部分回退破坏新旧DOM配合。新适配器保存在GitHub与本地，未冒称云端已可使用。

临时trialtrust-workbench已停止并设为私有，最终删除尚未完成。官方文档明确不支持通过OpenAPI/SDK删除创空间；受控内置浏览器更多菜单仅有“举报”，用户自己的浏览器登录未使这里出现所有者控件。请所有者在自己的已登录浏览器打开该临时空间，通过空间管理删除；不要误删trialtrust。

以下保留此前检查记录，代表各自检查时点。

日期：2026-10-19。应用代码主仓库不受托管平台自动回退影响。

## 已核实的情况

- GitHub应用提交`3c97eb0`包含v0.6.1完整实现；Windows Python135项、Node11项通过，应用CI通过。
- 托管提交`2d7f146`曾完成公开资源匹配与匿名接口验收，证据保留于`evals/results/`。
- 此后平台以Administrator身份自动产生6条回退提交，最后一条为`6d86ec9453dadfe6f3e2112f0da85e27e19b2c3e`。统一理由为`sensitive file content or message`，没有更具体的说明。
- 涉及`tests/test_conversations.py`、`app.py`、`trialtrust/webapp.py`、`CHANGELOG.md`、`trialtrust/web/app.js`、`trialtrust/web/index.html`。回退删除了适配公共网关的POST会话操作等修改。
- 最新无所有者凭据检查时，运行实例的3份资源仍与完整版本一致；远端源码和运行实例不同，因此重建可能使会话操作失效。直连HTTP403也可能来自门户访问上下文，需要官方匿名门户令牌，不能单独解释为应用停止。

平台未披露触发内容，不能认定是代码缺陷、密钥泄露或缓存故障。没有为绕过审核重新提交相同代码、强推历史或另建空间。

## 需要空间所有者完成的平台复核

进入[创空间](https://www.modelscope.cn/studios/L666H666Better/trialtrust-workbench)查看代码回退记录和管理页通知。通过平台提供的支持或复核入口提交以下说明；本项目未代为发送外部消息：

> v0.6.1应用更新提交2d7f146后，平台自动回退6个文件，最后提交6d86ec9453dadfe6f3e2112f0da85e27e19b2c3e，提示sensitive file content or message。请明确具体文件、触发内容及合规修改要求，并确认复核后的正常发布流程。当前运行实例与远端源码版本不一致。更新主要为兼容公共网关的会话重命名/确认删除接口，完整实现与测试保存在公开代码主仓库。

请勿发送模型密钥、管理令牌、会话凭据或运行数据库。收到具体原因后，按平台要求修改，正常提交、部署，并重新核验远端源码、公开资源和实际操作，才可关闭本发布事项。

## 立即使用完整版本

若当前公开运行实例不可用，可以本地运行，完整会话操作不依赖托管发布审核。Windows PowerShell在项目根目录执行：

```powershell
$env:TRIALTRUST_ENABLE_LIVE = '0'
python -m uvicorn trialtrust.webapp:app --host 127.0.0.1 --port 8774
```

依赖安装见[复现指南](reproducibility.md)。打开`http://127.0.0.1:8774/`。离线模式不会调用付费模型。使用独立运行目录可避免与其他服务共用SQLite；停止原服务后再用同端口启动。不要将任何服务直接暴露到公网。


## 单一入口迁移检查（后续更新）

维护者已选择保留原`L666H666Better/trialtrust`，展示名称已通过平台API核实为“试托·Agent委托前试运行工作台”。GitHub主页和主要文档已指回此入口。临时`trialtrust-workbench`待完整迁移验收后删除，当前尚未删除。

原空间本轮提交`5bbc71b`仅更新新的需求入口、折叠说明及步骤占位等界面；此前被平台回退的POST会话兼容实现没有重新提交。该部署候选在Windows上132项Python、11项Node通过；主仓库完整版本为135项Python、11项Node通过，二者不能混称完全相同。

平台构建分支`sbuild-369303-1792394446`实际包含`5bbc71b`，并含新的`workbench_tools.js`。部署状态变为Running后，公开app.js和style.css仍与该提交不符，辅助脚本返回404，见[实际校验结果](../evals/results/retained-studio-migration.json)。构建源码已更新与公开实例仍旧版同时成立；不能仅归因于此前源码审核，也不能断言具体的缓存或路由原因。

请空间所有者补充向平台复核：原空间源提交5bbc71b已进入构建分支98cd51b，2026-10-19 15:21构建日志成功，Running后公开资源却仍旧版且/api/workbench-assets/workbench_tools.js返回404，请核对运行实例对应镜像、代码目录与公开域名路由。同时处理此前6个文件自动回退的具体原因。不要发送密钥或运行数据库。

完整迁移的验收条件：远端源码不再被回退、公开资源与当前源码匹配、三项界面交互通过、会话重命名/删除在匿名门户下通过。全部满足后才删除临时空间；不以删除备用入口来掩盖迁移失败。
