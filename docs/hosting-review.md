# 托管发布复核记录

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
