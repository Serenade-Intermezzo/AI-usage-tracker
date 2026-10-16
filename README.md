# Codex Usage Tracker

用于统计 Codex Token 用量的原生桌面工具。界面采用 Qt / QFluentWidgets，图表由 Qt Charts 和本地绘图控件绘制，不使用浏览器或 WebView。

**项目目标：让共用同一个 OpenAI 账号的多位成员，在 Windows、Ubuntu 及其他 Linux 系统上分别采集自己的用量，并统一查看每位成员及全体成员的 Token 汇总。**

**当前状态：已实现单机原生统计；完整的多人汇总尚未实现。保留的同步模块目前有入口启动故障，不能按“多人版已可用”部署。**

本文描述本地定制版，审查日期为 2026-10-16。本分支保留原生 GUI、当前账号范围筛选和本机周月报的实现，作为后续多人功能开发的基线。

- Fork：<https://github.com/Serenade-Intermezzo/AI-usage-tracker>
- 上游：<https://github.com/Danielw412/AI-usage-tracker>
- 当前统计对象：Codex GUI / CLI 中可确认属于指定 OpenAI 登录账号的本机记录。
- Claude Code、第三方 API 服务和其他账号的用量不纳入本版统计。

## 1. 多人使用的目标与当前差距

“同一个 OpenAI 账号”“某位使用者”“一台设备”是三种不同的身份：

- **账号**决定哪些 Codex 请求属于统计范围。
- **成员**决定用量归到谁名下，必须由软件单独登记，不能从共用的 OpenAI 登录账号推断。
- **设备**决定记录从哪里采集；一个成员可以有多台设备，也可能使用不同操作系统。

目标是按 `账号 → 成员 → 设备 → Token 事件` 组织记录。同一成员的 Windows 电脑和 Linux 电脑应合并到该成员名下；全体总量应来自去重后的事件集合。

| 要求 | 当前状态 |
| --- | --- |
| 本机 Codex GUI / CLI 日志采集 | 已实现 |
| 绑定指定 OpenAI 账号并排除其他来源 | 已实现，但历史归属和监测中断有限制 |
| 原生 GUI、每日用量、活跃热力图、模型图表 | 已实现 |
| 本机周报、月报、可调整月度起始日 | 已实现 |
| Ubuntu 上实际运行 | 已验证 |
| 其他 Linux 发行版 | 有 Linux 运行路径，尚未逐发行版验证 |
| Windows 原生 GUI 与安装启动脚本 | 已准备，尚未 Windows 实机验证 |
| 成员登记、一个成员关联多台设备 | 未实现 |
| 成员用量、全员用量及相应周报/月报 | 未实现 |
| 多人汇总的统一月度周期 | 未实现；当前设置只保存在各自本机 |
| 多设备上传、断网队列、事件去重 | 保留上游模块，组件测试通过；当前应用入口集成存在阻塞 |
| 中央端校验上传记录属于指定 OpenAI 账号 | 当前协议没有账号指纹字段，尚未实现 |
| 原生 GUI 中配置汇总中心、查看人员及同步状态 | 未实现 |

把当前程序分别安装到几个人的电脑上，只会得到几套各自独立的统计，**不会自动形成“所有人的用量”看板**。

## 2. 当前审查发现

### 2.1 `server` / `collector` 模式启动失败

当前入口停用了 Claude，但同步初始化仍读取全部 provider 的数据库：

- `server/index.ts` 初始化 collector 时，遍历所有 provider 并访问 `provider.store`。
- `server/index.ts` 初始化中央端时，仍读取 `providers.claude.store`。
- `server/disabledClaude.ts` 中，被停用的 Claude provider 的 `store` getter 会直接抛错。

使用临时数据目录分别启动两个角色，均复现：

```text
TRACKER_ROLE=server     → exit 1
TRACKER_ROLE=collector  → exit 1
Error: Claude Code is disabled in this installation
```

复现没有修改实际运行的单机服务。修复应覆盖 provider 枚举、同步服务支持的 provider 集合以及真实入口启动测试，不能只把异常隐藏掉。

**目前不要依据上游 README 的多人部署步骤直接启用这两种角色。**

### 2.2 设备标识不能替代成员标识

目前配置和上传协议包含 `deviceId`、`deviceLabel`、`installId`，没有独立的 `memberId`，也没有成员与设备的映射。

设备名称即使写成某个人的名字，也不能处理一人多机、设备转交和成员筛选；共用的 OpenAI 账号标识也不能区分不同的人。未来添加成员字段后，仍不能自动推断旧记录由谁使用；历史归属需要明确的设备所有者或补录证据，并保留归属变更记录。

### 2.3 周报与月报只查询当前设备

`server/localReports.ts` 使用以下条件读取事件：

```sql
WHERE device_id = ?
```

其参数是本机设备 ID。因此，即使后续恢复上传，当前报表也不会自动变成全员报表。需要增加按成员、按设备以及全体的明确查询范围，并共享同一套周期规则。

### 2.4 Windows 启动路径仍固定为单机

`gui/main.py` 中的 `windows_backend_environment()` 固定设置：

```text
TRACKER_ROLE=standalone
HOST=127.0.0.1
```

原生 GUI 目前没有成员登记、汇总中心地址或同步配置入口。单独修改 Windows 源码目录里的 `.env`，不能把这一启动流程变成已验证的多人客户端。

### 2.5 原同步协议不等于最小化的 Token 汇总协议

保留的上游协议除了 Token 事件，还支持同步聊天标题、提示词内容、项目路径等描述性记录；它也没有当前定制版的账号指纹校验字段。

如果目标只是统计每个人用了多少 Token，多人版应默认只上传必要的计量字段，明确成员身份和账号范围。是否共享聊天内容应是另一项明确选择，不应随着用量同步默认发生。

## 3. 当前单机版的功能

### 用量报表

- 当前账号在本机的累计、本周和本月 Token。
- 周报按北京时间周一 00:00 至下周一 00:00 统计。
- 月度起始日可选择每月 **1–31 日**，点击“保存”后立即重算历史月报。
- 短月份没有所选日期时，使用当月最后一天；下个月继续按原设置计算。
- 周期未结束显示“进行中”，结束后显示“已结束”。
- 后台每分钟检查并保存汇总；GUI 关闭后后台仍可继续运行。

### 图表与明细

- 最近 14 天每日 Token 柱状图。
- 最近 30 天按星期和小时绘制的活跃热力图。
- 各模型的缓存输入、新增输入和输出构成。
- 本机聊天的入口、模型和 Token 明细。
- 原生控件使用统一字体、大字号和圆角界面。

本机已保存的月度起始日以界面为准；它目前不是全员共享的设置。

## 4. 统计含义和完整性

### 账号范围

本版读取 Codex 已保存的非秘密账号标识，并以 SHA-256 指纹绑定统计目标；不要求在软件中重新填写账号密码，也不把 OpenAI 登录令牌上传到汇总端。

只计入官方 OpenAI provider、指定账号以及 Codex GUI / CLI 来源。与这些入口关联的子任务可纳入其用量。

### 历史记录和中断

- 部分旧日志没有账号标识，不能凭“现在登录了某个账号”推断过去也属于该账号。
- 可确认账号标记的旧记录与已观察到匹配登录时段内的新记录，按代码中的筛选规则计入。
- 监测启用后的新记录需要落在已观察到的匹配登录时段；后台未运行的时段可能漏计，即使原日志文件仍存在，也不能承诺全部补齐。
- 未确认记录不混入正式统计，可在界面底部展开查看其范围说明。

因此，当前累计量表示“本机可确认记录的合计”，不能标成共享账号的完整总用量。未来的全员汇总也必须展示参与设备、最后同步时间和未覆盖范围，不能把缺失数据当成零。

### Token 计算

- 缓存输入属于输入 Token 的一部分，不应再次加到输入上。
- 按日志记录的实际发生时间归入周期，不按上传时间归入。
- 月报直接按日期范围汇总事件，不把跨月的一整周周报直接相加。
- 周报、月报中的聊天数分别去重，不能用各周聊天数简单相加代表月度独立聊天数。
- Token 统计与共享账号的额度百分比是不同指标；当前原生版不轮询账号额度，也不据额度变化猜测各人的用量。

## 5. 安装与运行：当前单机模式

要求：Node.js **22.5+**、Python **3.10+**；Python GUI 依赖见 `gui/requirements.txt`。

以下步骤针对本 fork 中包含 `gui/main.py` 的原生版源码。

### Ubuntu / Linux

本机已安装的版本可从应用列表打开 **“Codex 用量统计”**。

在新的源码目录中准备依赖：

```bash
npm ci --ignore-scripts --no-audit --no-fund
npm run build:native
python3 -m venv .venv-gui
.venv-gui/bin/python -m pip install -r gui/requirements.txt
```

创建 `.env`，示例为单机统计配置：

```dotenv
TRACKER_ROLE=standalone
LOCAL_ONLY=true
NATIVE_GUI_ONLY=true
CODEX_ACCOUNT_SCOPE=true
CODEX=true
CLAUDE_CODE=false
DEFAULT_PROVIDER=codex
QUOTA_POLLING=false
CLOUD_TASKS=false
WATCH_SESSIONS=true
HOST=127.0.0.1
PORT=8893
DATA_DIR=./data-current-account
```

Codex 日志默认从 `~/.codex` 读取。若桌面端使用独立的 `~/.codex-desktop`，应在 `.env` 中将 `CODEX_HOME` 设置为该目录的实际绝对路径，将 `CODEX_EXTRA_HOMES` 设置为 CLI 目录的实际绝对路径。多个额外目录使用本系统的路径分隔符分隔：Linux 为 `:`，Windows 为 `;`。

在使用 systemd 用户服务的 Linux 上：

```bash
bash scripts/install-linux-service.sh
bash scripts/open-local-gui.sh
```

查看后台状态与日志：

```bash
systemctl --user status ai-usage-tracker
journalctl --user -u ai-usage-tracker -n 50 --no-pager
```

Ubuntu 属于 Linux。当前实际验证的是这台 Ubuntu；其他 Linux 发行版还需确认 Qt 平台库、Python 依赖和服务管理方式。没有 systemd 的系统不能直接套用上述服务安装脚本。

### Windows 10 / 11 x64

1. 安装 Python 3.10+ 与 Node.js 22.5+。
2. 在该电脑的 Codex Desktop 或 CLI 中通过目标 OpenAI 账号登录。
3. 将本地定制版源码安装包完整解压到固定目录。
4. 首次双击 `scripts\install-native-windows.cmd`。
5. 之后使用桌面上的 **Codex Usage Tracker** 快捷方式，或 `scripts\start-native-gui.cmd`。

首次安装会联网下载 GUI 和后台依赖。安装器会创建桌面快捷方式及登录后后台采集快捷方式；移动源码目录后需要重新安装快捷方式。

Windows 数据存放在：

```text
%LOCALAPPDATA%\CodexUsageTracker\data-current-account
```

**Windows 的兼容代码和安装脚本已准备；当前没有 Windows 实机验证结果。源码安装包也不等于已经验证的独立 EXE。**

## 6. 数据、配置和源码位置

项目结构：

```text
gui/
  main.py                  原生窗口、图表入口、日期设置和本机后台启动
  charts.py                Qt 每日图、模型图及热力图
  tests/                   原生 GUI 与环境测试
server/
  index.ts                 后台入口与数据接口
  codex/accountScope.ts    当前账号与日志来源筛选
  localReports.ts          当前设备周报、月报
  sync/                    保留的跨设备同步模块；入口集成待修复
scripts/
  open-local-gui.sh         Linux 原生 GUI 入口
  install-linux-service.sh Linux 用户服务安装
  install-native-windows.* Windows 原生版安装
  start-native-gui.*       Windows 原生 GUI 启动
.github/workflows/
  native-gui.yml           已准备的 Ubuntu / Windows 检查配置
```

当前 Ubuntu 安装约定：

```text
源码与程序目录：$HOME/.local/share/ai-usage-tracker
当前账号数据：  <项目目录>/data-current-account/
月度设置：      <数据目录>/report-settings.json
报表快照：      <数据目录>/local-reports.json
账号范围：      <数据目录>/account-scope.json
旧未筛选数据：  <项目目录>/data/，不参与当前统计
GUI 隔离环境：  <项目目录>/.venv-gui/
```

备份和更新时应保留本机配置、设备标识、账号范围和数据库。不要把 `.env`、`auth.json`、数据库、会话日志或 GUI 虚拟环境提交到公共仓库。

本地源码目录已接入 Git，并保留上游提交历史；`origin` 指向本 fork。配置、数据库和虚拟环境保存在忽略列表中，不参与提交。更新远端需要显式提交和推送。

## 7. 面向多人版的下一步

以下是待实现的目标架构，不是现有部署功能：

```text
成员 A · Ubuntu GUI/CLI ─┐
成员 A · Windows GUI/CLI ├─ 本地采集与账号筛选 ─→ 汇总端 ─→ 原生 GUI
成员 B · Linux GUI/CLI ──┘                         │        ├─ 全员汇总
                                                  │        ├─ 按成员查看
                                                  └────────└─ 按设备查看
```

实现顺序：

1. **恢复 Codex-only 同步入口。** 修复停用 Claude 后的数据库访问，并对 `server`、`collector` 两种真实启动入口做测试。
2. **加入成员和设备关系。** 独立登记 `memberId` / 显示名称，让一个成员关联多个稳定设备 ID；同一台电脑由多人共用时，需要明确的用户档案或切换规则。
3. **统一账号范围和最小同步协议。** 中央端登记目标账号指纹、校验上传来源；默认只同步计量所需信息，不默认上传提示词正文和完整项目路径。
4. **实现人员与全员报表。** 按成员、设备或全体查询相同事件集合；由汇总端统一管理月度起始日和时区，更新后重算相应报表。
5. **增加原生 GUI 配置和同步状态。** 可配置人员、设备和汇总端，显示待上传数量、最后同步时间及未覆盖范围；多人数据的读取和设置变更需要明确权限。
6. **完成真实跨系统验证。** 至少覆盖 Windows + Ubuntu/Linux、同一人多设备、不同成员、断网重试、迟到记录和日志复制后的去重。

多人版的验收应以“每个人分别能查到自己的记录，并且所有人的去重合计与全员汇总一致”为准，而不能以几个单元测试通过或几个客户端窗口能打开代替。

## 8. 测试与验证边界

后台测试：

```bash
npm test
npm run build:native
npm run typecheck
```

原生 GUI 测试：

```bash
QT_QPA_PLATFORM=offscreen .venv-gui/bin/python -m unittest discover -s gui/tests -v
```

PowerShell 可先设置 `$env:QT_QPA_PLATFORM='offscreen'`，再使用 `.venv-gui\Scripts\python.exe` 执行同样的 unittest 命令。

最近的完整本地检查包括 87 项后台测试和 9 项原生 GUI / 环境测试。**这些测试没有覆盖当前应用的两种同步角色入口；本次隔离启动审查已复现这两个入口失败。** 上游同步组件的测试通过，只说明可复用的基础模块存在。

`.github/workflows/native-gui.yml` 已准备 Ubuntu / Windows 检查配置，但尚未远程运行，也没有 Windows 多人部署的验收结果。
