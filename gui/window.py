"""Window controller: scoped data, async requests and native user interactions."""

import json
from datetime import datetime, timezone, timedelta
from PyQt5.QtCore import Qt, QTimer, QUrl
from PyQt5.QtGui import QColor
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkProxy
from PyQt5.QtWidgets import (
    QMainWindow,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
)
from qfluentwidgets import TableWidget as FluentTable
from .team import ConnectionDialog, MembersDialog
from .ui import build_window
from .utils import DEFAULT_URL, compact, period_end


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
        build_window(self)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(30000)
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
            table.horizontalHeaderItem(column).setTextAlignment(
                (Qt.AlignLeft if column == 0 else Qt.AlignRight) | Qt.AlignVCenter
            )
        table.verticalHeader().setDefaultSectionSize(56)
        return table

    def request(self, endpoint: str, callback, body: dict | None = None, method=None):
        request = QNetworkRequest(QUrl(self.url + endpoint))
        request.setRawHeader(b"X-Tracker-Local", b"1")
        scope_at_request = self.scope_id
        request.setAttribute(
            QNetworkRequest.CacheLoadControlAttribute, QNetworkRequest.AlwaysNetwork
        )
        if hasattr(request, "setTransferTimeout"):
            request.setTransferTimeout(10000)
        if body is None:
            reply = self.network.get(request)
        else:
            request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
            reply = (self.network.post if method == "POST" else self.network.put)(
                request, json.dumps(body).encode("utf-8")
            )

        def done():
            scoped = endpoint.startswith(
                ("/api/team/reports", "/api/local-reports", "/api/overview")
            ) and not endpoint.endswith("settings")
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
                if endpoint == "/api/installation/restart":
                    self.restarting = False
                self.request_errors[endpoint] = str(error)
            finally:
                reply.deleteLater()
                self.active_requests.pop(id(reply), None)
                if endpoint == "/api/local-reports" or endpoint.startswith(
                    "/api/team/reports"
                ):
                    self.pending_reports = False
                elif endpoint.startswith("/api/overview"):
                    self.pending_overview = False
                elif endpoint == "/api/team":
                    self.pending_team = False
                elif endpoint.endswith("settings"):
                    self.pending_save = False
                    self.day_changed()
                self.update_status()
                if stale:
                    QTimer.singleShot(0, self.refresh)

        self.active_requests[id(reply)] = (reply, done)
        reply.finished.connect(done)

    def update_status(self):
        if self.request_errors:
            self.status.setText("连接暂时中断")
            self.coverage_notice.setText(
                "暂时无法更新 · 当前保留上次收到的数据，恢复连接后自动刷新。"
            )
            self.hint.setText("更新失败：" + next(iter(self.request_errors.values())))
            return
        if self.restarting:
            self.status.setText("后台正在重启")
            return
        scope = self.overview.get("accountScope", {})
        matching = any(home.get("matches") for home in scope.get("homes", []))
        sync = self.team.get("sync") or {}
        self.status.setText(
            (
                "等待补传"
                if sync.get("state") in ("offline", "unauthorized", "rejected")
                else "多人统计"
            )
            if self.team.get("enabled")
            else ("当前账号 · 仅本机" if matching else "等待当前账号登录")
        )
        incomplete = self.reports.get("incomplete")
        self.hint.setText(
            self.notice
            or (
                "部分设备离线或尚有待上传记录 · 当前为已收到的用量"
                if incomplete
                else "北京时间 · 周期结束后自动汇总 · 输入已包含缓存"
            )
        )

    def refresh(self):
        if self.restarting:
            return
        if not self.pending_team:
            self.pending_team = True
            self.request("/api/team", self.update_team)
        if not self.pending_reports:
            self.pending_reports = True
            endpoint = (
                "/api/local-reports"
                if self.scope_id == "local"
                else "/api/team/reports"
                + ("" if self.scope_id == "all" else "?memberId=" + self.scope_id)
            )
            self.request(endpoint, self.update_reports)
        if self.scope_id == "local" and not self.pending_overview:
            self.pending_overview = True
            self.request("/api/overview?provider=codex", self.update_overview)

    def show_page(self, index: int):
        self.stack.setCurrentIndex(index)
        self.nav.setCurrentItem(self.page_keys[index])
        self.page_title.setText(
            {
                0: "周期报表",
                1: "本机聊天",
                2: "图表分析",
                3: "成员与设备",
                4: "用量概览",
            }[index]
        )

    def set_mode(self, mode: str):
        self.mode = mode
        self.week_button.setChecked(mode == "weekly")
        self.month_button.setChecked(mode == "monthly")
        self.fill_report_table()

    def day_changed(self):
        if not self.loading_day:
            self.save_button.setEnabled(
                self.reports.get("canEditMonthDay", True)
                and not self.pending_save
                and bool(self.reports)
                and self.month_day.currentIndex() + 1
                != self.reports.get("monthStartDay")
            )

    def save_day(self):
        if self.pending_save:
            return
        self.pending_save = True
        self.save_button.setEnabled(False)
        self.request(
            (
                "/api/team/settings"
                if self.team.get("enabled") and self.team.get("role") == "server"
                else "/api/local-reports/settings"
            ),
            self.saved_day,
            {"monthStartDay": self.month_day.currentIndex() + 1},
        )

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
        dirty = bool(
            self.reports
        ) and self.month_day.currentIndex() + 1 != self.reports.get("monthStartDay")
        self.reports = reports
        self.month_day.setEnabled(reports.get("canEditMonthDay", True))
        if reports.get("scope") == "team":
            self.charts.set_data(reports.get("overview", {}))
            self.update_team_tables(reports)
            self.charts.pie.set_members(reports.get("members", []))
            self.details.setText(
                "团队报表仅包含已登记设备、指定 OpenAI 账号的可确认 Codex GUI / CLI 事件。成员归属由设备登记确定。\n周报按周一至周日，月报采用汇总中心统一起始日；离线补传后会更新历史报表。聊天正文、标题和项目路径不上传。"
            )
        if not dirty or force_day or not reports.get("canEditMonthDay", True):
            self.loading_day = True
            self.month_day.setCurrentIndex(reports["monthStartDay"] - 1)
            self.loading_day = False
        weekly, monthly = reports["weekly"], reports["monthly"]
        values = [
            sum(row["total"] for row in weekly),
            weekly[0]["total"] if weekly else 0,
            monthly[0]["total"] if monthly else 0,
        ]
        for label, value in zip(
            self.amount_labels + self.home_amounts, values + values
        ):
            label.setText(compact(value))
            label.setToolTip(f"{value:,} Token")
        self.card_notes[0].setText(
            (
                "全体成员的已确认记录"
                if self.scope_id == "all"
                else "所选成员的已确认记录"
            )
            if reports.get("scope") == "team"
            else "本机的已确认记录"
        )
        self.hero_note.setText(f"每月 {reports['monthStartDay']} 日起算 · 北京时间")
        if reports.get("scope") == "team":
            self.home_daily.set_data(
                reports.get("overview", {}).get("localDailyUsage", [])
            )
            self.contributions.set_members(reports.get("members", []))
            devices = reports.get("devices", [])
            people = len({d["memberId"] for d in devices})
            self.coverage_label.setText(
                f"{people} 位成员 · {len(devices)} 台设备 · 统一 {reports['monthStartDay']} 日起算"
            )
            attention = sum(
                not d.get("online")
                or d.get("pending") is None
                or (d.get("pending") or 0) > 0
                or d.get("syncedThrough") is None
                or bool(d.get("lastError"))
                for d in devices
            )
            self.coverage_notice.setText(
                f"{attention} 台设备需要关注 · 离线用量保留在原设备，恢复连接后自动补传。"
                if attention
                else "设备已同步 · 当前展示已收到的可确认用量，后台会持续更新。"
            )
        else:
            self.coverage_label.setText(
                f"本机记录 · 每月 {reports['monthStartDay']} 日起算"
            )
            self.coverage_notice.setText(
                "本机采集持续运行 · 在设置中建立团队或加入汇总中心。"
                if not self.team.get("enabled")
                else "当前仅查看本机用量 · 切换统计范围可以查看全员或指定成员。"
            )
        self.coverage_notice.setProperty("warning", bool(reports.get("incomplete")))
        self.coverage_notice.style().unpolish(self.coverage_notice)
        self.coverage_notice.style().polish(self.coverage_notice)
        self.card_notes[2].setText(f"每月 {reports['monthStartDay']} 日起算")
        self.fill_report_table()
        self.day_changed()

    def fill_report_table(self):
        rows = [
            row
            for row in self.reports.get(self.mode, [])
            if row["total"] or row["status"] == "open"
        ]
        self.report_table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            values = [
                f"{row['start']} — {period_end(row['endExclusive'])}",
                compact(row["total"]),
                compact(row["input"]),
                compact(row["output"]),
                str(row["chats"]),
                "进行中" if row["status"] == "open" else "已结束",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFont(self.report_table.font())
                item.setTextAlignment(
                    (Qt.AlignLeft if column == 0 else Qt.AlignRight) | Qt.AlignVCenter
                )
                if column in (1, 2, 3):
                    item.setToolTip(
                        f"{row[['total', 'input', 'output'][column - 1]]:,} Token"
                    )
                if column == 5:
                    item.setForeground(
                        QColor("#356778" if row["status"] == "open" else "#879198")
                    )
                self.report_table.setItem(index, column, item)

    def update_overview(self, overview):
        self.overview = overview
        if self.scope_id == "local":
            self.charts.set_data(overview)
            self.home_daily.set_data(overview.get("localDailyUsage", []))
        scope = overview.get("accountScope", {})
        matching = any(home.get("matches") for home in scope.get("homes", []))
        self.status.setText("当前账号 · 仅本机" if matching else "等待当前账号登录")
        threads = overview.get("threads", [])
        self.chat_table.setRowCount(len(threads))
        for index, thread in enumerate(threads):
            source = (
                "CLI"
                if thread.get("source") == "cli"
                else (
                    "GUI"
                    if thread.get("source") == "desktop"
                    else thread.get("source", "")
                )
            )
            values = [
                thread.get("title", "未命名聊天"),
                source,
                thread.get("primaryModel", ""),
                compact(thread.get("totalTokens", 0)),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFont(self.chat_table.font())
                item.setToolTip(
                    value if column != 3 else f"{thread.get('totalTokens', 0):,} Token"
                )
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
        self.charts.pie.set_members([])
        self.home_daily.set_data([])
        self.refresh()

    def update_team(self, team):
        self.team = team
        self.role_label.setText(
            {"server": "汇总中心 · 本机管理", "collector": "采集设备 · 自动补传"}.get(
                team.get("role"), "仅统计本机"
            )
        )
        self.manage_button.setEnabled(team.get("canManage", False))
        selected = self.scope_id
        self.scope.blockSignals(True)
        self.scope.clear()
        self.scope.addItem("本机", userData="local")
        if team.get("enabled"):
            self.scope.addItem("全体成员", userData="all")
            for member in team.get("members", []):
                self.scope.addItem(member["name"], userData=member["id"])
        if not self.team_loaded and team.get("enabled"):
            selected = "all"
        self.team_loaded = True
        index = self.scope.findData(selected)
        self.scope.setCurrentIndex(max(0, index))
        self.scope.blockSignals(False)
        self.scope_changed()
        if team.get("enabled"):
            sync = team.get("sync") or {}
            self.team_note.setText(
                "月度起始日由汇总中心统一管理。"
                + (
                    " 本机离线用量会保留并自动补传。"
                    if sync.get("state") == "offline"
                    else " 聊天内容仅在原设备查看。"
                )
            )
        if self.scope_id == "local" and team.get("role") == "collector":
            self.month_day.setEnabled(False)
            self.save_button.setEnabled(False)

    def update_team_tables(self, reports):
        members = reports.get("members", [])
        names = {m["id"]: m["name"] for m in members}
        rows = [
            [
                m["name"],
                compact(m["week"]),
                compact(m["month"]),
                compact(m["total"]),
                str(m["devices"]),
            ]
            for m in members
        ]
        self.set_rows(self.member_table, rows)
        rows = []
        for device in reports.get("devices", []):
            state = (
                "离线"
                if not device.get("online")
                else "待上传" if device.get("pending") else "在线"
            )
            if device.get("lastError"):
                state = "需检查"
            contact = device.get("lastSeenAt")
            rows.append(
                [
                    device["label"],
                    names.get(device["memberId"], "未登记"),
                    state,
                    (
                        str(device["pending"])
                        if device.get("pending") is not None
                        else "未知"
                    ),
                    (
                        datetime.fromtimestamp(
                            contact, timezone(timedelta(hours=8))
                        ).strftime("%m-%d %H:%M")
                        if contact
                        else "尚未联系"
                    ),
                ]
            )
        self.set_rows(self.device_table, rows)
        self.team_note.setText(
            (
                "部分设备尚未上传完整数据。"
                if reports.get("incomplete")
                else "已收到各参与设备的最近同步。"
            )
            + (
                f" 另有 {reports['unassignedEvents']} 条历史事件尚未关联成员。"
                if reports.get("unassignedEvents")
                else ""
            )
            + " 聊天内容留在各设备。"
        )

    @staticmethod
    def set_rows(table, rows):
        table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFont(table.font())
                item.setTextAlignment(
                    (Qt.AlignLeft if column == 0 else Qt.AlignRight) | Qt.AlignVCenter
                )
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
            self.request(
                "/api/installation/restart",
                lambda _: QTimer.singleShot(1500, self.poll_restart),
                {},
                "POST",
            )
        except Exception as error:
            QMessageBox.warning(self, "多人统计设置", str(error))

    def poll_restart(self):
        if self.closing:
            return
        self.restart_attempts += 1
        if self.restart_attempts > 30:
            self.restarting = False
            self.request_errors["restart"] = (
                "后台未能在等待时间内启动，请检查后台日志后重新打开界面。"
            )
            self.update_status()
            return
        # Poll the local service without blocking the native event loop.
        request = QNetworkRequest(QUrl(self.url + "/api/health"))
        if hasattr(request, "setTransferTimeout"):
            request.setTransferTimeout(1500)
        reply = self.network.get(request)

        def done():
            try:
                payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
                ready = (
                    not reply.error()
                    and payload.get("ok")
                    and payload.get("pid") != self.restart_previous_pid
                )
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
