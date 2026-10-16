当前仅支持各设备独立的单机统计；多人登记与统一汇总尚未完成，server/collector 入口存在已复现的启动故障。详情以根目录 README.md 为准。

Codex Usage Tracker — Native desktop GUI

Ubuntu
The installed application launcher opens a Qt Widgets window.
The local backend is managed by ai-usage-tracker.service.
QFluentWidgets controls and Qt Charts are rendered locally.
No browser, WebView, or Qt WebEngine is used by gui/main.py.
The charts tab shows daily usage, weekday/hour activity and model token composition.
Table and control text is 16 pixels; summary numbers and headings use larger text.

Windows 10/11 (64-bit)
1. Install Python 3.10+ and Node.js 22.5+ (64-bit).
2. Sign in to Codex Desktop or CLI using the intended OpenAI/ChatGPT account.
3. Extract the entire release ZIP into a permanent folder.
4. Double-click scripts\install-native-windows.cmd once.
5. Use the new "Codex Usage Tracker" desktop shortcut thereafter.
The first installation downloads Qt and Node dependencies, so internet access is needed.
No administrator account is required for the application installation.
Keep the extracted folder in place: shortcuts refer to it.

The installer creates:
- .venv-gui for the native Python/Qt GUI.
- A desktop shortcut to the GUI.
- A Startup-folder shortcut to start only the background collector at sign-in.
The data is kept in %LOCALAPPDATA%\CodexUsageTracker\data-current-account,
separately from the source and from the original Codex logs.
Closing the GUI keeps the local background collector running.
To disable sign-in startup, remove "Codex Usage Background" from shell:startup.

Monthly start day
Choose a day from 1 through 31 in the native "月度起始日" dropdown and click "保存".
Historical monthly reports are recalculated immediately. Weekly reports do not change.
Short months use the last day when the selected day is absent.
All report boundaries use Asia/Shanghai time. A week is Monday through Sunday.

Account scope
Only this machine's official Codex GUI/CLI usage attributable to the pinned OpenAI account is counted.
Claude Code is disabled. Third-party providers, other accounts and unverifiable historical usage are excluded.
No account quota or account-wide usage polling is used.
Older logs without an account identifier cannot be retroactively assigned to an account.
New untagged usage is counted only inside locally observed ChatGPT-login intervals.
If the background collector was stopped, untagged usage from that gap is not inferred.
The app never changes Codex login credentials, and this ZIP contains no user data or login files.

Validation
The Ubuntu native window and tests were exercised locally.
Windows startup/installer code is provided; a Windows runtime was not available for local execution.
.github/workflows/native-gui.yml provides Ubuntu and Windows checks after it is run on GitHub.
