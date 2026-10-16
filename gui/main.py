"""Native Codex tracker entrypoint. Launch the backend and open the Qt window."""

from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont, QFontDatabase, QPalette
from PyQt5.QtWidgets import QApplication, QMessageBox
from qfluentwidgets import (
    ComboBox as FluentComboBox,
    setTheme,
    setThemeColor,
    setFontFamilies,
    Theme,
)

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gui.window import UsageWindow
from gui.team import ConnectionDialog, MembersDialog
from gui.ui import STYLE
from gui.utils import ROOT, DEFAULT_URL, compact, period_end

NETWORK_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def backend_is_ready(url: str) -> bool:
    try:
        with NETWORK_OPENER.open(url + "/api/health", timeout=1) as response:
            health = json.load(response)
        with NETWORK_OPENER.open(
            url + "/api/overview?provider=codex", timeout=2
        ) as response:
            scope = json.load(response)
        return bool(
            health.get("ok")
            and (
                (health.get("role") == "server" and not health.get("scanLocal", True))
                or (
                    scope.get("trackingScope") == "local"
                    and scope.get("accountScope", {}).get("enabled")
                )
            )
        )
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
            if auth.get("auth_mode") == "chatgpt" and auth.get("tokens", {}).get(
                "account_id"
            ):
                eligible.append(p)
        except (OSError, ValueError):
            pass
    data = (
        Path(env.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
        / "CodexUsageTracker"
        / "data-current-account"
    )
    profile = data / "installation.json"
    headless = (
        profile.is_file()
        and json.loads(profile.read_text(encoding="utf-8")).get("scanLocal") is False
    )
    if not eligible and not headless:
        raise RuntimeError(
            "请先在 Codex 桌面端或 CLI 中通过 OpenAI 账号登录，再打开统计工具。"
        )
    primary = eligible[0] if eligible else candidates[0]
    data.mkdir(parents=True, exist_ok=True)
    env.update(
        {
            "TRACKER_ROLE": "standalone",
            "HOST": "127.0.0.1",
            "PORT": "8893",
            "CODEX": "true",
            "WATCH_SESSIONS": "true",
            "DATA_DIR": str(data),
            "CODEX_HOME": str(primary),
            "CODEX_EXTRA_HOMES": os.pathsep.join(str(p) for p in homes if p != primary),
        }
    )
    return env


def ensure_backend(url: str) -> None:
    if backend_is_ready(url):
        return
    if sys.platform == "win32":
        node = shutil.which("node")
        if not node or not (ROOT / "dist-server" / "index.js").is_file():
            raise RuntimeError(
                "请先双击 scripts\\install-native-windows.cmd 完成安装。"
            )
        env = windows_backend_environment()
        log_dir = Path(env["DATA_DIR"])
        with (log_dir / "backend.log").open("ab") as log:
            subprocess.Popen(
                [node, str(ROOT / "dist-server" / "index.js")],
                cwd=str(ROOT),
                env=env,
                stdout=log,
                stderr=log,
                stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
            )
    elif sys.platform.startswith("linux"):
        subprocess.run(
            ["systemctl", "--user", "start", "ai-usage-tracker.service"],
            check=True,
            timeout=15,
        )
    else:
        raise RuntimeError("请先启动本机的 Codex 用量后台服务。")
    for _ in range(60):
        if backend_is_ready(url):
            return
        time.sleep(0.25)
    raise RuntimeError("本机后台未就绪，请检查 ai-usage-tracker 服务或 backend.log。")


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
    setThemeColor("#357a69")
    available = set(QFontDatabase().families())
    choices = (
        ["Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans CJK SC"]
        if sys.platform == "win32"
        else ["Noto Sans CJK SC", "Noto Sans SC", "Microsoft YaHei UI"]
    )
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
                folder = (
                    Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
                    / "CodexUsageTracker"
                )
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
