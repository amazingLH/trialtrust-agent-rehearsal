# v0.7账号与存储验证

日期：2026-10-19。

## 本地已完成

- 完整Python156项、Node11项通过。新增14项账号回归覆盖平台权限兼容、意外I/O不吞错、生产默认鉴权、严格输入与密码不回显、bcrypt哈希、浏览器限制、账号隔离、异浏览器登录、密码修改与恢复撤销、恢复码轮换、匿名记录显式迁移、默认不迁移、运行中关联事务回滚、注册竞争、持久限流及SQLite重启保留。
- 旧匿名专项回归显式启用仅供迁移测试的工厂参数；生产工厂默认账号鉴权，新账号测试没有关闭该边界。
- 浏览器实际注册、恢复码展示、进入账号工作台和退出登录通过；账号名显示在左栏，原24小时匿名说明已移除。
- 默认桌面及390×844手机布局已查看；手机无横向溢出。太空小托为代码原创SVG/CSS，动效遵循prefers-reduced-motion。
- 使用生产默认配置进行本地HTTP完整烟测：未登录拒绝、注册登录、场景/技能、自定义澄清、离线对照、审阅、导出、会话重命名/删除通过。测试账号凭据仅在忽略的runtime目录，没有付费模型调用。

## 持续集成与部署候选

主仓库应用提交d3e1fa3的[GitHub CI](https://github.com/amazingLH/trialtrust-agent-rehearsal/actions/runs/39256566799)通过。魔搭正常源码提交125cb2b已推送，Docker构建中，硬件保持免费CPU。部署工作区账号与会话专项17项通过，冻结证据校验通过。

## 云端

本轮已完成部署、公开接口、真实门户、深度重启持久化及手机布局复核。最终结论与证据见本文末尾。


## 云端启动兼容修复

首次候选125cb2b构建成功但启动失败；运行日志明确为PermissionError: Operation not permitted，挂载盘拒绝web.sqlite的chmod，非SQLite读写失败。修复保留非root、私有目录及Web鉴权，对平台禁止的chmod元数据操作兼容处理；意外I/O仍报错。新增EPERM和EIO两项回归，账号/会话专项19项通过。重新部署验收中，未将失败候选标为完成。


## 首轮公开验收

原空间公开门户已展示登录页，app.js/auth.js/style.css/workbench_tools.js匹配候选源码；页面见[云端截图](../assets/v0.7/login-cloud.png)。用户名/密码登录后显示个人工作台，真实页面操作通过。专用测试账号使用独立HTTP浏览器标识创建，网页仅登录该测试账号，没有占用用户浏览器的注册绑定，也没有关联用户旧匿名记录。

无所有者凭据的应用烟测通过注册登录、场景/技能、未确认拦截、离线对照、审阅、导出、会话重命名/删除；[合成导出](../evals/results/accounts-cloud-offline.json)。[边界测试](../evals/results/accounts-cloud-boundaries.json)包含未登录拒绝、同一浏览器二次注册拒绝、跨账号记录/导出/审阅拒绝、恢复码轮换、密码与退出撤销，共10项断言通过。凭据、恢复码和会话令牌只在runtime私有测试文件，不上传。

平台自动产生420ef02回退提交，仅移除Docker镜像LABEL；账号与权限修复代码仍保留。部署工作区已快进接收该历史，不强推，不重复上传被回退标签。单独deploy曾选到历史Gradio启动模板，正在按明确Docker设置后的启动流程复核重启持久化。当前首轮功能验收不等于重启持久化已完成。


## 重启与手机复核

官方深度重启已重新构建当前420ef02源码。重启后同一账号登录及完整离线流程通过；数据库storage_id保持，进程boot_id变化，原有会话保留，见[重启证据](../evals/results/accounts-restart-persistence.json)。账号相关运行没有付费模型调用。

手机实际门户首轮发现iframe保持桌面画布，登录表单在屏外；[失败截图](../assets/v0.7/login-mobile-cloud-before.png)保留，不能用本地截图掩盖。登录根容器现接收现有PortalViewport的受控宽度，并使用容器查询；正在重新上线验证手机布局。


## 最终结果

最终应用发布源码42c89cf，公开资源[逐字节校验通过](../evals/results/accounts-release-assets.json)。受控桌面门户实际登录、显示个人账号与历史，退出后回到注册/登录入口；测试账号已退出，未占用用户浏览器的注册绑定。

手机390×844在实际魔搭门户复核：根容器按可信父页面宽度布局，表单单列显示，用户名、密码与登录按钮均在可见宽度内；[修复后截图](../assets/v0.7/login-mobile-cloud.png)，此前失败图仍保留。桌面默认尺寸已恢复，[最终桌面图](../assets/v0.7/login-cloud.png)已查看。装饰背景可能超出内部布局盒，由overflow隐藏，不当作表单横向滚动。

官方深度重启后，storage_id不变、boot_id改变，原账号登录和原会话查询通过；[持久化对照](../evals/results/accounts-restart-persistence.json)。手机更新再次深度重启后，[最终存储检查](../evals/results/accounts-final-storage.json)确认同一存储、旧登录会话和重启前记录仍保留。数据保留为本空间本轮实测，不保证删除/迁移空间或平台故障后的恢复。

Windows完整Python156项、Node11项通过，新增14项账号测试；[账号代码CI](https://github.com/amazingLH/trialtrust-agent-rehearsal/actions/runs/39257573632)通过。本轮无付费模型调用，未购买资源，硬件保持原免费CPU。最终本人注册与真实试用由用户自行完成。
