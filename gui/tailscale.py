"""Native Tailscale setup; no account credentials or admin API keys are stored."""

import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import urlsplit

from PyQt5.QtCore import QProcess, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
    QVBoxLayout, QWidget,
    QLayout,
)
from qfluentwidgets import PushButton, PrimaryPushButton
from .utils import ROOT

INSTALL_URL = "https://tailscale.com/download"
ADMIN_URL = "https://login.tailscale.com/admin/machines"


def find_cli():
    found = shutil.which("tailscale")
    if found:
        return found
    if sys.platform == "win32":
        for base in [os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")]:
            candidate = Path(base) / "Tailscale" / "tailscale.exe"
            if candidate.is_file():
                return str(candidate)
    for candidate in ["/usr/bin/tailscale", "/usr/local/bin/tailscale"]:
        if Path(candidate).is_file():
            return candidate
    return None


def status_summary(data, port=8893):
    state = data.get("BackendState", "Unknown")
    own = data.get("Self") or {}
    addresses = data.get("TailscaleIPs") or own.get("TailscaleIPs") or []
    ipv4 = next((a for a in addresses if is_tailscale_ip(a)), None)
    online = state == "Running" and bool(ipv4)
    titles = {"Running": "已连接", "NeedsLogin": "等待登录", "Stopped": "尚未连接",
              "NeedsMachineAuth": "等待管理员批准", "NoState": "正在启动"}
    return {
        "state": state, "online": online,
        "title": titles.get(state, "暂不可用"),
        "address": f"http://{ipv4}:{port}" if online else "",
        "ip": ipv4 or "", "name": own.get("HostName", ""),
        "health": "；".join(str(v) for v in data.get("Health") or []),
    }


def is_tailscale_ip(value):
    try:
        return ipaddress.ip_address(value) in ipaddress.ip_network("100.64.0.0/10")
    except (ValueError, TypeError):
        return False


def hub_address(value):
    """Invitation addresses must be usable from a different machine."""
    try:
        value = value.strip()
        if any(char.isspace() for char in value):
            raise ValueError()
        parsed = urlsplit(value)
        host = parsed.hostname
        if (parsed.scheme not in ("http", "https") or not host or parsed.username
                or parsed.password or parsed.path not in ("", "/")
                or parsed.query or parsed.fragment):
            raise ValueError()
        port = parsed.port
        if port is not None and port < 1:
            raise ValueError()
        if host.lower() in ("localhost", "0.0.0.0", "::"):
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None:
            address = getattr(address, "ipv4_mapped", None) or address
            if address.is_loopback or address.is_unspecified:
                raise ValueError()
        return f"{parsed.scheme}://{parsed.netloc}"
    except (ValueError, AttributeError):
        raise ValueError("请使用其他设备可访问的地址，不能填写 localhost、127.0.0.1 或 0.0.0.0。") from None


def install_command():
    if sys.platform == "win32":
        winget = shutil.which("winget")
        if winget:
            return [winget, "install", "--id", "Tailscale.Tailscale", "--exact",
                    "--source", "winget", "--accept-source-agreements",
                    "--accept-package-agreements", "--disable-interactivity"]
    elif sys.platform.startswith("linux") and shutil.which("pkexec"):
        return [shutil.which("pkexec"), "/bin/sh",
                str(ROOT / "scripts" / "install-tailscale-linux.sh")]
    return None


class TailscalePanel(QWidget):
    address_ready = pyqtSignal(str)

    def __init__(self, port=8893, parent=None):
        super().__init__(parent)
        self.port = port
        self.closed = False
        self.summary = {}
        self.process = None
        self.output = bytearray()
        self.login_opened = False
        self.mode = ""
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(10000)
        box = QVBoxLayout(self)
        box.setSizeConstraint(QLayout.SetMinimumSize)
        box.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        top.addWidget(QLabel("跨网络连接 · Tailscale", objectName="chartHeading"))
        top.addStretch()
        self.status = QLabel("正在检测", objectName="status")
        top.addWidget(self.status)
        box.addLayout(top)
        self.note = QLabel("不同网络的电脑需要加入同一 Tailscale 网络，或接受中心设备共享。")
        self.note.setWordWrap(True)
        self.note.setObjectName("muted")
        box.addWidget(self.note)
        self.address = QLineEdit()
        self.address.setReadOnly(True)
        self.address.setPlaceholderText("连接后自动显示本机 Tailscale 地址")
        box.addWidget(self.address)
        buttons = QHBoxLayout()
        self.install = PushButton("安装 Tailscale")
        self.install.clicked.connect(self.install_client)
        self.connect_button = PrimaryPushButton("登录并连接")
        self.connect_button.clicked.connect(self.connect_client)
        self.refresh_button = PushButton("重新检测")
        self.refresh_button.clicked.connect(self.refresh)
        self.admin = PushButton("邀请加入网络")
        self.admin.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(ADMIN_URL)))
        for button in (self.install, self.connect_button, self.refresh_button, self.admin):
            buttons.addWidget(button)
        box.addLayout(buttons)
        self.login_link = PushButton("打开授权页面")
        self.login_link.hide()
        self.login_link.clicked.connect(self.open_login)
        box.addWidget(self.login_link)
        self.auth_url = ""
        QTimer.singleShot(0, self.refresh)

    def refresh(self):
        if self.closed or self.process is not None:
            return
        cli = find_cli()
        if not cli:
            self.summary = {"online": False, "address": "", "state": "Missing"}
            self.status.setText("尚未安装")
            self.address.clear()
            self.install.show()
            self.connect_button.setEnabled(False)
            self.note.setText("先安装 Tailscale，再登录并连接。安装时系统可能要求管理员授权。")
            self.address_ready.emit("")
            return
        self.install.hide()
        self.connect_button.setEnabled(True)
        self.run([cli, "status", "--json"], "status", 8000)

    def run(self, command, mode, timeout):
        if self.process is not None:
            return
        self.mode = mode
        self.output.clear()
        self.login_opened = False
        self.process = QProcess(self)
        process = self.process
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.readyReadStandardOutput.connect(self.read_output)
        process.finished.connect(self.finished)
        process.errorOccurred.connect(self.process_error)
        self.deadline = QTimer(process)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self.timed_out)
        self.deadline.start(timeout)
        for button in (self.install, self.connect_button, self.refresh_button):
            button.setEnabled(False)
        process.start(command[0], command[1:])

    def read_output(self):
        if self.process is None:
            return
        self.output.extend(bytes(self.process.readAllStandardOutput()))
        if len(self.output) > 1024 * 1024:
            del self.output[:-65536]
        if self.mode == "connect":
            # Open only the official authentication host; never persist the URL.
            match = re.search(r'https://login\.tailscale\.com/[A-Za-z0-9/?=&._%-]+(?=["\s])',
                              self.output.decode("utf-8", errors="replace"))
            if match and not self.login_opened:
                self.auth_url = match.group(0)
                self.login_opened = True
                self.login_link.show()
                self.status.setText("等待浏览器授权")
                self.open_login()

    def open_login(self):
        if self.auth_url and urlsplit(self.auth_url).hostname == "login.tailscale.com":
            QDesktopServices.openUrl(QUrl(self.auth_url))

    def finished(self, exit_code, _exit_status):
        if self.process is None:
            return
        self.read_output()
        process, self.process = self.process, None
        self.deadline.stop()
        process.deleteLater()
        self.install.setEnabled(True)
        self.connect_button.setEnabled(True)
        self.refresh_button.setEnabled(True)
        text = self.output.decode("utf-8", errors="replace")
        if self.mode == "status":
            try:
                self.summary = status_summary(json.loads(text), self.port)
            except (ValueError, TypeError, AttributeError):
                self.summary = {"online": False, "address": "", "title": "服务不可用"}
            self.status.setText(self.summary["title"])
            address = self.summary["address"]
            self.address.setText(address)
            self.address_ready.emit(address)
            self.connect_button.setEnabled(not self.summary["online"])
            self.note.setText(
                "本机网络已连接。其他成员也需安装 Tailscale，并加入同一网络或接受设备共享；之后还要导入统计工具的成员接入配置。"
                if self.summary["online"] else
                "请登录并连接；若设备等待批准，请在 Tailscale 管理页面批准这台设备。"
            )
            if self.summary.get("health"):
                self.note.setText(self.note.text() + "\n" + self.summary["health"])
        elif exit_code == 0:
            self.auth_url = ""
            self.login_link.hide()
            self.refresh()
        else:
            self.status.setText("操作未完成")
            self.note.setText(
                "系统授权或安装未完成，请重试；也可从 tailscale.com/download 安装官方客户端。"
                if self.mode == "install" else
                "连接未完成。请完成系统与浏览器授权后重新检测；已有自定义 Tailscale 设置时，请在官方客户端连接，程序不会重置你的设置。"
            )

    def process_error(self, error):
        if error == QProcess.FailedToStart:
            self.finished(1, QProcess.CrashExit)

    def timed_out(self):
        if self.process is not None:
            self.process.kill()

    def install_client(self):
        command = install_command()
        if command:
            self.status.setText("正在安装")
            self.note.setText("请完成系统管理员授权，安装结束后会自动检测。")
            self.run(command, "install", 300000)
        else:
            QDesktopServices.openUrl(QUrl(INSTALL_URL))
            self.note.setText("已打开官方安装页面。安装完成后点击“重新检测”。")

    def connect_client(self):
        cli = find_cli()
        if not cli:
            self.refresh()
            return
        command = [cli, "up", "--json", "--timeout=90s"]
        if sys.platform.startswith("linux") and os.geteuid() != 0:
            pkexec = shutil.which("pkexec")
            if not pkexec:
                self.note.setText("系统缺少图形授权工具，请通过官方 Tailscale 客户端完成连接。")
                return
            command.insert(0, pkexec)
        self.status.setText("正在连接")
        self.run(command, "connect", 120000)

    def shutdown(self):
        self.closed = True
        self.timer.stop()
        self.auth_url = ""
        if self.process is not None:
            process, self.process = self.process, None
            process.blockSignals(True)
            process.kill()
            process.waitForFinished(1000)
            process.deleteLater()


class NetworkDialog(QDialog):
    def __init__(self, port=8893, parent=None):
        super().__init__(parent)
        self.setWindowTitle("跨网络连接")
        self.setMinimumWidth(640)
        box = QVBoxLayout(self)
        box.setContentsMargins(26, 24, 26, 24)
        box.setSpacing(18)
        self.panel = TailscalePanel(port, self)
        box.addWidget(self.panel)
        help_text = QLabel(
            "接入分两步：① 通过 Tailscale 加入网络或接受中心设备共享；② 在统计工具中导入自己的成员接入配置。\n"
            "“邀请加入网络”打开官方设备管理页，可共享这台中心设备。Tailscale 登录账号与共用的 OpenAI 账号是两回事。"
        )
        help_text.setWordWrap(True)
        help_text.setObjectName("muted")
        box.addWidget(help_text)
        self.copy = PushButton("复制本机 Tailscale 地址")
        self.copy.clicked.connect(lambda: QApplication.clipboard().setText(self.panel.address.text()))
        self.copy.setEnabled(False)
        self.panel.address_ready.connect(lambda address: self.copy.setEnabled(bool(address)))
        box.addWidget(self.copy)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText("关闭")
        buttons.rejected.connect(self.reject)
        box.addWidget(buttons)

    def done(self, result):
        self.panel.shutdown()
        super().done(result)
