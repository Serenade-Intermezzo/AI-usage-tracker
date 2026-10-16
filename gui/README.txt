Codex Usage Tracker 0.2.0 — Native Qt desktop GUI

The UI uses Qt Widgets, QFluentWidgets and Qt Charts; no browser or WebView.

Team workflow
1. Install on one computer, open 设置, and choose 作为汇总中心.
2. Set your member/device name. Enable connections from other devices if needed.
3. Under 成员与设备 > 管理成员, add each person.
4. Enter the reachable hub URL and generate that person's invitation.
5. On each of their devices, open 设置 > 加入汇总中心 and paste that invitation.
6. Choose 本机, 全体成员 or a member in the main window.
One person can connect many devices using the same invitation. Each installation
keeps its own device identity; never copy device.json/data directories to another PC.

Only the hub's local native UI can manage members or the monthly start day.
Collectors receive the shared calendar via heartbeat and cache it while offline.
Weeks are Monday-Sunday in Asia/Shanghai. Monthly start supports 1-31 with
short-month clamping. Offline usage queues locally and catches up automatically.

Invitations contain a private team access key: share them privately with members.
Use HTTPS or a trusted VPN over public networks. Chat contents, titles and project
paths stay local. Team views only receive metering events for the pinned OpenAI
account. No Claude Code or account-wide quota polling is enabled.

Windows: install Python 3.10+ and Node 22.5+, sign into Codex, extract to a fixed
folder, then run scripts\install-native-windows.cmd. Data remains in
%LOCALAPPDATA%\CodexUsageTracker\data-current-account. Closing the GUI keeps
the backend running. Remove Codex Usage Background from shell:startup to disable
sign-in startup. This is a source installer, not a self-contained EXE.

Ubuntu/Linux: follow root README.md to install the user service and native GUI.
The root README describes account coverage limits, configuration and validation.
