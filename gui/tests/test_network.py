"""Network onboarding uses isolated processes/HTTP fixtures, never real accounts."""

import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PyQt5.QtCore import Qt, QEvent, QCoreApplication, QSettings
from PyQt5.QtTest import QTest
from gui.main import create_app
from gui.connection import HubProbe, parse_invitation
from gui.tailscale import TailscalePanel, status_summary, hub_address, find_cli, install_command
from gui.team import MembersDialog

INVITE = {"version": 1, "memberId": "alice", "memberName": "Alice",
          "centralUrl": "http://100.100.10.20:8893",
          "accountFingerprint": "a" * 64, "secret": "synthetic-network-test-key"}


def encode(value):
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


class NetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="tracker-network-ui-")
        self.addCleanup(directory.cleanup)
        settings = QSettings(str(Path(directory.name) / "preferences.ini"), QSettings.IniFormat)
        patcher = patch("gui.team.QSettings", return_value=settings)
        patcher.start()
        self.addCleanup(patcher.stop)

    def wait_for(self, predicate):
        end = time.monotonic() + 4
        while time.monotonic() < end:
            self.app.processEvents()
            QTest.qWait(15)
            if predicate():
                return
        self.fail("Timed out waiting for native network operation")

    def tearDown(self):
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_tailscale_states_never_offer_offline_or_unapproved_address(self):
        for state in ["NeedsLogin", "Stopped", "NeedsMachineAuth", "Starting"]:
            result = status_summary({"BackendState": state, "TailscaleIPs": ["100.100.1.2"]})
            self.assertFalse(result["online"])
            self.assertEqual(result["address"], "")
        result = status_summary({"BackendState": "Running", "Self": {"TailscaleIPs": ["100.100.1.2"]}}, 9999)
        self.assertEqual(result["address"], "http://100.100.1.2:9999")
        self.assertFalse(status_summary({"BackendState": "Running", "TailscaleIPs": ["192.168.1.2"]})["online"])

    def test_invitation_rejects_corrupt_payload_and_accepts_copied_instructions(self):
        self.assertEqual(parse_invitation("步骤说明\n接入配置：\n" + encode(INVITE) + "\n请勿公开"), INVITE)
        for changes in [{"secret":"short"}, {"accountFingerprint":"wrong"}, {"version":2},
                        {"centralUrl":"file:///tmp/x"}, {"centralUrl":"https://user:pass@hub"},
                        {"centralUrl":"http://hub:0"}, {"memberId":"../other"}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                parse_invitation(encode({**INVITE, **changes}))
        for raw in ["", "broken-text", encode([]), "a" * 20000]:
            with self.assertRaises(ValueError):
                parse_invitation(raw)

    def test_invite_address_rejects_loopback_and_credentials(self):
        for value in ["http://127.0.0.1:8893", "http://localhost:8893", "http://[::1]:8893",
                      "http://0.0.0.0:8893", "http://[::]:8893", "file:///tmp/x",
                      "http://user:pass@host", "http://host/path", "http://host:0"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                hub_address(value)
        self.assertEqual(hub_address(" http://100.100.1.2:8893/ "), "http://100.100.1.2:8893")
        self.assertEqual(hub_address("https://hub.example.ts.net"), "https://hub.example.ts.net")

    def test_missing_client_and_closed_panel_do_not_spawn_processes(self):
        with patch("gui.tailscale.find_cli", return_value=None):
            panel = TailscalePanel()
            panel.refresh()
            self.assertIn("未安装", panel.status.text())
            self.assertFalse(panel.connect_button.isEnabled())
            panel.shutdown()
            with patch.object(panel, "run") as run:
                panel.refresh()
                self.assertFalse(run.called)
            panel.deleteLater()

    def test_async_cli_parses_status_without_blocking_and_times_out(self):
        with patch("gui.tailscale.find_cli", return_value=None):
            panel = TailscalePanel()
            self.app.processEvents()
            seen = []
            panel.address_ready.connect(seen.append)
            data = json.dumps({"BackendState":"Running", "TailscaleIPs":["100.90.80.70"]})
            panel.run([sys.executable, "-c", f"print({data!r})"], "status", 3000)
            self.wait_for(lambda: panel.process is None)
            self.assertEqual(panel.address.text(), "http://100.90.80.70:8893")
            self.assertIn(panel.address.text(), seen)
            panel.run([sys.executable, "-c", "import time; time.sleep(10)"], "status", 30)
            self.wait_for(lambda: panel.process is None)
            self.assertEqual(panel.address.text(), "")
            panel.shutdown()
            panel.deleteLater()

    def test_login_opens_only_official_authorization_url(self):
        with patch("gui.tailscale.find_cli", return_value=None), patch("gui.tailscale.QDesktopServices.openUrl") as opened:
            panel = TailscalePanel()
            self.app.processEvents()
            panel.run([sys.executable, "-c", 'import sys;print(\'{"AuthURL":"https://login.tailscale.com/a/synthetic"}\');sys.exit(1)'], "connect", 3000)
            self.wait_for(lambda: panel.process is None)
            self.assertEqual(opened.call_args.args[0].host(), "login.tailscale.com")
            opened.reset_mock()
            panel.auth_url = "https://other.example/a/synthetic"
            panel.open_login()
            self.assertFalse(opened.called)
            panel.shutdown()
            panel.deleteLater()

    def test_windows_cli_detection_and_installer_command(self):
        with patch("gui.tailscale.sys.platform", "win32"), patch("gui.tailscale.shutil.which", return_value=None), patch("gui.tailscale.Path.is_file", return_value=True):
            self.assertTrue(find_cli().endswith("tailscale.exe"))
        with patch("gui.tailscale.sys.platform", "win32"), patch("gui.tailscale.shutil.which", return_value="winget.exe"):
            command = install_command()
            self.assertEqual(command[0], "winget.exe")
            self.assertIn("Tailscale.Tailscale", command)

    def test_connection_probe_checks_account_member_and_auth_and_does_not_follow_redirects(self):
        class Handler(BaseHTTPRequestHandler):
            status = 200
            fingerprint = INVITE["accountFingerprint"]
            members = [{"id":"alice"}]
            calls = []

            def log_message(self, *_):
                pass

            def do_GET(self):
                type(self).calls.append((self.path, self.headers.get("Authorization")))
                self.send_response(self.status)
                if self.status == 302:
                    self.send_header("Location", "/must-not-follow")
                self.end_headers()
                value = {"enabled":True, "role":"server", "accountFingerprint":self.fingerprint, "members":self.members}
                self.wfile.write(json.dumps(value).encode())

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        probe = HubProbe()
        seen = []
        probe.checked.connect(lambda ok, message: seen.append((ok, message)))
        invitation = {**INVITE, "centralUrl":f"http://127.0.0.1:{server.server_port}"}
        try:
            for status, fingerprint, members, expected in [
                (200, "a"*64, [{"id":"alice"}], True),
                (200, "b"*64, [{"id":"alice"}], False),
                (200, "a"*64, [], False), (401, "a"*64, [], False),
                (302, "a"*64, [], False),
            ]:
                Handler.status, Handler.fingerprint, Handler.members = status, fingerprint, members
                seen.clear()
                probe.check(invitation)
                self.wait_for(lambda: bool(seen))
                self.assertEqual(seen[0][0], expected)
            self.assertEqual(len(Handler.calls), 5)
            self.assertTrue(all(p == "/api/team" and auth == "Bearer " + INVITE["secret"] for p, auth in Handler.calls))
        finally:
            probe.cancel()
            probe.deleteLater()
            server.shutdown()
            server.server_close()
            thread.join()

    def make_members(self, remote=True):
        people = [{"id":"alice", "name":"Alice"}, {"id":"bob", "name":"Bob"}]
        report = {"members":[dict(m,week=10,month=20,total=30) for m in people],
                  "devices":[{"memberId":"alice", "label":"Ubuntu", "online":True,"pending":0}]}
        def api(_url, path, *args, **kwargs):
            if path == "/api/team":
                return {"members":people,"selfMemberId":"alice", "acceptsRemote":remote}
            if path == "/api/team/reports":
                return report
            return {"invitation":encode(INVITE)}
        return api

    def test_member_search_devices_delete_protection_and_invite_invalidation(self):
        with patch("gui.team.api",side_effect=self.make_members()), patch("gui.tailscale.find_cli",return_value=None):
            d = MembersDialog("http://127.0.0.1:18993")
            self.addCleanup(d.deleteLater)
            self.addCleanup(d.close)
            self.assertEqual(d.devices.rowCount(), 1)
            self.assertFalse(d.delete_button.isEnabled())
            d.select_member("bob")
            self.assertTrue(d.delete_button.isEnabled())
            d.address.setText("http://100.100.10.20:8893")
            d.copy_invitation()
            self.assertTrue(d.code.toPlainText())
            d.select_member("alice")
            self.assertEqual(d.code.toPlainText(), "")
            d.search.setText("bob")
            self.assertEqual(d.current_member(), "bob")
            d.search.setText("nobody")
            self.assertIsNone(d.current_member())
            self.assertFalse(d.invite_button.isEnabled())

    def test_network_address_autofill_preserves_manual_address_and_requires_remote_listener(self):
        with patch("gui.team.api",side_effect=self.make_members(False)), patch("gui.tailscale.find_cli",return_value=None):
            d = MembersDialog("http://127.0.0.1:18994")
            self.addCleanup(d.deleteLater)
            self.addCleanup(d.close)
            d.address.clear()
            d.network_changed("http://100.100.10.20:8893")
            self.assertEqual(d.address.text(), "http://100.100.10.20:8893")
            self.assertFalse(d.invite_button.isEnabled())
            d.address.setText("http://custom-hub:8893")
            d.network_changed("http://100.100.10.30:8893")
            self.assertEqual(d.address.text(), "http://custom-hub:8893")

    def test_invitation_instructions_can_be_pasted_into_connection_dialog(self):
        with patch("gui.team.api",side_effect=self.make_members()), patch("gui.tailscale.find_cli",return_value=None):
            d = MembersDialog("http://127.0.0.1:18995")
            self.addCleanup(d.deleteLater)
            self.addCleanup(d.close)
            d.address.setText(INVITE["centralUrl"])
            d.copy_instructions()
            instructions = self.app.clipboard().text()
            self.assertEqual(parse_invitation(instructions), INVITE)

