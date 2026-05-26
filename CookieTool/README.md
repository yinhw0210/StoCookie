# Cookie Tool

申通内部业务系统的 **登录态采集与同步** Chrome 扩展（Manifest V3）。

## 功能概述

插件在后台自动读取浏览器中多个 STO 域名的 Cookie，并上报至 Normandy 网点管理后台；同时对部分已打开的业务页定时刷新，以维持登录态。

## 主要能力

### 1. 定时同步 Cookie（核心）

- **周期**：每 1 分钟执行一次（`chrome.alarms`）
- **上报接口**（生产 + SIT 各请求一次）：
  - `https://slinghang.cn/s/v1/normandy/api/controller/cust/netManager/settingCookie`
  - `https://lysto.com.cn/s/v1/normandy/api/controller/cust/netManager/settingCookie`
- **参数**：`cookie`（URL 编码后的 Cookie 字符串）

| 来源 | 采集内容 |
|------|----------|
| `finance-mng.sto.cn` | `SESSION` |
| `market-cod.sto.cn` | `cod` |
| `finance-fundmanage.sto.cn` | `SESSION`（以 `finance=值` 上报） |
| `wutonggateway.sto.cn` | `spf_sid`、`stoToken`、`sid_cfo`、`WD_SESSION`、`TSID` 及组合（含 `CFO_DOWNLOAD` 等） |
| 当前活动标签页（网关域） | 同上，按名称分别上报 |

### 2. 接口触发同步（网点）

- **触发条件**：请求完成 `wangdian.sto.cn/order/collectMap/query/detail/mapAreaDetail`（揽件区域管理相关接口）
- **行为**：读取 `wangdian.sto.cn` 下全部 Cookie，以 `KFSD=...` 形式上报
- **限流**：5 分钟内仅触发一次

### 3. 定时刷新业务页（保活）

若以下页面已在浏览器中打开，每分钟自动 **reload** 一次：

| 页面 URL 匹配 |
|---------------|
| `page.sto.cn/ux/manipulate-center/index` |
| `front.sto.cn/group/customerCenter#/` |
| `wangdian.sto.cn/page/fin-center/settlement/new-outbound-settlement` |
| `wangdian.sto.cn/page/external/hq-fin-center/report/policy/transfer/rebate` |
| `market-cod.sto.cn/cod/topayment/siteOrder/list` |
| `finance-fundmanage.sto.cn/prepaidment/prepaid/common/getBizType.action?showLevel=1` |

### 4. 弹窗（次要）

点击扩展图标可打开 `popup.html`：

- **Get Cookies**：预留手动获取入口（当前逻辑主要在后台自动执行）
- **Todo**：未实现

## 权限说明

| 权限 | 用途 |
|------|------|
| `cookies` | 读取各域名 Cookie |
| `alarms` | 定时任务 |
| `activeTab` / `scripting` | 与当前标签页交互 |
| `webRequest` | 监听网点接口以触发同步 |
| `host_permissions`（`http(s)://*/*`） | 访问各 STO 业务域 |

## 安装与使用

1. Chrome 打开 `chrome://extensions/`
2. 开启「开发者模式」
3. 「加载已解压的扩展程序」，选择本目录 `CookieTool`
4. 保持浏览器登录各 STO 业务系统，插件将在后台自动同步 Cookie

## 项目结构

```
CookieTool/
├── manifest.json    # 扩展配置（MV3）
├── popup.js         # 后台 Service Worker + 弹窗脚本（核心逻辑）
├── popup.html       # 扩展弹窗 UI
├── contentScript.js # 网点首页辅助脚本（当前 manifest 未引用）
├── content.js       # 页面循环点击脚本（未接入）
└── icon.png         # 扩展图标
```

## 注意事项

- 插件会将登录凭证同步至 `slinghang.cn` / `lysto.com.cn`，请确认仅为公司授权环境使用。
- 定时刷新会导致对应标签页每分钟重载，可能影响正在编辑的页面。
- `contentScript.js`、`content.js` 尚未在 `manifest.json` 中注册，不参与当前运行逻辑。

## 版本信息

- 名称：Cookie Tool
- 版本：0.0.1
- Manifest：V3
