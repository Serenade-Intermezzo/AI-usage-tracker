"""Native configuration and member management. Credentials are never part of source bundles."""

import json
import urllib.request
from urllib.parse import urlencode

from PyQt5.QtCore import Qt, QSettings, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QListWidget,
    QListWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QWidget,
    QScrollArea,
    QFrame,
    QLayout,
    QTabWidget,
    QVBoxLayout,
)
from qfluentwidgets import ComboBox, PushButton, PrimaryPushButton, TableWidget, setFont, setCustomStyleSheet
from .tailscale import NetworkDialog, TailscalePanel, hub_address
from .connection import parse_invitation, HubProbe
from .utils import compact

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api(url, path, data=None, method=None):
    request = urllib.request.Request(
        url + path,
        data=None if data is None else json.dumps(data).encode(),
        method=method or ("GET" if data is None else "PUT"),
        headers={"Content-Type": "application/json", "X-Tracker-Local": "1"},
    )
    try:
        with OPENER.open(request, timeout=10) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        try:
            detail = json.load(error).get("error", "操作失败")
        except (ValueError, OSError):
            detail = "操作失败"
        raise RuntimeError(detail) from None


class ConnectionDialog(QDialog):
    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.url = url
        self.profile = api(url, "/api/installation")
        self.setWindowTitle("多人统计设置")
        self.setMinimumWidth(610)
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(28, 24, 28, 24)
        form = QFormLayout()
        self.form = form
        form.setSpacing(14)
        self.role = ComboBox()
        self.roles = ["standalone", "server", "collector"]
        self.role.addItems(["仅统计本机", "作为汇总中心", "加入汇总中心"])
        self.role.setCurrentIndex(self.roles.index(self.profile["role"]))
        form.addRow("工作方式", self.role)
        self.name = QLineEdit(self.profile["memberName"])
        self.device = QLineEdit(self.profile["deviceLabel"])
        form.addRow("我的姓名 / 昵称", self.name)
        form.addRow("这台设备的名称", self.device)
        self.invitation = QPlainTextEdit()
        self.invitation.setPlaceholderText(
            "粘贴汇总中心为你生成的接入配置；同一人的多台设备使用同一份配置。"
        )
        self.invitation.setMaximumHeight(100)
        form.addRow("接入配置", self.invitation)
        self.lan = QCheckBox("允许其他设备连接此汇总中心")
        self.lan.setChecked(self.profile.get("listenHost") in ("0.0.0.0", "::"))
        form.addRow("", self.lan)
        self.scan = QCheckBox("同时采集这台电脑的 Codex 用量")
        self.scan.setChecked(self.profile.get("scanLocal", True))
        form.addRow("", self.scan)
        self.fingerprint = QLineEdit(self.profile.get("accountFingerprint") or "")
        self.fingerprint.setPlaceholderText(
            "通常自动读取；纯汇总服务器可从接入配置取得账号指纹"
        )
        form.addRow("账号范围指纹", self.fingerprint)
        layout.addLayout(form)
        self.invitation_summary = QLabel(objectName="muted")
        self.invitation_summary.setWordWrap(True)
        layout.addWidget(self.invitation_summary)
        network_row = QHBoxLayout()
        network_button = PushButton("跨网络连接 · Tailscale")
        network_button.clicked.connect(self.open_network)
        network_row.addWidget(network_button)
        self.test_button = PushButton("测试中心连接")
        self.test_button.clicked.connect(self.test_connection)
        network_row.addWidget(self.test_button)
        network_row.addStretch()
        layout.addLayout(network_row)
        self.probe = HubProbe(self)
        self.probe.checked.connect(self.connection_checked)
        self.invitation.textChanged.connect(self.invitation_changed)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setObjectName("muted")
        layout.addWidget(self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("保存并重启后台")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.role.currentIndexChanged.connect(self.role_changed)
        self.scan.toggled.connect(self.role_changed)
        self.role_changed()

    def open_network(self):
        NetworkDialog(QUrl(self.url).port(8893), self).exec_()

    def invitation_changed(self):
        self.probe.cancel()
        self.test_button.setEnabled(True)
        try:
            value = parse_invitation(self.invitation.toPlainText())
            self.invitation_summary.setText(f"成员：{value['memberName']}\n汇总中心：{value['centralUrl']}")
        except ValueError:
            self.invitation_summary.setText("请粘贴完整接入配置；也可粘贴中心复制的整段操作说明。")

    def test_connection(self):
        try:
            value = (parse_invitation(self.invitation.toPlainText())
                     if self.invitation.toPlainText().strip() else self.profile)
            if not value.get("secret"):
                raise ValueError("请先粘贴成员接入配置；已接入设备也可重新粘贴原配置进行测试。")
            self.test_button.setEnabled(False)
            self.invitation_summary.setText("正在确认中心连接、成员和账号范围…")
            self.probe.check(value)
        except ValueError as error:
            self.invitation_summary.setText(str(error))

    def connection_checked(self, _ok, message):
        self.test_button.setEnabled(True)
        self.invitation_summary.setText(message)

    def done(self, result):
        self.probe.cancel()
        super().done(result)

    def role_changed(self):
        role = self.roles[self.role.currentIndex()]
        self.test_button.setVisible(role == "collector")
        self.invitation_summary.setVisible(role == "collector")
        self.invitation.setVisible(role == "collector")
        self.form.labelForField(self.invitation).setVisible(role == "collector")
        self.invitation.setEnabled(role == "collector")
        self.name.setEnabled(role != "collector")
        self.lan.setVisible(role == "server")
        self.scan.setVisible(role == "server")
        self.lan.setEnabled(role == "server")
        self.scan.setEnabled(role == "server")
        advanced = role == "server" and not self.scan.isChecked()
        self.fingerprint.setVisible(advanced)
        self.form.labelForField(self.fingerprint).setVisible(advanced)
        self.fingerprint.setEnabled(advanced)
        notes = {
            "standalone": "保存后保留原有本机历史。各人的用量通过成员编号区分，姓名可以在汇总中心修改。",
            "server": "月度起始日和成员由这台电脑统一管理。其他设备连接时，此汇总中心需保持运行；离线期间会在各设备保留待上传用量。",
            "collector": "先在 Codex GUI / CLI 登录同一 OpenAI 账号。只上传计量信息；聊天正文、标题和项目路径留在本机。月度起始日由汇总中心统一管理。",
        }
        self.note.setText(notes[role])

    def save(self):
        try:
            role = self.roles[self.role.currentIndex()]
            value = dict(self.profile)
            value.update(
                role=role,
                memberName=self.name.text().strip(),
                deviceLabel=self.device.text().strip(),
                listenHost=(
                    "0.0.0.0"
                    if role == "server" and self.lan.isChecked()
                    else "127.0.0.1"
                ),
                scanLocal=self.scan.isChecked() if role == "server" else True,
                accountFingerprint=self.fingerprint.text().strip() or None,
            )
            code = self.invitation.toPlainText().strip()
            if role == "collector" and code:
                invitation = parse_invitation(code)
                for key in [
                    "centralUrl",
                    "secret",
                    "memberId",
                    "memberName",
                    "accountFingerprint",
                ]:
                    value[key] = invitation[key]
            elif role == "collector" and self.profile["role"] != "collector":
                raise ValueError("请粘贴汇总中心生成的接入配置。")
            api(self.url, "/api/installation", value)
            self.accept()
        except Exception as error:
            QMessageBox.warning(self, "设置未保存", str(error))


class MembersDialog(QDialog):
    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.url = url
        self.people = []
        self.report = {}
        self.self_member_id = None
        self.accepts_remote = True
        self.setWindowTitle("成员与邀请")
        available = self.screen().availableGeometry()
        self.resize(min(1100, available.width() - 40), min(800, available.height() - 48))
        self.setMinimumSize(720, 480)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)
        heading = QHBoxLayout()
        heading.addWidget(QLabel("成员与邀请", objectName="heading"))
        heading.addStretch()
        self.refresh_button = PushButton("刷新")
        self.refresh_button.clicked.connect(self.reload)
        heading.addWidget(self.refresh_button)
        outer.addLayout(heading)
        columns = QHBoxLayout()
        outer.addLayout(columns, 1)
        left = QVBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索成员")
        self.search.textChanged.connect(self.filter_members)
        left.addWidget(self.search)
        self.members = QListWidget()
        self.members.setMinimumWidth(170)
        self.members.setMaximumWidth(250)
        self.members.setStyleSheet("QListWidget {border:0;background:#eaf0f1;border-radius:16px;} QListWidget::item {padding:13px;border-radius:10px;} QListWidget::item:selected {background:#d6e8df;color:#285e50;}")
        self.members.currentItemChanged.connect(self.member_changed)
        left.addWidget(self.members, 1)
        self.add_button = PrimaryPushButton("添加成员")
        self.add_button.clicked.connect(lambda: self.save_member(False))
        left.addWidget(self.add_button)
        columns.addLayout(left, 1)
        detail = QWidget()
        right = QVBoxLayout(detail)
        right.setContentsMargins(0, 0, 10, 0)
        right.setSpacing(14)
        right.setSizeConstraint(QLayout.SetMinimumSize)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(detail)
        columns.addWidget(scroll, 4)
        row = QHBoxLayout()
        self.member_name = QLabel("选择一个成员", objectName="chartHeading")
        row.addWidget(self.member_name, 1)
        self.rename_button = PushButton("改名")
        self.rename_button.clicked.connect(lambda: self.save_member(True))
        self.delete_button = PushButton("删除空成员")
        self.delete_button.clicked.connect(self.delete_member)
        row.addWidget(self.rename_button)
        row.addWidget(self.delete_button)
        right.addLayout(row)
        self.summary = QLabel(objectName="muted")
        self.summary.setWordWrap(True)
        right.addWidget(self.summary)
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("QTabWidget::pane {border:0;} QTabBar::tab {padding:9px 16px;color:#6e8583;border:0;} QTabBar::tab:selected {color:#2f7561;background:#e1ece6;border-radius:12px;}")
        right.addWidget(self.tabs)
        device_page = QWidget()
        device_layout = QVBoxLayout(device_page)
        device_layout.setContentsMargins(0, 14, 0, 0)
        self.devices = TableWidget()
        self.devices.setColumnCount(3)
        self.devices.setHorizontalHeaderLabels(["关联设备", "状态", "待上传"])
        self.devices.verticalHeader().hide()
        self.devices.setEditTriggers(QTableWidget.NoEditTriggers)
        self.devices.setSelectionBehavior(QTableWidget.SelectRows)
        self.devices.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.devices.setColumnWidth(1, 100)
        self.devices.setColumnWidth(2, 85)
        self.devices.setMinimumHeight(120)
        self.devices.setShowGrid(False)
        self.devices.setMinimumHeight(180)
        setFont(self.devices, 16)
        table_style = "QTableView,QTableWidget {font-size:16px;border:none;background:transparent;} QHeaderView::section {font-size:14px;border:none;background:transparent;color:#829390;padding:12px;}"
        setCustomStyleSheet(self.devices, table_style, table_style)
        device_layout.addWidget(self.devices, 1)
        next_step = PrimaryPushButton("邀请这个成员的其他设备")
        next_step.clicked.connect(lambda: self.tabs.setCurrentIndex(1))
        device_layout.addWidget(next_step)
        self.tabs.addTab(device_page, "用量与设备")
        invite_page = QWidget()
        invite_layout = QVBoxLayout(invite_page)
        invite_layout.setContentsMargins(0, 14, 0, 0)
        invite_layout.setSpacing(14)
        invite_layout.setSizeConstraint(QLayout.SetMinimumSize)
        invite_scroll = QScrollArea()
        invite_scroll.setFrameShape(QFrame.NoFrame)
        invite_scroll.setWidgetResizable(True)
        invite_scroll.setWidget(invite_page)
        self.tabs.addTab(invite_scroll, "邀请接入")
        self.network = TailscalePanel(QUrl(url).port(8893), self)
        self.network.address.hide()
        self.network.admin.setText("共享中心设备")
        invite_layout.addWidget(self.network)
        invite_layout.addWidget(QLabel("成员接入地址"))
        address_row = QHBoxLayout()
        self.settings = QSettings()
        self.address_key = "invitations/address/" + url
        self.address = QLineEdit(str(self.settings.value(self.address_key, "")))
        self.address.setPlaceholderText("连接 Tailscale 后自动填写，或输入可访问的中心地址")
        self.address.textChanged.connect(self.clear_invitation)
        address_row.addWidget(self.address, 1)
        self.use_address = PushButton("使用 Tailscale 地址")
        self.use_address.setEnabled(False)
        self.use_address.clicked.connect(lambda: self.address.setText(self.network.address.text()))
        address_row.addWidget(self.use_address)
        invite_layout.addLayout(address_row)
        self.network.address_ready.connect(self.network_changed)
        self.address_note = QLabel(objectName="muted")
        self.address_note.setWordWrap(True)
        invite_layout.addWidget(self.address_note)
        invite_row = QHBoxLayout()
        self.invite_button = PrimaryPushButton("复制接入配置")
        self.invite_button.clicked.connect(self.copy_invitation)
        invite_row.addWidget(self.invite_button)
        self.instructions_button = PushButton("复制给成员的操作说明")
        self.instructions_button.clicked.connect(self.copy_instructions)
        invite_row.addWidget(self.instructions_button)
        invite_layout.addLayout(invite_row)
        self.code = QPlainTextEdit()
        self.code.setReadOnly(True)
        self.code.setMaximumHeight(65)
        self.code.setPlaceholderText("选好成员和地址后复制配置。同一人的多台设备使用同一份配置。")
        invite_layout.addWidget(self.code)
        invite_layout.addStretch()
        self.feedback = QLabel(objectName="muted")
        self.feedback.setWordWrap(True)
        outer.addWidget(self.feedback)
        note = QLabel("网络邀请与统计邀请分开：先加入 Tailscale 网络或接受中心设备共享，再导入成员配置。配置含团队密钥，请私下发送。")
        note.setObjectName("muted")
        note.setWordWrap(True)
        outer.addWidget(note)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.button(QDialogButtonBox.Close).setText("关闭")
        close.rejected.connect(self.reject)
        outer.addWidget(close)
        self.reload()

    def current_member(self):
        item = self.members.currentItem()
        return item.data(Qt.UserRole) if item else None

    def select_member(self, member_id):
        for i in range(self.members.count()):
            item = self.members.item(i)
            if item.data(Qt.UserRole) == member_id:
                self.members.setCurrentItem(item)
                return

    def reload(self, selected=None):
        selected = selected if isinstance(selected, str) else self.current_member()
        try:
            data = api(self.url, "/api/team")
            report = api(self.url, "/api/team/reports")
            self.people = data["members"]
            self.self_member_id = data.get("selfMemberId")
            self.accepts_remote = data.get("acceptsRemote", True)
            self.report = report
            self.members.blockSignals(True)
            self.members.clear()
            for member in self.people:
                item = QListWidgetItem(member["name"])
                item.setData(Qt.UserRole, member["id"])
                self.members.addItem(item)
            self.members.blockSignals(False)
            self.select_member(selected)
            if self.members.currentItem() is None and self.members.count():
                self.members.setCurrentRow(0)
            self.filter_members(self.search.text())
            self.member_changed()
            self.feedback.setText(f"{len(self.people)} 位成员 · {len(report.get('devices', []))} 台设备")
            if not self.accepts_remote:
                self.feedback.setText("中心目前仅允许本机访问。请在“设置与连接”勾选“允许其他设备连接此汇总中心”，保存并重启后再生成邀请。")
        except Exception as error:
            self.feedback.setText("刷新失败：" + str(error))

    def filter_members(self, text):
        first = None
        for i in range(self.members.count()):
            item = self.members.item(i)
            visible = text.casefold() in item.text().casefold()
            item.setHidden(not visible)
            if visible and first is None:
                first = item
        current = self.members.currentItem()
        if current is None or current.isHidden():
            self.members.setCurrentItem(first)
        self.member_changed()

    def member_changed(self, *_):
        member_id = self.current_member()
        person = next((m for m in self.people if m["id"] == member_id), None)
        stats = next((m for m in self.report.get("members", []) if m["id"] == member_id), {})
        devices = [d for d in self.report.get("devices", []) if d["memberId"] == member_id]
        self.member_name.setText(person["name"] if person else "未找到成员")
        self.summary.setText(
            f"本周 {compact(stats.get('week', 0))} · 本月 {compact(stats.get('month', 0))} · 累计 {compact(stats.get('total', 0))} Token · {len(devices)} 台设备"
            if person else "添加成员后生成接入配置。"
        )
        if person and not devices:
            self.summary.setText("等待设备接入 · 同一成员的多台电脑使用同一份配置")
        self.devices.setRowCount(len(devices))
        self.tabs.setCurrentIndex(0 if devices else 1)
        for row, device in enumerate(devices):
            state = "需检查" if device.get("lastError") else "在线" if device.get("online") else "离线"
            if device.get("online") and device.get("pending"):
                state = "待上传"
            for col, value in enumerate([device["label"], state, str(device.get("pending") if device.get("pending") is not None else "—")]):
                self.devices.setItem(row, col, QTableWidgetItem(value))
        self.rename_button.setEnabled(person is not None)
        removable = person is not None and not devices and member_id != self.self_member_id
        self.delete_button.setEnabled(removable)
        self.delete_button.setToolTip("仅可删除尚未关联设备的成员；已有设备和历史归属会保留。")
        self.clear_invitation()

    def network_changed(self, address):
        self.use_address.setEnabled(bool(address))
        if address and not self.address.text().strip():
            self.address.setText(address)

    def clear_invitation(self, *_):
        self.code.clear()
        try:
            address = hub_address(self.address.text())
            valid = True
            host = QUrl(address).host()
            self.address_note.setText("跨网络请使用本机 Tailscale 地址；局域网地址仅适用于可访问该局域网的设备。" if not host.endswith(".ts.net") and not host.startswith("100.") else "请让成员先接通 Tailscale，再导入配置。")
        except ValueError:
            valid = False
            self.address_note.setText("先连接 Tailscale 获取地址，不能把 localhost 或 127.0.0.1 发给其他电脑。")
        ready = valid and self.current_member() is not None and self.accepts_remote
        self.invite_button.setEnabled(ready)
        self.instructions_button.setEnabled(ready)

    def save_member(self, rename):
        current = self.members.currentItem()
        name, accepted = QInputDialog.getText(
            self, "修改姓名" if rename else "添加成员", "姓名 / 昵称",
            text=current.text() if rename and current else "",
        )
        if not accepted:
            return
        try:
            value = {"name": name.strip()}
            if rename:
                value["id"] = self.current_member()
            member = api(self.url, "/api/team/members", value, "POST")
            self.search.clear()
            self.reload(member["id"])
            self.feedback.setText("姓名已更新，设备与历史归属保留。" if rename else "成员已添加，接下来复制他的接入配置。")
        except Exception as error:
            QMessageBox.warning(self, "成员管理", str(error))

    def delete_member(self):
        member_id = self.current_member()
        if not self.delete_button.isEnabled():
            return
        if QMessageBox.question(self, "删除空成员", "删除这个尚未接入设备的成员？此前发出的配置将失效。") != QMessageBox.Yes:
            return
        try:
            api(self.url, "/api/team/members/" + member_id, method="DELETE")
            self.reload()
        except Exception as error:
            QMessageBox.warning(self, "成员管理", str(error))

    def generate_invitation(self):
        if not self.accepts_remote:
            raise ValueError("中心尚未允许其他设备连接，请先在设置中开启并重启后台。")
        address = hub_address(self.address.text())
        member_id = self.current_member()
        if not member_id:
            raise ValueError("请先选择一个成员。")
        query = urlencode({"memberId": member_id, "url": address})
        code = api(self.url, "/api/team/invitation?" + query)["invitation"]
        self.code.setPlainText(code)
        self.settings.setValue(self.address_key, address)
        return code

    def copy_invitation(self):
        try:
            QApplication.clipboard().setText(self.generate_invitation())
            self.feedback.setText("已复制所选成员的配置，请私下发送。同一人的多台设备使用这份配置。")
        except Exception as error:
            QMessageBox.warning(self, "接入配置", str(error))

    def copy_instructions(self):
        try:
            code = self.generate_invitation()
            name = self.members.currentItem().text()
            message = (
                f"{name}，请按下面步骤接入 Codex 用量统计：\n"
                "1. 安装 Tailscale，加入我们的网络或接受汇总中心设备共享，保持已连接。\n"
                "2. 安装统计工具：https://github.com/Serenade-Intermezzo/AI-usage-tracker\n"
                "3. 在 Codex 中登录共同统计的 OpenAI 账号。\n"
                "4. 打开统计工具 → 设置与连接 → 加入汇总中心，粘贴下方配置，填写设备名称。\n"
                "5. 点击测试中心连接，成功后保存并等待扫描上传。\n"
                "同一人的多台电脑使用同一份配置，每台设备单独安装，不要复制数据目录。\n"
                "接入配置：\n" + code + "\n\n此配置含团队密钥，请勿公开。"
            )
            QApplication.clipboard().setText(message)
            self.feedback.setText("已复制操作说明与成员配置。网络共享邀请需在 Tailscale 中另外发送。")
        except Exception as error:
            QMessageBox.warning(self, "接入配置", str(error))

    def done(self, result):
        self.network.shutdown()
        super().done(result)
