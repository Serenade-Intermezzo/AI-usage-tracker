"""Native widget tests against an isolated data fixture, never the user's ledger."""
import copy
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

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QComboBox, QTableWidget

import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from gui import main as gui
APP = None


def reports(day):
    return {'monthStartDay': day, 'generatedAt': 1, 'firstEventAt': 1,
            'weekly': [{'start': '2026-10-12', 'endExclusive': '2026-10-19', 'status': 'open', 'total': 123456,
                        'input': 120000, 'cached': 110000, 'output': 3456, 'chats': 2}],
            'monthly': [{'start': f'2026-10-{day:02}', 'endExclusive': f'2026-11-{min(day,30):02}',
                         'status': 'open', 'total': 123456, 'input': 120000, 'cached': 110000, 'output': 3456, 'chats': 2}]}


OVERVIEW = {'trackingScope':'local', 'accountScope': {'enabled':True,'homes':[{'matches':True}], 'unverifiedFiles':5,
            'otherProviderFiles':2, 'otherAccountFiles':1, 'note':'Unverified history is excluded.'},
            'localDailyUsage':[{'date':datetime.now(timezone(timedelta(hours=8))).date().isoformat(),'tokens':123456}],
            'hourlyActivity':[[100 if d==1 and h==9 else 0 for h in range(24)] for d in range(7)],
            'modelUsage':[{'model':'test-model','totalTokens':123456,'inputTokens':120000,'cachedInputTokens':110000,'outputTokens':3456}],
            'threads':[{'title':'sample chat','source':'cli','primaryModel':'test-model','totalTokens':123456}]}


class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global APP
        APP = gui.create_app()
        cls.directory = tempfile.TemporaryDirectory(prefix='tracker-native-test-')
        cls.settings = Path(cls.directory.name) / 'settings.json'
        cls.settings.write_text('{"day":12}')
        cls.fail_reports = False
        cls.requests = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def send_json(self, value, status=200):
                raw=json.dumps(value).encode();self.send_response(status)
                self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
                self.end_headers();self.wfile.write(raw)
            def do_GET(self):
                cls.requests.append(('GET',self.path))
                if self.path=='/api/local-reports':
                    if cls.fail_reports:return self.send_json({'error':'temporary fixture outage'},503)
                    return self.send_json(reports(json.loads(cls.settings.read_text())['day']))
                if self.path.startswith('/api/overview'):return self.send_json(copy.deepcopy(OVERVIEW))
                return self.send_json({'error':'unexpected path'},404)
            def do_PUT(self):
                cls.requests.append(('PUT',self.path))
                value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                day=value.get('monthStartDay')
                if self.path!='/api/local-reports/settings' or type(day) is not int or not 1<=day<=31:
                    return self.send_json({'error':'bad setting'},400)
                cls.settings.write_text(json.dumps({'day':day}))
                return self.send_json(reports(day))
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.url=f'http://127.0.0.1:{cls.server.server_port}'
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.directory.cleanup()
    def wait_for(self,predicate):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            APP.processEvents();QTest.qWait(15)
            if predicate():return
        self.fail('Timed out waiting for native GUI update')
    def window(self):
        w=gui.UsageWindow(self.url);w.show();self.addCleanup(w.close)
        self.wait_for(lambda:bool(w.reports) and bool(w.overview));w.timer.stop();return w
    def test_native_controls_load_data_and_tabs(self):
        w=self.window()
        self.assertIsInstance(w.report_table,QTableWidget);self.assertIsInstance(w.month_day,gui.FluentComboBox)
        self.assertEqual(w.chat_table.item(0,1).text(),'CLI')
        self.assertFalse(w.save_button.isEnabled())
        QTest.mouseClick(w.month_button,Qt.LeftButton);self.assertEqual(w.mode,'monthly')
        QTest.mouseClick(w.chat_tab,Qt.LeftButton);self.assertEqual(w.stack.currentIndex(),1)
        QTest.mouseClick(w.report_tab,Qt.LeftButton);self.assertEqual(w.stack.currentIndex(),0)
        QTest.mouseClick(w.chart_tab,Qt.LeftButton);self.assertEqual(w.stack.currentIndex(),2)
        self.assertEqual(len(w.charts.daily.rows),14)
        QTest.mouseClick(w.detail_button,Qt.LeftButton);self.assertTrue(w.details.isVisible())
        self.assertNotIn('WebEngine',str(type(w.report_table)))
    def test_native_charts_fonts_and_request_callback_lifetimes(self):
        w=self.window()
        self.assertEqual(len(w.charts.daily.rows),14)
        self.assertEqual(sum(r['tokens'] for r in w.charts.daily.rows),123456)
        self.assertEqual(w.charts.activity.grid[1][9],100)
        self.assertEqual(len(w.charts.models.rows),1)
        self.assertGreaterEqual(w.report_table.font().pixelSize(),16)
        self.assertGreaterEqual(w.report_table.item(0,0).font().pixelSize(),16)
        for _ in range(3):
            w.refresh();gc.collect()
            self.wait_for(lambda:not w.pending_reports and not w.pending_overview)
            self.assertFalse(w.active_requests)
        self.assertFalse(any('WebEngine' in name for name in sys.modules))
    def test_month_day_save_refresh_and_reopen_preserve_setting(self):
        w=self.window();w.month_day.setCurrentIndex(30)
        self.assertTrue(w.save_button.isEnabled())
        QTest.mouseClick(w.save_button,Qt.LeftButton)
        self.wait_for(lambda:w.reports['monthStartDay']==31 and not w.pending_save)
        self.assertEqual(w.mode,'monthly');self.assertIn('已保存',w.hint.text())
        self.assertEqual(json.loads(self.settings.read_text())['day'],31)
        self.assertFalse(w.save_button.isEnabled())
        w.refresh();self.wait_for(lambda:not w.pending_reports and not w.pending_overview)
        self.assertEqual(w.month_day.currentIndex(),30)
        another=self.window();self.assertEqual(another.month_day.currentIndex(),30)
        self.assertIn(('PUT','/api/local-reports/settings'),self.requests)
    def test_closing_window_cancels_pending_gui_requests(self):
        w=self.window();w.refresh()
        self.assertTrue(w.active_requests)
        w.close();APP.processEvents()
        self.assertFalse(w.active_requests)
        self.assertFalse(w.timer.isActive())
    def test_unsaved_draft_survives_refresh(self):
        w=self.window();w.month_day.setCurrentIndex(15)
        w.refresh();self.wait_for(lambda:not w.pending_reports and not w.pending_overview)
        self.assertEqual(w.month_day.currentIndex(),15);self.assertTrue(w.save_button.isEnabled())
    def test_transient_backend_error_recovers(self):
        w=self.window();type(self).fail_reports=True
        try:
            w.refresh();self.wait_for(lambda:bool(w.request_errors))
            self.assertIn('更新失败',w.hint.text())
        finally:type(self).fail_reports=False
        w.refresh();self.wait_for(lambda:not w.pending_reports and not w.pending_overview)
        self.assertFalse(w.request_errors);self.assertNotIn('更新失败',w.hint.text())
        self.assertEqual(w.status.text(),'当前账号 · 仅本机')


class EnvironmentTests(unittest.TestCase):
    def test_windows_environment_selects_chatgpt_home_and_excludes_account_polling(self):
        with tempfile.TemporaryDirectory(prefix='tracker-path-中文 space-') as temp:
            home=Path(temp)
            desktop=home/'.codex-desktop';cli=home/'.codex'
            desktop.mkdir();cli.mkdir()
            (desktop/'auth.json').write_text(json.dumps({'auth_mode':'chatgpt','tokens':{'account_id':'fixture-account'}}))
            (cli/'auth.json').write_text(json.dumps({'auth_mode':'apikey'}))
            with patch.object(gui.Path,'home',return_value=home),patch.dict(os.environ,{'LOCALAPPDATA':str(home/'Local data')},clear=True):
                env=gui.windows_backend_environment()
            self.assertEqual(env['CODEX_HOME'],str(desktop))
            self.assertEqual(env['CLAUDE_CODE'],'false');self.assertEqual(env['QUOTA_POLLING'],'false')
            self.assertEqual(env['NATIVE_GUI_ONLY'],'true');self.assertEqual(env['CODEX_ACCOUNT_SCOPE'],'true')
            self.assertTrue(Path(env['DATA_DIR']).is_dir())
            self.assertNotIn('auth.json',','.join(p.name for p in Path(env['DATA_DIR']).iterdir()))
    def test_missing_chatgpt_login_is_not_treated_as_current_account(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(gui.Path,'home',return_value=Path(temp)),patch.dict(os.environ,{},clear=True):
                with self.assertRaises(RuntimeError):gui.windows_backend_environment()
    def test_period_end_handles_month_and_year_boundaries(self):
        self.assertEqual(gui.period_end('2027-01-01'),'2026-12-31')
        self.assertEqual(gui.period_end('2028-03-01'),'2028-02-29')

if __name__=='__main__':unittest.main()
