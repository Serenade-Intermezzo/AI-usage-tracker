"""Invitation parsing and asynchronous, account-pinned connection checks."""

import base64
import json
import re
from urllib.parse import urlsplit

from PyQt5.QtCore import QObject, QUrl, pyqtSignal
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkProxy, QNetworkRequest


def parse_invitation(text):
    # Accept either a bare code or the instructions copied by the member dialog.
    if "接入配置：" in text:
        text = text.split("接入配置：", 1)[1].strip().splitlines()[0]
    code = text.strip()
    try:
        if not code or len(code) > 16384:
            raise ValueError()
        value = json.loads(base64.b64decode(code + "=" * (-len(code) % 4), altchars=b"-_", validate=True))
        if not isinstance(value, dict) or value.get("version") != 1:
            raise ValueError()
        url = urlsplit(value["centralUrl"])
        if (url.scheme not in ("http", "https") or not url.hostname or url.username
                or url.password or url.path not in ("", "/") or url.query or url.fragment
                or url.port == 0):
            raise ValueError()
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}", value["memberId"]):
            raise ValueError()
        if not isinstance(value["memberName"], str) or not 1 <= len(value["memberName"].strip()) <= 80:
            raise ValueError()
        if not re.fullmatch(r"[a-f0-9]{64}", value["accountFingerprint"]):
            raise ValueError()
        secret = value["secret"]
        if not isinstance(secret, str) or not 16 <= len(secret) <= 512 or "\r" in secret or "\n" in secret:
            raise ValueError()
        return value
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValueError("接入配置无效或不完整，请重新复制汇总中心为你生成的配置。") from None


class HubProbe(QObject):
    checked = pyqtSignal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.network = QNetworkAccessManager(self)
        self.network.setProxy(QNetworkProxy(QNetworkProxy.NoProxy))
        self.reply = None
        self.callback = None

    def check(self, invitation):
        self.cancel()
        request = QNetworkRequest(QUrl(invitation["centralUrl"].rstrip("/") + "/api/team"))
        request.setRawHeader(b"Authorization", b"Bearer " + invitation["secret"].encode())
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.ManualRedirectPolicy)
        request.setTransferTimeout(8000)
        self.reply = self.network.get(request)
        reply = self.reply

        def done():
            try:
                status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
                if status in (401, 403):
                    raise ValueError("中心拒绝了接入配置，请重新获取该成员的邀请。")
                if reply.error() or status != 200:
                    raise ValueError("无法连接中心。请检查双方 Tailscale 已连接、设备共享已接受，以及中心正在运行并允许其他设备连接。")
                data = json.loads(bytes(reply.readAll()).decode("utf-8"))
                if not data.get("enabled") or data.get("role") != "server":
                    raise ValueError("这个地址不是已启用的汇总中心。")
                if data.get("accountFingerprint") != invitation["accountFingerprint"]:
                    raise ValueError("中心绑定的 OpenAI 账号与接入配置不一致，请重新获取配置。")
                if not any(m.get("id") == invitation["memberId"] for m in data.get("members", [])):
                    raise ValueError("该成员已不在中心登记，请重新添加并生成邀请。")
                self.checked.emit(True, "连接成功，成员与账号范围已确认。保存后会开始同步用量。")
            except (ValueError, TypeError, AttributeError) as error:
                message = str(error) if isinstance(error, ValueError) and str(error).startswith(("中心", "无法", "这个", "该成员")) else "中心响应无效，请确认地址指向统计工具的汇总中心。"
                self.checked.emit(False, message)
            finally:
                reply.deleteLater()
                if self.reply is reply:
                    self.reply = None
                    self.callback = None

        self.callback = done
        reply.finished.connect(done)

    def cancel(self):
        if self.reply is not None:
            reply, self.reply = self.reply, None
            if self.callback is not None:
                reply.finished.disconnect(self.callback)
            self.callback = None
            reply.abort()
            reply.deleteLater()
