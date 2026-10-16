# Codex 用量统计

为多人共用同一个 OpenAI 账号提供的原生桌面用量工具。每台电脑只采集自己的 Codex GUI / CLI 日志，再将计量事件上传到一个汇总中心，按成员和全体生成周报、月报。

界面使用 **Qt Widgets + QFluentWidgets + Qt Charts** 在本地绘制，保留较大的字体、圆角卡片和本地图表，无需浏览器或 WebView。后台通过本机 HTTP 接口与原生界面通信；界面不使用网页渲染。

- 本 fork：<https://github.com/Serenade-Intermezzo/AI-usage-tracker>
- 原始项目：<https://github.com/Danielw412/AI-usage-tracker>
- 原生多人版：**0.2.0**。

## 能做什么

| 功能 | 行为 |
| --- | --- |
| 成员与设备 | 汇总中心登记成员，一个成员可关联多台 Windows / Ubuntu / Linux 设备 |
| 个人及全员报表 | 原生界面可切换本机、全体成员或指定成员，查看累计、本周、本月以及历史周月报 |
| 月度周期 | 汇总中心统一设置每月 1–31 日起算，采集设备自动同步，不能各自修改 |
| 跨设备同步 | 持久化待上传队列，断网保留、恢复补传；按稳定事件标识去重 |
| 图表 | 日用量、星期 / 小时热力图、模型 Token 构成，跟随报表成员范围变化 |
| 同步状态 | 查看成员的设备数、设备在线状态、待上传数量和最近联系时间 |
| 账号范围 | 仅采集绑定 OpenAI 账号的官方 Codex GUI / CLI 可确认事件，汇总中心校验账号指纹 |
| 数据范围 | 不启用 Claude Code、不查询账号全局用量，不默认上传聊天正文、标题或项目路径 |

原生界面的“聊天明细”只在选择“本机”时显示。团队视图只展示计量信息。

## 多人使用流程

选择一台经常开机的电脑作为汇总中心，其他电脑作为采集设备。汇总中心也可以同时采集本机用量；不采集本机时可作为独立服务器。

### 1. 在汇总中心建立团队

1. 安装程序并在 Codex 中登录要统计的 OpenAI 账号。
2. 打开原生界面右上角的 **设置**，工作方式选择 **作为汇总中心**。
3. 填写本机使用者的姓名 / 昵称和设备名称。
4. 需要其他电脑连接时，勾选 **允许其他设备连接此汇总中心**。默认只监听本机。
5. 保存并等待后台自动重启。
6. 打开 **成员与设备 → 管理成员**，为每位使用者添加成员。

同一账号不等于同一成员。成员身份由这里的登记和设备关联确定，无法从共用的 OpenAI 登录信息自动识别实际使用者。

### 2. 为每个人生成接入配置

在成员管理中选择一个成员，填写其他设备可以访问的汇总中心地址，例如：

```text
http://192.168.1.10:8893
```

点击 **生成并复制此成员的接入配置**。这份配置包含该成员编号、目标账号指纹、中心地址和团队访问密钥。**只私下发送给对应成员，不要放进公开仓库、截图或日志。**

同一人的多台电脑使用同一份成员接入配置；每台电脑会保留独立设备编号。不要在不同电脑之间复制整个数据目录或 `device.json`。

局域网中需允许该端口通过汇总端防火墙。跨公网使用 HTTPS 或可信 VPN；程序本身不配置 TLS、路由器端口转发或公网服务器。

### 3. 在各台设备接入

1. 在该设备自己的 Codex GUI / CLI 中，通过同一个 OpenAI 账号登录。
2. 安装并打开原生界面，进入 **设置 → 加入汇总中心**。
3. 粘贴这个人的接入配置，填写设备名称，保存并等待后台重启。
4. 右上角范围菜单可选择 **本机 / 全体成员 / 某位成员**。
5. 在“成员与设备”检查设备是否已联系中心、是否还有待上传记录。

设备首次登记后，成员编号与安装实例保持固定，避免重复设备编号或更换成员时悄悄改写历史归属。需要修改人的显示名称，请在汇总中心使用“修改姓名”；历史会保留在原成员编号下。暂不提供已有设备历史的跨成员转移功能。

### 4. 统一设置月度起始日

在**汇总中心本机**的原生界面中选择“月度起始日”，点击保存。

- 所有人使用同一个起始日，采集设备的日期控件只读。
- 修改后重新计算历史月报；周报不受影响。
- 采集设备通过心跳取得最新设置，即使没有打开团队报表也会更新。
- 中心离线时，本机月报沿用最后收到的日期，恢复连接后更新。
- 选择 29、30 或 31 日而当月没有该日期时，使用当月最后一天。

所有报表统一使用 **Asia/Shanghai（北京时间，UTC+8）**，不随设备系统时区变化。周报按周一 00:00 至下周一 00:00，月报按配置日期的 00:00 分界。

后台每分钟保存一次报表快照，跨周、跨月后自动标记已结束；关机后再次启动会补算。离线事件到达后，历史周期也会更新，避免把“周期已结束”误认为“所有设备都已完整上传”。

## 统计范围与覆盖限制

### 账号范围

统计来自本机日志，不读取共享账号的全局用量接口。采集端只接受官方 OpenAI provider 和 Codex GUI / CLI 入口，包括可确认的子代理调用。

- 首次运行将目标账号的非密钥标识做 SHA256，保存为本机账号绑定。
- 带明确账号标识的历史日志，仅在账号匹配时纳入。
- 不带账号标识的事件，仅在后台实际观察到该账号登录的时段纳入。
- 后台停止期间的无账号标记历史不推定归属；其他账号、第三方 API 和不符合入口范围的记录排除。
- 汇总中心固定目标账号指纹，拒绝范围不一致的上传。

账号指纹用于范围一致性校验，不是密码或访问令牌。成员身份仍以设备登记为准；该工具不能从共享账号中辨认谁实际操作了键盘，也不提供对采集端日志的第三方计费认证。

如果旧版数据库尚未建立账号绑定，首次启用范围筛选时会将旧数据库保存到数据目录的 `unscoped-backup-*`，再从符合条件的日志重建；不把旧的未筛选缓存直接上传。

### Token 口径

- 总 Token 使用日志记录的 `total_tokens`，输入已包含缓存输入，避免重复加算。
- 聊天数按周期内不同线程计数；模型图基于相同范围的事件。
- 重试和完整历史重传不会重复计数。同一份日志复制到不同设备时，相同事件只计一次，归属首次收到该事件的设备。
- 这不是 OpenAI 官方账单，也不代表未安装本工具、未接入团队或未上传设备的用量。

有设备离线、尚有待上传记录、首次扫描未完成时，界面会提示当前只显示已收到的用量。周期结束后仍可能继续补传。未知或尚未关联成员的历史事件会单独提示，不默认为某个人。

### 访问权限与隐私

- 团队密钥用于设备上传和团队计量报表读取；团队成员可以查看个人及全体统计。
- 成员管理、接入配置生成和月度设置修改仅在中心本机原生界面进行。
- 远程接口不提供本机聊天明细、个人配置或登录文件。
- 同步仅发送 Token 事件、稳定标识、模型、时间及必要删除记录；正文、聊天标题、项目路径和额度样本不上传。
- 密钥保存在设备自己的 `installation.json`，默认按用户私有权限写入；Windows 还依赖用户资料目录的 ACL。
- 不修改 Codex 登录状态，也不复制 `auth.json` 到源码、发布包或团队中心。

## 安装

需要 Node.js **22.5+**、Python **3.10+**。建议使用当前 Node 22 LTS 与 Python 3.11；GUI 依赖见 `gui/requirements.txt`。

### Windows 10 / 11 x64

1. 安装 Node.js 和 Python，确保可以从终端启动。
2. 在本机 Codex GUI / CLI 中通过目标 OpenAI 账号登录。
3. 下载或 clone 本 fork，完整解压到固定目录。
4. 双击 `scripts\install-native-windows.cmd`，等待依赖安装与后台构建完成。
5. 使用桌面的 **Codex Usage Tracker** 快捷方式打开界面。

首次安装需联网。安装器会创建 GUI 快捷方式和登录时启动后台的快捷方式；关闭窗口不停止后台采集。移动源码目录后需重新安装快捷方式。

数据保存在：

```text
%LOCALAPPDATA%\CodexUsageTracker\data-current-account
```

要关闭登录后启动，可在 `shell:startup` 中删除“Codex Usage Background”。这是源码安装方式，不是独立 EXE。

### Ubuntu / 其他桌面 Linux

Ubuntu 示例；其他 Linux 发行版使用对应包管理器准备 Python venv 和 Qt 所需桌面库。

```bash
git clone https://github.com/Serenade-Intermezzo/AI-usage-tracker.git
cd AI-usage-tracker
cp .env.example .env
npm ci --ignore-scripts --no-audit --no-fund
npm run build:native
python3 -m venv .venv-gui
.venv-gui/bin/python -m pip install -r gui/requirements.txt
bash scripts/install-linux-service.sh
bash scripts/open-local-gui.sh
```

需要先安装 Node.js 22.5+；Ubuntu 若缺少 venv / Qt 桌面库，可安装 `python3-venv libxcb-xinerama0 libxcb-cursor0 libegl1`。后台运行在当前用户的 systemd 服务中，不需要管理员账户读取其他人的会话。

默认数据目录为源码目录下的 `data/`；可在 `.env` 中配置 `DATA_DIR`。程序自动发现当前用户的 `.codex-desktop` 和 `.codex`，也可通过 `CODEX_HOME` / `CODEX_EXTRA_HOMES` 指定。后者的分隔符在 Linux 为冒号、Windows 为分号。

```bash
systemctl --user status ai-usage-tracker
systemctl --user restart ai-usage-tracker
systemctl --user disable --now ai-usage-tracker
```

### 无本机采集的中心

可在设置中选择“作为汇总中心”，关闭“同时采集这台电脑的 Codex 用量”，填入目标账号指纹。此时中心不需要 OpenAI 登录文件。首次部署也可通过 `.env` 设置 `TRACKER_ROLE=server`、`CODEX_SCAN=false`、`TEAM_ACCOUNT_FINGERPRINT` 和 `SYNC_SECRET`。

纯服务器无需启动 GUI，但需要通过中心本机的管理接口登记成员并获取接入配置；建议首次在有桌面的中心完成设置。管理请求需要来自回环地址且带 `X-Tracker-Local: 1`。不对公网开放管理 API。

## 数据和更新

```text
server/installation.ts    安装角色、连接配置的校验和持久化
server/team.ts            成员、设备绑定、团队周月报和图表数据
server/sync/              上传、去重、持久队列、重试与心跳
server/codex/accountScope.ts  本机账号范围筛选
server/localReports.ts    本机周期报表及共享的日期聚合逻辑
gui/main.py              原生窗口、成员范围、报表、状态
gui/team.py              原生团队设置、成员管理和接入配置
gui/charts.py            本地 Qt 图表
```

数据目录包含：

```text
codex-usage.sqlite        本机 / 中心计量数据；采集设备还包含待上传队列
device.json               独立设备和安装实例标识
account-scope.json        非密钥账号指纹、观察到的登录时间范围
installation.json         角色、成员、连接地址和私有团队密钥
team.sqlite               中心的成员与设备归属
sync.sqlite               中心的设备心跳与上传状态
report-settings.json      本机或中心月度起始日
team-calendar.json        采集设备最后收到的中心日期设置及时间
local-reports.json        本机报表快照
team-reports.json         中心全员与每位成员的周月报快照
```

更新源码时保留整个数据目录和 `.env`，然后重新安装依赖、构建并重启后台。不要把私有数据、密钥、登录文件、会话日志或虚拟环境提交到公共仓库。保存数据目录时应使用数据库在线备份，或先停止后台后整体复制。

本机既有安装的源码目录：`$HOME/.local/share/ai-usage-tracker`；既有账号筛选数据使用其 `data-current-account/`。其他安装以自己的 `.env` / Windows 用户资料目录为准。

## 测试与验证范围

```bash
npm run typecheck
npm run build:native
npm test
QT_QPA_PLATFORM=offscreen .venv-gui/bin/python -m unittest discover -s gui/tests -v
```

测试覆盖账号范围、北京时间周月边界、短月份、多成员和多设备归属、事件重传去重、统一月度设置、真实 server / collector 进程启动、扫描上传、账号及 Claude 拒绝、离线队列与重启补传、网络访问权限、旧缓存迁移，以及原生范围切换和界面交互。

GitHub Actions 的 `.github/workflows/native-gui.yml` 在 Ubuntu 和 Windows 上运行后台与 GUI 测试，并在 Windows 检查安装脚本。CI 结果以仓库 Actions 中相应提交为准；自动化检查不等于在每位成员的真实电脑上完成账号登录、网络连接和完整日常使用验收。
