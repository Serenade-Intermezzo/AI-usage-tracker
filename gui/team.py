"""Native configuration and member management. Credentials are never part of source bundles."""

import base64
import json
import urllib.request
from urllib.parse import urlencode

from PyQt5.QtCore import Qt
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
    QVBoxLayout,
)
from qfluentwidgets import ComboBox, PushButton, PrimaryPushButton

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

    def role_changed(self):
        role = self.roles[self.role.currentIndex()]
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
                invitation = json.loads(
                    base64.urlsafe_b64decode(code + "=" * (-len(code) % 4))
                )
                for key in [
                    "centralUrl",
                    "secret",
                    "memberId",
                    "memberName",
                    "accountFingerprint",
                ]:
                    value[key] = invitation[key]
                if invitation.get("version") != 1:
                    raise ValueError("接入配置版本不支持。")
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
        self.setWindowTitle("成员管理")
        self.setMinimumWidth(630)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        self.members = ComboBox()
        layout.addWidget(self.members)
        row = QHBoxLayout()
        add = PushButton("添加成员")
        rename = PushButton("修改姓名")
        add.clicked.connect(lambda: self.save_member(False))
        rename.clicked.connect(lambda: self.save_member(True))
        row.addWidget(add)
        row.addWidget(rename)
        row.addStretch()
        layout.addLayout(row)
        layout.addWidget(QLabel("汇总中心地址（需能从其他设备访问）"))
        self.address = QLineEdit(url)
        self.address.setPlaceholderText("例如 http://192.168.1.10:8893 或 VPN 内网地址")
        layout.addWidget(self.address)
        copy = PrimaryPushButton("生成并复制此成员的接入配置")
        copy.clicked.connect(self.copy_invitation)
        layout.addWidget(copy)
        self.code = QPlainTextEdit()
        self.code.setReadOnly(True)
        self.code.setMaximumHeight(100)
        self.code.setPlaceholderText(
            "生成后可复制到该成员每台设备的“加入汇总中心”设置。"
        )
        layout.addWidget(self.code)
        note = QLabel(
            "接入配置含团队访问密钥，请只私下发给成员。公网连接请使用 HTTPS 或可信 VPN。\n成员与设备第一次关联后保持固定；修改姓名不会拆分历史。"
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        layout.addWidget(note)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        self.reload()

    def reload(self):
        selected = self.members.currentData()
        data = api(self.url, "/api/team")
        self.members.clear()
        for member in data["members"]:
            self.members.addItem(member["name"], userData=member["id"])
        index = self.members.findData(selected)
        if index >= 0:
            self.members.setCurrentIndex(index)

    def save_member(self, rename):
        name, accepted = QInputDialog.getText(
            self,
            "修改姓名" if rename else "添加成员",
            "姓名 / 昵称",
            text=self.members.currentText() if rename else "",
        )
        if not accepted:
            return
        try:
            value = {"name": name}
            if rename:
                value["id"] = self.members.currentData()
            api(self.url, "/api/team/members", value, "POST")
            self.reload()
        except Exception as error:
            QMessageBox.warning(self, "成员管理", str(error))

    def copy_invitation(self):
        try:
            query = urlencode(
                {
                    "memberId": self.members.currentData(),
                    "url": self.address.text().strip(),
                }
            )
            code = api(self.url, "/api/team/invitation?" + query)["invitation"]
            self.code.setPlainText(code)
            QApplication.clipboard().setText(code)
        except Exception as error:
            QMessageBox.warning(self, "接入配置", str(error))
