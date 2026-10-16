"""Native Qt Widgets GUI. No browser, HTML, JavaScript renderer, or WebEngine."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request

from PyQt5.QtCore import Qt, QTimer, QUrl
from PyQt5.QtGui import QColor, QFont, QFontDatabase, QIcon, QPalette
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkProxy
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QMainWindow, QMessageBox, QPushButton, QStackedWidget,
    QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget, QGraphicsDropShadowEffect,
)

from qfluentwidgets import (PushButton as FluentButton, ToggleButton, PrimaryPushButton, ComboBox as FluentComboBox,
                            TableWidget as FluentTable, setFont as setFluentFont,
                            setCustomStyleSheet, setTheme, setThemeColor, setFontFamilies, Theme)
if __package__:
    from .charts import ChartsPanel
    from .team import ConnectionDialog, MembersDialog, api as local_api
else:
    from charts import ChartsPanel
    from team import ConnectionDialog, MembersDialog, api as local_api

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_URL = "http://127.0.0.1:8893"
NETWORK_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def compact(value: int) -> str:
    for divisor, unit in [(1_000_000_000, "B"), (1_000_000, "M"), (1000, "K")]:
        if value >= divisor:
            return f"{value / divisor:,.2f}".rstrip("0").rstrip(".") + unit
    return f"{value:,}"


def period_end(exclusive: str) -> str:
    from datetime import date, timedelta
    return (date.fromisoformat(exclusive) - timedelta(days=1)).isoformat()


def backend_is_ready(url: str) -> bool:
    try:
        with NETWORK_OPENER.open(url + "/api/health", timeout=1) as response:
            health = json.load(response)
        with NETWORK_OPENER.open(url + "/api/overview?provider=codex", timeout=2) as response:
            scope = json.load(response)
        return bool(health.get("ok") and ((health.get("role") == "server" and not health.get("scanLocal", True)) or (scope.get("trackingScope") == "local" and scope.get("accountScope", {}).get("enabled"))))
    except (OSError, ValueError):
        return False


def windows_backend_environment() -> dict[str, str]:
    """Machine-specific configuration is generated at runtime, never shipped."""
    env = os.environ.copy()
    home = Path.home()
    candidates = [home / ".codex-desktop", home / ".codex"]
    explicit = env.get("CODEX_HOME")
    if explicit:
        candidates.insert(0, Path(explicit))
    candidates = list(dict.fromkeys(candidates))
    homes = [p for p in candidates if (p / "auth.json").is_file()]
    eligible = []
    for p in homes:
        try:
            auth = json.loads((p / "auth.json").read_text(encoding="utf-8"))
            if auth.get("auth_mode") == "chatgpt" and auth.get("tokens", {}).get("account_id"):
                eligible.append(p)
        except (OSError, ValueError):
            pass
    data = Path(env.get('LOCALAPPDATA', str(home / 'AppData' / 'Local'))) / 'CodexUsageTracker' / 'data-current-account'
    profile = data / 'installation.json'
    headless = profile.is_file() and json.loads(profile.read_text(encoding='utf-8')).get('scanLocal') is False
    if not eligible and not headless:
        raise RuntimeError("请先在 Codex 桌面端或 CLI 中通过 OpenAI 账号登录，再打开统计工具。")
    primary = eligible[0] if eligible else candidates[0]
    data = Path(env.get("LOCALAPPDATA", str(home / "AppData" / "Local"))) / "CodexUsageTracker" / "data-current-account"
    data.mkdir(parents=True, exist_ok=True)
    env.update({
        "TRACKER_ROLE": "standalone", "HOST": "127.0.0.1", "PORT": "8893",
        "LOCAL_ONLY": "true", "NATIVE_GUI_ONLY": "true", "CODEX_ACCOUNT_SCOPE": "true", "CODEX": "true",
        "CLAUDE_CODE": "false", "DEFAULT_PROVIDER": "codex", "CLOUD_TASKS": "false",
        "QUOTA_POLLING": "false", "WATCH_SESSIONS": "true", "DEMO_MODE": "false",
        "DATA_DIR": str(data), "CODEX_HOME": str(primary),
        "CODEX_EXTRA_HOMES": os.pathsep.join(str(p) for p in homes if p != primary),
    })
    return env


def ensure_backend(url: str) -> None:
    if backend_is_ready(url):
        return
    if sys.platform == "win32":
        node = shutil.which("node")
        if not node or not (ROOT / "dist-server" / "index.js").is_file():
            raise RuntimeError("请先双击 scripts\\install-native-windows.cmd 完成安装。")
        env = windows_backend_environment()
        log_dir = Path(env["DATA_DIR"])
        with (log_dir / "backend.log").open("ab") as log:
            subprocess.Popen(
                [node, str(ROOT / "dist-server" / "index.js")], cwd=str(ROOT), env=env,
                stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
            )
    elif sys.platform.startswith("linux"):
        subprocess.run(["systemctl", "--user", "start", "ai-usage-tracker.service"], check=True, timeout=15)
    else:
        raise RuntimeError("请先启动本机的 Codex 用量后台服务。")
    for _ in range(60):
        if backend_is_ready(url):
            return
        time.sleep(0.25)
    raise RuntimeError("本机后台未就绪，请检查 ai-usage-tracker 服务或 backend.log。")


STYLE = """
QMainWindow, QWidget#root { background: #f3f5f8; color: #22282e; }
QWidget { font-family: "@FONT@"; font-size: 16px; font-weight: 400; }
QFrame#card, QFrame#report { background: white; border: none; border-radius: 24px; }
QLabel#chartHeading { font-size: 19px; font-weight: 600; color: #253d47; }
QLabel#heading { font-size: 25px; font-weight: 500; color: #20282f; }
QLabel#muted { color: #7d8790; font-size: 14px; }
QLabel#amount { font-size: 38px; font-weight: 500; color: #253d47; padding: 6px 0; }
QPushButton, QToolButton { background: white; border: 1px solid #dce2e7; border-radius: 18px; padding: 7px 15px; color: #50616b; }
QPushButton:hover, QToolButton:hover { background: #eff4f5; }
QPushButton:checked { background: #e7eff1; color: #315b68; border-color: #ccdce1; font-weight: 600; }
QPushButton#save { background: #355d6b; color: white; border: none; }
QPushButton:disabled { color: #a9b0b6; }
QPushButton#save:disabled { background: #edf0f3; color: #a3adb4; }
QLineEdit, QPlainTextEdit { background: white; border: 1px solid #dce2e7; border-radius: 12px; padding: 8px; }
QDialog { background: #f3f5f8; }
QComboBox { background: white; border: 1px solid #dce2e7; border-radius: 16px; padding: 5px 10px; min-width: 50px; }
QTableWidget { background: white; alternate-background-color: #fafbfc; border: none; gridline-color: #edf0f2; selection-background-color: #e8f0f2; selection-color: #263e48; }
QTableWidget::item { padding: 10px; border-bottom: 1px solid #edf0f2; }
QHeaderView::section { background: white; color: #73808b; padding: 11px 10px; border: none; border-bottom: 1px solid #e7ebef; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 3px; }
QScrollBar::handle:vertical { background: #c7cfd5; border-radius: 3px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


class UsageWindow(QMainWindow):
    def __init__(self, url: str = DEFAULT_URL):
        super().__init__()
        self.url = url.rstrip("/")
        self.network = QNetworkAccessManager(self)
        self.network.setProxy(QNetworkProxy(QNetworkProxy.NoProxy))
        self.reports = {}
        self.team = {}
        self.pending_team = False
        self.team_loaded = False
        self.scope_id = "local"
        self.restarting = False
        self.closing = False
        self.overview = {}
        self.mode = "weekly"
        self.loading_day = False
        self.pending_reports = False
        self.pending_overview = False
        self.pending_save = False
        self.request_errors = {}
        self.active_requests = {}
        self.notice = ""
        self.setWindowTitle("Codex 用量统计")
        self.resize(1180, 880)
        self.setMinimumSize(1000, 740)
        icon = ROOT / "public" / "ai-usage-tracker-logo.png"
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        root = QWidget(objectName="root")
        self.setCentralWidget(root)
        page = QVBoxLayout(root)
        page.setContentsMargins(30, 24, 30, 18)
        page.setSpacing(18)
        header = QHBoxLayout()
        title = QLabel("Codex 用量统计", objectName="heading")
        header.addWidget(title)
        header.addStretch()
        self.status = QLabel("当前账号 · 仅本机", objectName="muted")
        header.addWidget(self.status)
        refresh = FluentButton("刷新")
        refresh.clicked.connect(self.refresh)
        header.addWidget(refresh)
        self.settings_button = FluentButton("设置")
        self.settings_button.clicked.connect(self.configure_team)
        header.addWidget(self.settings_button)
        page.addLayout(header)
        self.navigation = QHBoxLayout()
        self.report_tab = ToggleButton("用量报表")
        self.chat_tab = ToggleButton("聊天明细")
        self.chart_tab = ToggleButton("图表分析")
        self.team_tab = ToggleButton("成员与设备")
        for button in (self.report_tab, self.chat_tab, self.chart_tab, self.team_tab):
            button.setCheckable(True)
            self.navigation.addWidget(button)
        self.report_tab.setChecked(True)
        self.navigation.addStretch()
        self.scope = FluentComboBox()
        self.scope.addItem("本机", userData="local")
        self.scope.currentIndexChanged.connect(self.scope_changed)
        self.scope.setMinimumWidth(150)
        self.navigation.addWidget(self.scope)
        self.report_tab.clicked.connect(lambda: self.show_page(0))
        self.chat_tab.clicked.connect(lambda: self.show_page(1))
        self.chart_tab.clicked.connect(lambda: self.show_page(2))
        self.team_tab.clicked.connect(lambda: self.show_page(3))
        page.addLayout(self.navigation)
        self.stack = QStackedWidget()
        page.addWidget(self.stack, 1)
        report_page = QWidget()
        report_layout = QVBoxLayout(report_page)
        report_layout.setContentsMargins(0, 0, 0, 0)
        report_layout.setSpacing(18)
        cards = QHBoxLayout()
        cards.setSpacing(14)
        self.amount_labels = []
        self.card_notes = []
        for text, note in [("累计用量", "当前账号的已确认记录"), ("本周", "周一至周日"), ("本月", "")]:
            frame = QFrame(objectName="card")
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(20, 18, 20, 18)
            layout.addWidget(QLabel(text, objectName="muted"))
            value = QLabel("—", objectName="amount")
            layout.addWidget(value)
            sub = QLabel(note, objectName="muted")
            layout.addWidget(sub)
            self.amount_labels.append(value)
            self.card_notes.append(sub)
            cards.addWidget(frame, 1)
        report_layout.addLayout(cards)
        frame = QFrame(objectName="report")
        box = QVBoxLayout(frame)
        box.setContentsMargins(18, 16, 18, 10)
        box.setSpacing(14)
        toolbar = QHBoxLayout()
        self.week_button = ToggleButton("周报")
        self.month_button = ToggleButton("月报")
        for b in (self.week_button, self.month_button):
            b.setCheckable(True)
            toolbar.addWidget(b)
        self.week_button.setChecked(True)
        self.week_button.clicked.connect(lambda: self.set_mode("weekly"))
        self.month_button.clicked.connect(lambda: self.set_mode("monthly"))
        toolbar.addStretch()
        toolbar.addWidget(QLabel("月度起始日", objectName="muted"))
        self.month_day = FluentComboBox()
        self.month_day.setObjectName("monthStartDay")
        self.month_day.addItems([f"{day} 日" for day in range(1, 32)])
        self.month_day.currentIndexChanged.connect(self.day_changed)
        toolbar.addWidget(self.month_day)
        self.save_button = PrimaryPushButton("保存")
        self.save_button.setObjectName("save")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save_day)
        toolbar.addWidget(self.save_button)
        box.addLayout(toolbar)
        self.report_table = self.make_table(["周期", "总 Token", "输入", "输出", "聊天数", "状态"])
        self.report_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        box.addWidget(self.report_table, 1)
        self.hint = QLabel("北京时间 · 周期结束后自动汇总 · 输入已包含缓存", objectName="muted")
        box.addWidget(self.hint)
        report_layout.addWidget(frame, 1)
        self.stack.addWidget(report_page)
        self.chat_table = self.make_table(["聊天", "入口", "模型", "Token"])
        self.chat_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.stack.addWidget(self.chat_table)
        self.charts = ChartsPanel()
        self.stack.addWidget(self.charts)
        team_page = QWidget()
        team_box = QVBoxLayout(team_page)
        team_box.setContentsMargins(0, 0, 0, 0)
        member_card = QFrame(objectName="card")
        member_box = QVBoxLayout(member_card)
        member_box.setContentsMargins(18, 16, 18, 12)
        device_card = QFrame(objectName="card")
        device_box = QVBoxLayout(device_card)
        device_box.setContentsMargins(18, 16, 18, 12)
        team_header = QHBoxLayout()
        team_header.addWidget(QLabel("成员用量 · 本周 / 本月", objectName="chartHeading"))
        team_header.addStretch()
        self.manage_button = FluentButton("管理成员")
        self.manage_button.setEnabled(False)
        self.manage_button.clicked.connect(self.manage_members)
        team_header.addWidget(self.manage_button)
        member_box.addLayout(team_header)
        self.member_table = self.make_table(["成员", "本周 Token", "本月 Token", "累计 Token", "设备数"])
        self.member_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in (1, 2, 3):
            self.member_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.Fixed)
            self.member_table.setColumnWidth(column, 145)
        self.member_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        self.member_table.setColumnWidth(4, 85)
        member_box.addWidget(self.member_table)
        team_box.addWidget(member_card, 1)
        device_box.addWidget(QLabel("设备同步", objectName="chartHeading"))
        self.device_table = self.make_table(["设备", "成员", "状态", "待上传", "最近联系"])
        self.device_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        device_box.addWidget(self.device_table)
        team_box.addWidget(device_card, 1)
        self.team_note = QLabel("在设置中建立汇总中心或加入现有中心。", objectName="muted")
        self.team_note.setWordWrap(True)
        team_box.addWidget(self.team_note)
        self.stack.addWidget(team_page)
        self.detail_button = QToolButton()
        self.detail_button.setText("统计范围与未计入记录")
        self.detail_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.detail_button.setArrowType(Qt.RightArrow)
        self.detail_button.setCheckable(True)
        self.detail_button.toggled.connect(self.toggle_details)
        page.addWidget(self.detail_button, alignment=Qt.AlignLeft)
        self.details = QLabel(objectName="muted")
        self.details.setWordWrap(True)
        self.details.hide()
        page.addWidget(self.details)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(30000)
        soft_button = """
PushButton, ToggleButton, PrimaryPushButton {font-size:16px; padding:8px 18px; min-height:26px; border-radius:19px; border:1px solid transparent; background:#ffffff; color:#526376;}
PushButton:hover, ToggleButton:hover {background:#eaf0f7;}
ToggleButton:checked {background:#e4edf9; color:#3c6295; border:1px solid transparent; font-weight:500;}
PrimaryPushButton {background:#5a82b8; color:white;}
PrimaryPushButton:hover {background:#4d76ab;}
PrimaryPushButton:disabled {background:#edf1f6; color:#a1abb7; border:none;}
"""
        for button in self.findChildren(FluentButton):
            setFluentFont(button, 16)
            setCustomStyleSheet(button, soft_button, soft_button)
        setFluentFont(self.month_day, 16)
        qss = 'ComboBox {font-size:16px; min-height:28px; border-radius:17px; border:1px solid transparent; background:#f0f4f9; padding:5px 14px;}'
        setCustomStyleSheet(self.month_day, qss, qss)
        for table in [self.report_table, self.chat_table, self.member_table, self.device_table]:
            setFluentFont(table, 16)
            qss = 'QTableView, QTableWidget {font-size:16px; border:none; border-radius:16px;} QHeaderView::section {font-size:15px; background:white; color:#82909d; border:none; border-bottom:1px solid #f0f3f7; padding:13px 10px;}'
            setCustomStyleSheet(table, qss, qss)
        for frame in self.findChildren(QFrame):
            if frame.objectName() not in ('card', 'report'):
                continue
            shadow = QGraphicsDropShadowEffect(frame)
            shadow.setBlurRadius(24)
            shadow.setOffset(0, 3)
            shadow.setColor(QColor(40, 63, 90, 12))
            frame.setGraphicsEffect(shadow)
        QTimer.singleShot(0, self.refresh)

    def closeEvent(self, event):
        self.closing = True
        self.timer.stop()
        for reply, callback in list(self.active_requests.values()):
            try:
                reply.finished.disconnect(callback)
                reply.abort()
                reply.deleteLater()
            except RuntimeError:
                pass
        self.active_requests.clear()
        super().closeEvent(event)

    @staticmethod
    def make_table(headers: list[str]) -> QTableWidget:
        table = FluentTable()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().hide()
        table.setShowGrid(False)
        table.setAlternatingRowColors(False)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setFocusPolicy(Qt.NoFocus)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setHighlightSections(False)
        for column in range(len(headers)):
            table.horizontalHeaderItem(column).setTextAlignment((Qt.AlignLeft if column == 0 else Qt.AlignRight) | Qt.AlignVCenter)
        table.verticalHeader().setDefaultSectionSize(56)
        return table

    def request(self, endpoint: str, callback, body: dict | None = None, method=None):
        request = QNetworkRequest(QUrl(self.url + endpoint))
        request.setRawHeader(b"X-Tracker-Local", b"1")
        scope_at_request = self.scope_id
        request.setAttribute(QNetworkRequest.CacheLoadControlAttribute, QNetworkRequest.AlwaysNetwork)
        if hasattr(request, "setTransferTimeout"):
            request.setTransferTimeout(10000)
        if body is None:
            reply = self.network.get(request)
        else:
            request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
            reply = (self.network.post if method == "POST" else self.network.put)(request, json.dumps(body).encode("utf-8"))
        def done():
            scoped = endpoint.startswith(("/api/team/reports", "/api/local-reports", "/api/overview")) and not endpoint.endswith("settings")
            stale = scoped and scope_at_request != self.scope_id
            try:
                if stale:
                    return
                payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
                if reply.error() or payload.get("error"):
                    raise RuntimeError(payload.get("error") or reply.errorString())
                callback(payload)
                self.request_errors.pop(endpoint, None)
            except Exception as error:
                if endpoint == "/api/installation/restart": self.restarting = False
                self.request_errors[endpoint] = str(error)
            finally:
                reply.deleteLater()
                self.active_requests.pop(id(reply), None)
                if endpoint == "/api/local-reports" or endpoint.startswith("/api/team/reports"):
                    self.pending_reports = False
                elif endpoint.startswith("/api/overview"):
                    self.pending_overview = False
                elif endpoint == "/api/team":
                    self.pending_team = False
                elif endpoint.endswith("settings"):
                    self.pending_save = False
                    self.day_changed()
                self.update_status()
                if stale: QTimer.singleShot(0, self.refresh)
        self.active_requests[id(reply)] = (reply, done)
        reply.finished.connect(done)

    def update_status(self):
        if self.request_errors:
            self.status.setText("连接暂时中断")
            self.hint.setText("更新失败：" + next(iter(self.request_errors.values())))
            return
        if self.restarting:
            self.status.setText("后台正在重启")
            return
        scope = self.overview.get("accountScope", {})
        matching = any(home.get("matches") for home in scope.get("homes", []))
        sync = self.team.get("sync") or {}
        self.status.setText(("等待补传" if sync.get("state") in ("offline", "unauthorized", "rejected") else "多人统计") if self.team.get("enabled") else ("当前账号 · 仅本机" if matching else "等待当前账号登录"))
        incomplete = self.reports.get("incomplete")
        self.hint.setText(self.notice or ("部分设备离线或尚有待上传记录 · 当前为已收到的用量" if incomplete else "北京时间 · 周期结束后自动汇总 · 输入已包含缓存"))

    def refresh(self):
        if self.restarting:
            return
        if not self.pending_team:
            self.pending_team = True
            self.request("/api/team", self.update_team)
        if not self.pending_reports:
            self.pending_reports = True
            endpoint = "/api/local-reports" if self.scope_id == "local" else "/api/team/reports" + ("" if self.scope_id == "all" else "?memberId=" + self.scope_id)
            self.request(endpoint, self.update_reports)
        if self.scope_id == "local" and not self.pending_overview:
            self.pending_overview = True
            self.request("/api/overview?provider=codex", self.update_overview)

    def show_page(self, index: int):
        self.stack.setCurrentIndex(index)
        self.report_tab.setChecked(index == 0)
        self.chat_tab.setChecked(index == 1)
        self.chart_tab.setChecked(index == 2)
        self.team_tab.setChecked(index == 3)

    def set_mode(self, mode: str):
        self.mode = mode
        self.week_button.setChecked(mode == "weekly")
        self.month_button.setChecked(mode == "monthly")
        self.fill_report_table()

    def day_changed(self):
        if not self.loading_day:
            self.save_button.setEnabled(self.reports.get("canEditMonthDay", True) and not self.pending_save and bool(self.reports) and self.month_day.currentIndex() + 1 != self.reports.get("monthStartDay"))

    def save_day(self):
        if self.pending_save:
            return
        self.pending_save = True
        self.save_button.setEnabled(False)
        self.request("/api/team/settings" if self.team.get("enabled") and self.team.get("role") == "server" else "/api/local-reports/settings", self.saved_day, {"monthStartDay": self.month_day.currentIndex() + 1})

    def saved_day(self, reports):
        if self.scope_id != "all" and reports.get("scope") == "team":
            self.pending_reports = False
            self.refresh()
        else:
            self.update_reports(reports, force_day=True)
        self.set_mode("monthly")
        self.notice = "已保存月度起始日，历史月报已重新汇总。"

    def update_reports(self, reports, force_day=False):
        if not force_day:
            self.notice = ""
        dirty = bool(self.reports) and self.month_day.currentIndex() + 1 != self.reports.get("monthStartDay")
        self.reports = reports
        self.month_day.setEnabled(reports.get("canEditMonthDay", True))
        if reports.get("scope") == "team":
            self.charts.set_data(reports.get("overview", {}))
            self.update_team_tables(reports)
            self.details.setText("团队报表仅包含已登记设备、指定 OpenAI 账号的可确认 Codex GUI / CLI 事件。成员归属由设备登记确定。\n周报按周一至周日，月报采用汇总中心统一起始日；离线补传后会更新历史报表。聊天正文、标题和项目路径不上传。")
        if not dirty or force_day or not reports.get("canEditMonthDay", True):
            self.loading_day = True
            self.month_day.setCurrentIndex(reports["monthStartDay"] - 1)
            self.loading_day = False
        weekly, monthly = reports["weekly"], reports["monthly"]
        values = [sum(row["total"] for row in weekly), weekly[0]["total"] if weekly else 0, monthly[0]["total"] if monthly else 0]
        for label, value in zip(self.amount_labels, values):
            label.setText(compact(value))
            label.setToolTip(f"{value:,} Token")
        self.card_notes[0].setText(("全体成员的已确认记录" if self.scope_id == "all" else "所选成员的已确认记录") if reports.get("scope") == "team" else "本机的已确认记录")
        self.card_notes[2].setText(f"每月 {reports['monthStartDay']} 日起算")
        self.fill_report_table()
        self.day_changed()

    def fill_report_table(self):
        rows = [row for row in self.reports.get(self.mode, []) if row["total"] or row["status"] == "open"]
        self.report_table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            values = [f"{row['start']} — {period_end(row['endExclusive'])}", compact(row["total"]), compact(row["input"]), compact(row["output"]), str(row["chats"]), "进行中" if row["status"] == "open" else "已结束"]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFont(self.report_table.font())
                item.setTextAlignment((Qt.AlignLeft if column == 0 else Qt.AlignRight) | Qt.AlignVCenter)
                if column in (1, 2, 3):
                    item.setToolTip(f"{row[['total', 'input', 'output'][column - 1]]:,} Token")
                if column == 5:
                    item.setForeground(QColor("#356778" if row["status"] == "open" else "#879198"))
                self.report_table.setItem(index, column, item)

    def update_overview(self, overview):
        self.overview = overview
        if self.scope_id == "local":
            self.charts.set_data(overview)
        scope = overview.get("accountScope", {})
        matching = any(home.get("matches") for home in scope.get("homes", []))
        self.status.setText("当前账号 · 仅本机" if matching else "等待当前账号登录")
        threads = overview.get("threads", [])
        self.chat_table.setRowCount(len(threads))
        for index, thread in enumerate(threads):
            source = "CLI" if thread.get("source") == "cli" else "GUI" if thread.get("source") == "desktop" else thread.get("source", "")
            values = [thread.get("title", "未命名聊天"), source, thread.get("primaryModel", ""), compact(thread.get("totalTokens", 0))]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFont(self.chat_table.font())
                item.setToolTip(value if column != 3 else f"{thread.get('totalTokens', 0):,} Token")
                self.chat_table.setItem(index, column, item)
        self.details.setText(
            "仅统计本机 Codex GUI / CLI 中当前 OpenAI 账号的可确认记录。\n"
            + scope.get("note", "")
            + f"\n未确认历史来源 {scope.get('unverifiedFiles', 0)} 份；第三方服务 {scope.get('otherProviderFiles', 0)} 份；其他账号 {scope.get('otherAccountFiles', 0)} 份。\n"
            + "月度起始日支持 1–31 日；短月份没有该日期时，使用当月最后一天。修改后重算历史月报，周报不变。"
        )

    def scope_changed(self):
        selected = self.scope.currentData() or "local"
        if selected == self.scope_id:
            return
        self.scope_id = selected
        self.request_errors.clear()
        self.reports = {}
        self.report_table.setRowCount(0)
        self.chat_tab.setEnabled(selected == "local")
        if selected != "local" and self.stack.currentIndex() == 1:
            self.show_page(0)
        self.charts.set_data({})
        self.refresh()

    def update_team(self, team):
        self.team = team
        self.manage_button.setEnabled(team.get("canManage", False))
        selected = self.scope_id
        self.scope.blockSignals(True)
        self.scope.clear()
        self.scope.addItem("本机", userData="local")
        if team.get("enabled"):
            self.scope.addItem("全体成员", userData="all")
            for member in team.get("members", []):
                self.scope.addItem(member['name'], userData=member['id'])
        if not self.team_loaded and team.get("enabled"):
            selected = "all"
        self.team_loaded = True
        index = self.scope.findData(selected)
        self.scope.setCurrentIndex(max(0, index))
        self.scope.blockSignals(False)
        self.scope_changed()
        if team.get("enabled"):
            sync = team.get("sync") or {}
            self.team_note.setText("月度起始日由汇总中心统一管理。" + (" 本机离线用量会保留并自动补传。" if sync.get('state') == 'offline' else " 聊天内容仅在原设备查看。"))
        if self.scope_id == "local" and team.get("role") == "collector":
            self.month_day.setEnabled(False)
            self.save_button.setEnabled(False)

    def update_team_tables(self, reports):
        members = reports.get("members", [])
        names = {m['id']: m['name'] for m in members}
        rows = [[m['name'], compact(m['week']), compact(m['month']), compact(m['total']), str(m['devices'])] for m in members]
        self.set_rows(self.member_table, rows)
        rows = []
        for device in reports.get('devices', []):
            state = "离线" if not device.get('online') else "待上传" if device.get('pending') else "在线"
            if device.get('lastError'): state = "需检查"
            contact = device.get('lastSeenAt')
            rows.append([device['label'], names.get(device['memberId'], '未登记'), state,
                         str(device['pending']) if device.get('pending') is not None else '未知',
                         datetime.fromtimestamp(contact, timezone(timedelta(hours=8))).strftime('%m-%d %H:%M') if contact else '尚未联系'])
        self.set_rows(self.device_table, rows)
        self.team_note.setText(("部分设备尚未上传完整数据。" if reports.get('incomplete') else "已收到各参与设备的最近同步。") +
                              (f" 另有 {reports['unassignedEvents']} 条历史事件尚未关联成员。" if reports.get('unassignedEvents') else '') + " 聊天内容留在各设备。")

    @staticmethod
    def set_rows(table, rows):
        table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFont(table.font())
                item.setTextAlignment((Qt.AlignLeft if column == 0 else Qt.AlignRight) | Qt.AlignVCenter)
                table.setItem(row, column, item)

    def configure_team(self):
        try:
            dialog = ConnectionDialog(self.url, self)
            if dialog.exec_() != dialog.Accepted:
                return
            self.restarting = True
            self.restart_previous_pid = dialog.profile.get("pid")
            self.restart_attempts = 0
            self.team_loaded = False
            self.request_errors.clear()
            self.request("/api/installation/restart", lambda _: QTimer.singleShot(1500, self.poll_restart), {}, "POST")
        except Exception as error:
            QMessageBox.warning(self, "多人统计设置", str(error))

    def poll_restart(self):
        if self.closing:
            return
        self.restart_attempts += 1
        if self.restart_attempts > 30:
            self.restarting = False
            self.request_errors['restart'] = '后台未能在等待时间内启动，请检查后台日志后重新打开界面。'
            self.update_status()
            return
        # Poll the local service without blocking the native event loop.
        request = QNetworkRequest(QUrl(self.url + "/api/health"))
        if hasattr(request, 'setTransferTimeout'): request.setTransferTimeout(1500)
        reply = self.network.get(request)
        def done():
            try:
                payload = json.loads(bytes(reply.readAll()).decode('utf-8'))
                ready = not reply.error() and payload.get('ok') and payload.get('pid') != self.restart_previous_pid
            except (ValueError, OSError):
                ready = False
            reply.deleteLater()
            self.active_requests.pop(id(reply), None)
            if ready:
                self.restarting = False
                self.request_errors.clear()
                self.scope_id = "local"
                self.pending_reports = self.pending_overview = self.pending_team = False
                self.refresh()
            else:
                QTimer.singleShot(1500, self.poll_restart)
        self.active_requests[id(reply)] = (reply, done)
        reply.finished.connect(done)

    def manage_members(self):
        try:
            MembersDialog(self.url, self).exec_()
            self.refresh()
        except Exception as error:
            QMessageBox.warning(self, "成员管理", str(error))

    def toggle_details(self, expanded: bool):
        self.details.setVisible(expanded)
        self.detail_button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)


def create_app() -> QApplication:
    if QApplication.instance() is None:
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Codex 用量统计")
    app.setOrganizationName("CodexUsageTracker")
    app.setDesktopFileName("ai-usage-tracker")
    app.setStyle("Fusion")
    setTheme(Theme.LIGHT)
    setThemeColor("#3b6ed4")
    available = set(QFontDatabase().families())
    choices = ["Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans CJK SC"] if sys.platform == "win32" else ["Noto Sans CJK SC", "Noto Sans SC", "Microsoft YaHei UI"]
    family = next((name for name in choices if name in available), app.font().family())
    setFontFamilies([family])
    font = QFont(family)
    font.setPixelSize(16)
    font.setWeight(QFont.Normal)
    app.setFont(font)
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#f4f5f7"))
    palette.setColor(QPalette.Base, Qt.white)
    palette.setColor(QPalette.Text, QColor("#22282e"))
    palette.setColor(QPalette.WindowText, QColor("#22282e"))
    app.setPalette(palette)
    app.setStyleSheet(STYLE.replace("@FONT@", family))
    return app


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--no-start-backend", action="store_true")
    parser.add_argument("--backend-only", action="store_true")
    args = parser.parse_args()
    if args.backend_only:
        try:
            ensure_backend(args.url)
            return 0
        except Exception as error:
            if sys.platform == "win32":
                folder = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "CodexUsageTracker"
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "startup-error.log").write_text(str(error), encoding="utf-8")
            return 1
    app = create_app()
    try:
        if not args.no_start_backend:
            ensure_backend(args.url)
    except Exception as error:
        QMessageBox.critical(None, "Codex 用量统计", str(error))
        return 1
    window = UsageWindow(args.url)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
