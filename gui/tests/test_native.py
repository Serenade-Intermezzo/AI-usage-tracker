"""Native widget tests against an isolated data fixture, never the user's ledger."""

import copy
import base64
import gc
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import Qt, QEvent, QCoreApplication
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QComboBox, QTableWidget

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from gui import main as gui

APP = None


def reports(day):
    return {
        "monthStartDay": day,
        "generatedAt": 1,
        "firstEventAt": 1,
        "weekly": [
            {
                "start": "2026-10-12",
                "endExclusive": "2026-10-19",
                "status": "open",
                "total": 123456,
                "input": 120000,
                "cached": 110000,
                "output": 3456,
                "chats": 2,
            }
        ],
        "monthly": [
            {
                "start": f"2026-10-{day:02}",
                "endExclusive": f"2026-11-{min(day,30):02}",
                "status": "open",
                "total": 123456,
                "input": 120000,
                "cached": 110000,
                "output": 3456,
                "chats": 2,
            }
        ],
    }


OVERVIEW = {
    "trackingScope": "local",
    "accountScope": {
        "enabled": True,
        "homes": [{"matches": True}],
        "unverifiedFiles": 5,
        "otherProviderFiles": 2,
        "otherAccountFiles": 1,
        "note": "Unverified history is excluded.",
    },
    "localDailyUsage": [
        {
            "date": datetime.now(timezone(timedelta(hours=8))).date().isoformat(),
            "tokens": 123456,
        }
    ],
    "hourlyActivity": [
        [100 if d == 1 and h == 9 else 0 for h in range(24)] for d in range(7)
    ],
    "modelUsage": [
        {
            "model": "test-model",
            "totalTokens": 123456,
            "inputTokens": 120000,
            "cachedInputTokens": 110000,
            "outputTokens": 3456,
        }
    ],
    "threads": [
        {
            "title": "sample chat",
            "source": "cli",
            "primaryModel": "test-model",
            "totalTokens": 123456,
        }
    ],
}


class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global APP
        APP = gui.create_app()
        cls.directory = tempfile.TemporaryDirectory(prefix="tracker-native-test-")
        cls.settings = Path(cls.directory.name) / "settings.json"
        cls.settings.write_text('{"day":12}')
        cls.fail_reports = False
        cls.team_enabled = False
        cls.requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def send_json(self, value, status=200):
                raw = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                cls.requests.append(("GET", self.path))
                if self.path == "/api/team":
                    return self.send_json(
                        {
                            "enabled": cls.team_enabled,
                            "role": "server" if cls.team_enabled else "standalone",
                            "canManage": cls.team_enabled,
                            "members": (
                                [
                                    {"id": "alice", "name": "Alice"},
                                    {"id": "bob", "name": "Bob"},
                                ]
                                if cls.team_enabled
                                else []
                            ),
                        }
                    )
                if self.path.startswith("/api/team/reports"):
                    value = reports(json.loads(cls.settings.read_text())["day"])
                    value.update(
                        scope="team",
                        canEditMonthDay=True,
                        incomplete=True,
                        overview=copy.deepcopy(OVERVIEW),
                        members=[
                            {
                                "id": "alice",
                                "name": "Alice",
                                "week": 100,
                                "month": 100,
                                "total": 100,
                                "devices": 2,
                            },
                            {
                                "id": "bob",
                                "name": "Bob",
                                "week": 200,
                                "month": 200,
                                "total": 200,
                                "devices": 1,
                            },
                        ],
                        devices=[
                            {
                                "deviceId": "a1",
                                "memberId": "alice",
                                "label": "Ubuntu",
                                "online": False,
                                "pending": 5,
                                "lastSeenAt": None,
                            }
                        ],
                    )
                    if "memberId=alice" in self.path:
                        value["weekly"][0]["total"] = 100
                    return self.send_json(value)
                if self.path == "/api/installation":
                    return self.send_json(
                        {
                            "role": "standalone",
                            "memberId": "owner",
                            "memberName": "Me",
                            "deviceLabel": "Ubuntu",
                            "listenHost": "127.0.0.1",
                        }
                    )
                if self.path == "/api/local-reports":
                    if cls.fail_reports:
                        return self.send_json(
                            {"error": "temporary fixture outage"}, 503
                        )
                    return self.send_json(
                        reports(json.loads(cls.settings.read_text())["day"])
                    )
                if self.path.startswith("/api/overview"):
                    return self.send_json(copy.deepcopy(OVERVIEW))
                return self.send_json({"error": "unexpected path"}, 404)

            def do_PUT(self):
                cls.requests.append(("PUT", self.path))
                value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                day = value.get("monthStartDay")
                if (
                    self.path != "/api/local-reports/settings"
                    or type(day) is not int
                    or not 1 <= day <= 31
                ):
                    return self.send_json({"error": "bad setting"}, 400)
                cls.settings.write_text(json.dumps({"day": day}))
                return self.send_json(reports(day))

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.directory.cleanup()
        # Destroy native charts while Qt is alive, before Python tears down wrappers.
        for widget in QApplication.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        APP.processEvents()
        gc.collect()

    def wait_for(self, predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            APP.processEvents()
            QTest.qWait(15)
            if predicate():
                return
        self.fail("Timed out waiting for native GUI update")

    def window(self):
        w = gui.UsageWindow(self.url)
        w.show()
        self.addCleanup(w.close)
        self.wait_for(
            lambda: bool(w.reports)
            and (bool(w.overview) or w.reports.get("scope") == "team")
            and not w.pending_team
        )
        w.timer.stop()
        return w

    def test_native_controls_load_data_and_tabs(self):
        w = self.window()
        self.assertIsInstance(w.report_table, QTableWidget)
        self.assertIsInstance(w.month_day, gui.FluentComboBox)
        self.assertEqual(w.chat_table.item(0, 1).text(), "CLI")
        self.assertFalse(w.save_button.isEnabled())
        QTest.mouseClick(w.month_button, Qt.LeftButton)
        self.assertEqual(w.mode, "monthly")
        QTest.mouseClick(w.chat_tab.itemWidget, Qt.LeftButton)
        self.assertEqual(w.stack.currentIndex(), 1)
        QTest.mouseClick(w.report_tab.itemWidget, Qt.LeftButton)
        self.assertEqual(w.stack.currentIndex(), 0)
        QTest.mouseClick(w.chart_tab.itemWidget, Qt.LeftButton)
        self.assertEqual(w.stack.currentIndex(), 2)
        self.assertEqual(len(w.charts.daily.rows), 14)
        QTest.mouseClick(w.detail_button, Qt.LeftButton)
        self.assertTrue(w.details.isVisible())
        self.assertNotIn("WebEngine", str(type(w.report_table)))

    def test_native_charts_fonts_and_request_callback_lifetimes(self):
        w = self.window()
        self.assertEqual(len(w.charts.daily.rows), 14)
        self.assertEqual(sum(r["tokens"] for r in w.charts.daily.rows), 123456)
        self.assertEqual(w.charts.activity.grid[1][9], 100)
        self.assertEqual(len(w.charts.models.rows), 1)
        self.assertGreaterEqual(w.report_table.font().pixelSize(), 16)
        self.assertGreaterEqual(w.report_table.item(0, 0).font().pixelSize(), 16)
        for _ in range(3):
            w.refresh()
            gc.collect()
            self.wait_for(lambda: not w.pending_reports and not w.pending_overview)
            self.assertFalse(w.active_requests)
        self.assertFalse(any("WebEngine" in name for name in sys.modules))

    def test_month_day_save_refresh_and_reopen_preserve_setting(self):
        w = self.window()
        w.month_day.setCurrentIndex(30)
        self.assertTrue(w.save_button.isEnabled())
        QTest.mouseClick(w.save_button, Qt.LeftButton)
        self.wait_for(lambda: w.reports["monthStartDay"] == 31 and not w.pending_save)
        self.assertEqual(w.mode, "monthly")
        self.assertIn("已保存", w.hint.text())
        self.assertEqual(json.loads(self.settings.read_text())["day"], 31)
        self.assertFalse(w.save_button.isEnabled())
        w.refresh()
        self.wait_for(lambda: not w.pending_reports and not w.pending_overview)
        self.assertEqual(w.month_day.currentIndex(), 30)
        another = self.window()
        self.assertEqual(another.month_day.currentIndex(), 30)
        self.assertIn(("PUT", "/api/local-reports/settings"), self.requests)

    def test_closing_window_cancels_pending_gui_requests(self):
        w = self.window()
        w.refresh()
        self.assertTrue(w.active_requests)
        w.close()
        APP.processEvents()
        self.assertFalse(w.active_requests)
        self.assertFalse(w.timer.isActive())

    def test_unsaved_draft_survives_refresh(self):
        w = self.window()
        w.month_day.setCurrentIndex(15)
        w.refresh()
        self.wait_for(lambda: not w.pending_reports and not w.pending_overview)
        self.assertEqual(w.month_day.currentIndex(), 15)
        self.assertTrue(w.save_button.isEnabled())

    def test_transient_backend_error_recovers(self):
        w = self.window()
        type(self).fail_reports = True
        try:
            w.refresh()
            self.wait_for(lambda: bool(w.request_errors))
            self.assertIn("更新失败", w.hint.text())
        finally:
            type(self).fail_reports = False
        w.refresh()
        self.wait_for(lambda: not w.pending_reports and not w.pending_overview)
        self.assertFalse(w.request_errors)
        self.assertNotIn("更新失败", w.hint.text())
        self.assertEqual(w.status.text(), "当前账号 · 仅本机")

    def test_team_scope_person_reports_and_native_member_device_tables(self):
        type(self).team_enabled = True
        try:
            w = self.window()
            self.wait_for(
                lambda: w.reports.get("scope") == "team"
                and not w.pending_reports
                and not w.pending_team
            )
            self.assertEqual(w.scope_id, "all")
            self.assertTrue(w.manage_button.isEnabled())
            self.assertFalse(w.chat_tab.isEnabled())
            self.assertEqual(w.member_table.rowCount(), 2)
            self.assertEqual(w.device_table.item(0, 2).text(), "离线")
            self.assertIn("部分设备", w.hint.text())
            index = w.scope.findData("alice")
            self.assertGreater(index, 0)
            w.scope.setCurrentIndex(index)
            self.wait_for(lambda: w.reports.get("weekly", [{}])[0].get("total") == 100)
            QTest.mouseClick(w.team_tab.itemWidget, Qt.LeftButton)
            self.assertEqual(w.stack.currentIndex(), 3)
            w.scope.setCurrentIndex(w.scope.findData("local"))
            self.wait_for(lambda: w.reports.get("scope") != "team" and bool(w.reports))
            self.assertTrue(w.chat_tab.isEnabled())
        finally:
            type(self).team_enabled = False

    def test_connection_dialog_uses_native_configuration_controls(self):
        d = gui.ConnectionDialog(self.url)
        self.addCleanup(d.close)
        self.assertEqual(d.role.currentIndex(), 0)
        d.role.setCurrentIndex(2)
        self.assertTrue(d.invitation.isEnabled())
        self.assertFalse(d.lan.isEnabled())
        d.role.setCurrentIndex(1)
        self.assertTrue(d.lan.isEnabled())
        self.assertFalse(d.invitation.isEnabled())
        self.assertFalse(d.fingerprint.isEnabled())
        d.scan.setChecked(False)
        self.assertTrue(d.fingerprint.isEnabled())

    def test_overview_shows_the_same_scope_totals_and_native_sidebar(self):
        w = self.window()
        self.assertEqual(w.stack.currentIndex(), 4)
        self.assertEqual(
            w.home_amounts[2].text(), gui.compact(w.reports["monthly"][0]["total"])
        )
        self.assertEqual(len(w.home_daily.rows), 7)
        self.assertGreaterEqual(w.nav.width(), 170)
        QTest.mouseClick(w.report_tab.itemWidget, Qt.LeftButton)
        self.assertEqual(w.stack.currentIndex(), 0)
        QTest.mouseClick(w.home_tab.itemWidget, Qt.LeftButton)
        self.assertEqual(w.stack.currentIndex(), 4)

    def test_standard_window_controls_minimize_maximize_restore_and_close(self):
        w = self.window()
        self.prepare_normal_window(w)
        original = w.size()
        self.assertTrue(w.titlebar.minimize_button.isVisible())
        self.assertTrue(w.titlebar.maximize_button.isVisible())
        self.assertTrue(w.titlebar.close_button.isVisible())
        QTest.mouseClick(w.titlebar.maximize_button, Qt.LeftButton)
        self.wait_for(w.isMaximized)
        self.wait_for(lambda: w.geometry() == w.screen().availableGeometry())
        for page in range(w.stack.count()):
            w.show_page(page)
            APP.processEvents()
            self.assertEqual(w.geometry(), w.screen().availableGeometry())
        self.assertEqual(w.titlebar.maximize_button.toolTip(), "还原")
        QTest.mouseClick(w.titlebar.maximize_button, Qt.LeftButton)
        self.wait_for(lambda: not w.isMaximized())
        self.wait_for(lambda: w.size() == original)
        self.assertEqual(w.titlebar.maximize_button.toolTip(), "最大化")
        QTest.mouseClick(w.titlebar.minimize_button, Qt.LeftButton)
        self.wait_for(w.isMinimized)
        QTest.qWait(250)
        w.showNormal()
        w.activateWindow()
        self.wait_for(lambda: not w.isMinimized())
        QTest.mouseClick(w.titlebar.close_button, Qt.LeftButton)
        self.assertFalse(w.isVisible())
        self.assertFalse(w.timer.isActive())
        self.assertFalse(w.active_requests)

    def test_fullscreen_covers_screen_and_restores_normal_and_maximized(self):
        w = self.window()
        self.prepare_normal_window(w)
        w.activateWindow()
        QTest.qWait(100)
        original = w.geometry()
        QTest.keyClick(w, Qt.Key_F11)
        self.wait_for(w.isFullScreen)
        self.wait_for(lambda: w.geometry() == w.screen().geometry())
        self.assertEqual(w.titlebar.maximize_button.toolTip(), "还原")
        QTest.keyClick(w, Qt.Key_Escape)
        self.wait_for(lambda: not w.isFullScreen())
        self.wait_for(lambda: w.geometry() == original)
        self.assertFalse(w.isMaximized())
        w.showMaximized()
        self.wait_for(lambda: w.geometry() == w.screen().availableGeometry())

        QTest.keyClick(w, Qt.Key_F11)
        self.wait_for(lambda: w.isFullScreen() and w.geometry() == w.screen().geometry())
        QTest.keyClick(w, Qt.Key_F11)
        self.wait_for(lambda: w.isMaximized() and not w.isFullScreen())
        self.wait_for(lambda: w.geometry() == w.screen().availableGeometry())
        w.titlebar.toggle_fullscreen()
        self.wait_for(w.isFullScreen)
        QTest.mouseClick(w.titlebar.maximize_button, Qt.LeftButton)
        self.wait_for(lambda: w.isMaximized() and not w.isFullScreen())
        self.wait_for(lambda: w.geometry() == w.screen().availableGeometry())

    def prepare_normal_window(self, w):
        # Desktop policies may initially maximize newly opened application windows.
        QTest.qWait(250)
        w.showNormal()
        self.wait_for(lambda: not w.isMaximized())
        available = w.screen().availableGeometry()
        w.resize(min(980, available.width() - 40), min(620, available.height() - 40))
        QTest.qWait(250)

    def test_member_pie_uses_all_members_and_switches_month_week_lifetime(self):
        w = self.window()
        pie = w.charts.pie
        pie.set_members(
            [
                {"id": "a", "name": "Alice", "month": 100, "week": 50, "total": 700},
                {"id": "b", "name": "Bob", "month": 300, "week": 50, "total": 300},
            ]
        )
        self.assertEqual(pie.total, 400)
        self.assertEqual([s.value() for s in pie.series.slices()], [300, 100])
        self.assertAlmostEqual(pie.series.slices()[0].percentage(), 0.75)
        pie.period_combo.setCurrentIndex(pie.period_combo.findData("week"))
        self.assertEqual(pie.total, 100)
        self.assertEqual([s.value() for s in pie.series.slices()], [50, 50])
        pie.period_combo.setCurrentIndex(pie.period_combo.findData("total"))
        self.assertEqual(pie.total, 1000)
        pie.set_members(
            [{"id": "zero", "name": "No usage", "month": 0, "week": 0, "total": 0}]
        )
        self.assertEqual(pie.series.count(), 0)
        self.assertEqual(pie.total, 0)
        self.assertFalse(w.subtitle.isVisible())

    def test_collector_calendar_is_readonly_and_updates_even_with_an_old_draft(self):
        w = self.window()
        w.month_day.setCurrentIndex(15)
        data = reports(12)
        data["canEditMonthDay"] = False
        w.update_reports(data)
        self.assertEqual(w.month_day.currentIndex(), 11)
        self.assertFalse(w.month_day.isEnabled())
        self.assertFalse(w.save_button.isEnabled())

    def test_overview_healthy_device_coverage_has_no_false_warning(self):
        w = self.window()
        value = reports(12)
        value.update(
            scope="team",
            members=[
                {
                    "id": "a",
                    "name": "A",
                    "month": 100,
                    "week": 100,
                    "total": 100,
                    "devices": 1,
                }
            ],
            overview={},
            incomplete=False,
            devices=[
                {
                    "deviceId": "one",
                    "memberId": "a",
                    "label": "Ubuntu",
                    "online": True,
                    "pending": 0,
                    "syncedThrough": 100,
                    "lastSeenAt": 100,
                    "lastError": None,
                }
            ],
        )
        w.update_reports(value)
        self.assertIn("设备已同步", w.coverage_notice.text())
        self.assertEqual(len(w.contributions.members), 1)

    def test_native_connection_dialog_submits_member_invitation(self):
        invitation = {
            "version": 1,
            "memberId": "member-1",
            "memberName": "测试成员",
            "centralUrl": "http://hub:8893",
            "secret": "synthetic-private-test-key",
            "accountFingerprint": "a" * 64,
        }
        code = (
            base64.urlsafe_b64encode(json.dumps(invitation).encode())
            .decode()
            .rstrip("=")
        )
        profile = {
            "role": "standalone",
            "memberId": "local",
            "memberName": "Me",
            "deviceLabel": "Ubuntu",
            "listenHost": "127.0.0.1",
        }
        with patch("gui.team.api", side_effect=[profile, {"ok": True}]) as calls:
            d = gui.ConnectionDialog(self.url)
            self.addCleanup(d.close)
            d.role.setCurrentIndex(2)
            d.invitation.setPlainText(code)
            d.device.setText("Windows laptop")
            d.save()
            saved = calls.call_args.args[2]
            self.assertEqual(saved["memberId"], "member-1")
            self.assertEqual(saved["memberName"], "测试成员")
            self.assertEqual(saved["deviceLabel"], "Windows laptop")
            self.assertEqual(saved["role"], "collector")
            self.assertEqual(d.result(), d.Accepted)

    def test_native_member_manager_generates_selected_person_invitation(self):
        fixture = {
            "members": [{"id": "alice", "name": "Alice"}, {"id": "bob", "name": "Bob"}]
        }
        def member_api(_url, path, *args):
            if path == "/api/team":
                return fixture
            if path == "/api/team/reports":
                return {"members": [], "devices": []}
            return {"invitation": "synthetic-invitation"}
        with patch(
            "gui.team.api",
            side_effect=member_api,
        ) as calls:
            d = gui.MembersDialog(self.url)
            self.addCleanup(d.close)
            d.select_member("bob")
            d.address.setText("http://192.168.1.10:8893")
            d.copy_invitation()
            self.assertIn("memberId=bob", calls.call_args.args[1])
            self.assertEqual(d.code.toPlainText(), "synthetic-invitation")
            self.assertEqual(APP.clipboard().text(), "synthetic-invitation")


class EnvironmentTests(unittest.TestCase):
    def test_windows_environment_selects_chatgpt_home_and_private_data_directory(
        self,
    ):
        with tempfile.TemporaryDirectory(prefix="tracker-path-中文 space-") as temp:
            home = Path(temp)
            desktop = home / ".codex-desktop"
            cli = home / ".codex"
            desktop.mkdir()
            cli.mkdir()
            (desktop / "auth.json").write_text(
                json.dumps(
                    {
                        "auth_mode": "chatgpt",
                        "tokens": {"account_id": "fixture-account"},
                    }
                )
            )
            (cli / "auth.json").write_text(json.dumps({"auth_mode": "apikey"}))
            with patch.object(gui.Path, "home", return_value=home), patch.dict(
                os.environ, {"LOCALAPPDATA": str(home / "Local data")}, clear=True
            ):
                env = gui.windows_backend_environment()
            self.assertEqual(env["CODEX_HOME"], str(desktop))
            self.assertNotIn("CLAUDE_CODE", env)
            self.assertNotIn("QUOTA_POLLING", env)
            self.assertNotIn("NATIVE_GUI_ONLY", env)
            self.assertEqual(env["WATCH_SESSIONS"], "true")
            self.assertTrue(Path(env["DATA_DIR"]).is_dir())
            self.assertNotIn(
                "auth.json", ",".join(p.name for p in Path(env["DATA_DIR"]).iterdir())
            )

    def test_missing_chatgpt_login_is_not_treated_as_current_account(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(gui.Path, "home", return_value=Path(temp)), patch.dict(
                os.environ, {}, clear=True
            ):
                with self.assertRaises(RuntimeError):
                    gui.windows_backend_environment()

    def test_period_end_handles_month_and_year_boundaries(self):
        self.assertEqual(gui.period_end("2027-01-01"), "2026-12-31")
        self.assertEqual(gui.period_end("2028-03-01"), "2028-02-29")


if __name__ == "__main__":
    unittest.main()
