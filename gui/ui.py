"""Native page composition and a compact, shared visual language."""

from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QColor, QFont, QPainter, QIcon
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QStackedWidget,
    QStyledItemDelegate,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    NavigationInterface,
    NavigationItemPosition,
    FluentIcon as FIF,
    PushButton,
    PrimaryPushButton,
    ToggleButton,
    ComboBox,
    setFont,
    setCustomStyleSheet,
)
from .charts import ChartsPanel, DailyChart
from .utils import compact, ROOT

STYLE = """
QMainWindow, QWidget#root, QWidget#content {background:#f4f7f8;color:#213c40;}
QWidget {font-family:"@FONT@";font-size:16px;font-weight:400;}
QFrame#sidebar {background:#eaf0f1;border:none;}
QFrame#card, QFrame#report {background:white;border:1px solid #e8eeed;border-radius:22px;}
QFrame#hero {background:#163f43;border:none;border-radius:24px;}
QLabel#brand {font-size:21px;font-weight:600;color:#22474b;}
QLabel#heading {font-size:29px;font-weight:600;color:#193a3f;}
QLabel#chartHeading {font-size:19px;font-weight:600;color:#244448;}
QLabel#muted {font-size:14px;color:#7a8e90;}
QLabel#amount {font-size:36px;font-weight:500;color:#254b4f;}
QLabel#heroAmount {font-size:46px;font-weight:500;color:#f5fffb;}
QLabel#heroCaption {font-size:16px;color:#bbd5cf;}
QLabel#status {background:#e2efea;border-radius:14px;padding:6px 12px;color:#397364;font-size:14px;}
QLabel#notice {background:#eaf1ef;border-radius:14px;padding:11px 16px;color:#55766d;font-size:14px;}
QLabel#notice[warning="true"] {background:#fbf0da;color:#967039;}
QLabel#badge {background:#eaf1ef;border-radius:12px;padding:5px 12px;color:#55766d;font-size:14px;}
QLineEdit, QPlainTextEdit {background:white;border:1px solid #dce6e5;border-radius:12px;padding:9px;}
QDialog {background:#f4f7f8;}
QPushButton, QToolButton {background:white;border:1px solid #dce6e5;border-radius:14px;padding:7px 14px;color:#47656a;}
QPushButton:hover, QToolButton:hover {background:#e9f1ee;}
QHeaderView::section {background:transparent;color:#829390;border:none;padding:13px 10px;}
QScrollBar:vertical {background:transparent;width:8px;margin:3px;}
QScrollBar::handle:vertical {background:#c9d7d2;border-radius:4px;min-height:30px;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0;}
"""


def card(parent=None, hero=False):
    frame = QFrame(parent, objectName="hero" if hero else "card")
    box = QVBoxLayout(frame)
    box.setContentsMargins(24, 20, 24, 20)
    box.setSpacing(10)
    return frame, box


class Contributions(QWidget):
    """Member comparison drawn locally with proportional bars and exact tooltips."""

    def __init__(self):
        super().__init__()
        self.members = []
        self.month_total = 0
        self.setMinimumHeight(240)

    def set_members(self, members):
        self.month_total = sum(m["month"] for m in members)
        self.members = sorted(members, key=lambda m: m["month"], reverse=True)[:5]
        self.setToolTip(
            "\n".join(f"{m['name']}：{m['month']:,} Token" for m in self.members)
        )
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        font = QFont(self.font())
        font.setPixelSize(16)
        p.setFont(font)
        if not self.members:
            p.setPen(QColor("#829390"))
            p.drawText(self.rect(), Qt.AlignCenter, "接入成员后，在这里比较用量")
            return
        gap = min(68, self.height() / max(4, len(self.members)))
        for i, m in enumerate(self.members):
            y = int(i * gap)
            p.setPen(QColor("#314f53"))
            name = p.fontMetrics().elidedText(
                m["name"], Qt.ElideRight, int(self.width() * 0.48)
            )
            p.drawText(
                QRectF(0, y, self.width() * 0.5, 26),
                Qt.AlignLeft | Qt.AlignVCenter,
                name,
            )
            p.setPen(QColor("#527a71"))
            p.drawText(
                QRectF(self.width() * 0.5, y, self.width() * 0.5, 26),
                Qt.AlignRight | Qt.AlignVCenter,
                (
                    f"{compact(m['month'])} · {m['month']/self.month_total:.0%}"
                    if self.month_total
                    else compact(m["month"])
                ),
            )
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#edf3f0"))
            p.drawRoundedRect(QRectF(0, y + 34, self.width(), 7), 3.5, 3.5)
            p.setBrush(
                QColor(["#397c70", "#6c9e89", "#a1be9f", "#bad0c0", "#cbdccf"][i])
            )
            if self.month_total:
                p.drawRoundedRect(
                    QRectF(
                        0,
                        y + 34,
                        max(7, self.width() * m["month"] / self.month_total),
                        7,
                    ),
                    3.5,
                    3.5,
                )


class StatusDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        text = index.data() or ""
        good = text == "在线"
        warn = text in ("待上传", "待初始化")
        background = "#e6f2eb" if good else "#fcf0d9" if warn else "#edf0f3"
        foreground = "#38735d" if good else "#9b7735" if warn else "#849294"
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(option.rect.adjusted(10, 14, -10, -14))
        rect.setWidth(min(94, rect.width()))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(rect, 12, 12)
        painter.setFont(option.font)
        painter.setPen(QColor(foreground))
        painter.drawText(rect, Qt.AlignCenter, text)
        painter.restore()


def apply_widget_styles(owner):
    button_style = """
PushButton,ToggleButton,PrimaryPushButton {font-size:16px;padding:8px 17px;min-height:27px;border-radius:15px;border:1px solid transparent;background:#fff;color:#506c6c;}
PushButton:hover,ToggleButton:hover {background:#e9f1ed;}
ToggleButton:checked {background:#e4eeea;color:#306d5c;font-weight:500;}
PrimaryPushButton {background:#357a69;color:#fff;}
PrimaryPushButton:hover {background:#286c5b;}
PrimaryPushButton:disabled {background:#edf2ef;color:#9dafaa;}
"""
    for button in owner.findChildren(PushButton):
        setFont(button, 16)
        setCustomStyleSheet(button, button_style, button_style)
    for combo in (owner.month_day, owner.scope):
        setFont(combo, 16)
        qss = "ComboBox {font-size:16px;min-height:28px;border-radius:14px;border:1px solid #e3ebe7;background:#fff;padding:6px 14px;}"
        setCustomStyleSheet(combo, qss, qss)
    for table in (
        owner.report_table,
        owner.chat_table,
        owner.member_table,
        owner.device_table,
    ):
        setFont(table, 16)
        qss = "QTableView,QTableWidget {font-size:16px;border:none;background:transparent;} QHeaderView::section {font-size:14px;background:transparent;color:#829390;border:none;border-bottom:1px solid #edf2ef;padding:14px 10px;} QTableWidget::item {padding:12px 10px;border-bottom:1px solid #f0f4f1;}"
        setCustomStyleSheet(table, qss, qss)


def build_window(w):
    w.setWindowTitle("Codex · 用量统计")
    w.setWindowIcon(QIcon(str(ROOT / "public" / "ai-usage-tracker.ico")))
    w.resize(1360, 940)
    w.setMinimumSize(1180, 800)
    root = QWidget(objectName="root")
    w.setCentralWidget(root)
    outer = QHBoxLayout(root)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    sidebar = QFrame(objectName="sidebar")
    sidebar.setFixedWidth(210)
    side = QVBoxLayout(sidebar)
    side.setContentsMargins(12, 30, 12, 20)
    side.setSpacing(20)
    brand = QLabel("◈  Codex", objectName="brand")
    brand.setContentsMargins(15, 0, 0, 0)
    side.addWidget(brand)
    caption = QLabel("    团队用量工作台", objectName="muted")
    side.addWidget(caption)
    w.nav = NavigationInterface(
        showMenuButton=False, showReturnButton=False, collapsible=False
    )
    w.nav.setExpandWidth(186)
    w.nav.setMinimumExpandWidth(0)
    w.nav.expand(useAni=False)
    pages = [
        (4, "overview", FIF.HOME, "用量概览"),
        (0, "reports", FIF.DOCUMENT, "周期报表"),
        (3, "team", FIF.PEOPLE, "成员与设备"),
        (2, "charts", FIF.PIE_SINGLE, "图表分析"),
        (1, "chats", FIF.CHAT, "本机聊天"),
    ]
    w.page_keys = {index: key for index, key, _, _ in pages}
    items = {}
    for index, key, icon, text in pages:
        items[index] = w.nav.addItem(
            key, icon, text, onClick=lambda *_, i=index: w.show_page(i)
        )
    w.report_tab = items[0]
    w.chat_tab = items[1]
    w.chart_tab = items[2]
    w.team_tab = items[3]
    w.home_tab = items[4]
    side.addWidget(w.nav, 1)
    w.role_label = QLabel("仅统计本机", objectName="muted")
    w.role_label.setContentsMargins(15, 0, 0, 0)
    side.addWidget(w.role_label)
    w.settings_button = PushButton(FIF.SETTING, "设置与连接")
    w.settings_button.clicked.connect(w.configure_team)
    side.addWidget(w.settings_button)
    outer.addWidget(sidebar)
    content = QWidget(objectName="content")
    body = QVBoxLayout(content)
    body.setContentsMargins(30, 28, 30, 18)
    body.setSpacing(18)
    outer.addWidget(content, 1)
    header = QHBoxLayout()
    headings = QVBoxLayout()
    headings.setSpacing(5)
    w.page_title = QLabel("用量概览", objectName="heading")
    headings.addWidget(w.page_title)
    w.subtitle = QLabel("每一位成员，每一台设备，清楚汇总。", objectName="muted")
    headings.addWidget(w.subtitle)
    header.addLayout(headings)
    header.addStretch()
    w.status = QLabel("正在连接", objectName="status")
    w.status.setFixedHeight(34)
    header.addWidget(w.status, 0, Qt.AlignVCenter)
    refresh = PushButton(FIF.SYNC, "刷新")
    refresh.clicked.connect(w.refresh)
    header.addWidget(refresh)
    body.addLayout(header)
    scope_row = QHBoxLayout()
    scope_row.addWidget(QLabel("统计范围", objectName="muted"))
    w.scope = ComboBox()
    w.scope.addItem("本机", userData="local")
    w.scope.setMinimumWidth(180)
    w.scope.currentIndexChanged.connect(w.scope_changed)
    scope_row.addWidget(w.scope)
    scope_row.addStretch()
    w.coverage_label = QLabel("北京时间 · 统一周期", objectName="muted")
    scope_row.addWidget(w.coverage_label)
    body.addLayout(scope_row)
    w.stack = QStackedWidget()
    body.addWidget(w.stack, 1)
    # Period report page (index 0).
    report_page = QWidget()
    report_layout = QVBoxLayout(report_page)
    report_layout.setContentsMargins(0, 0, 0, 0)
    report_layout.setSpacing(18)
    totals = QHBoxLayout()
    w.amount_labels = []
    w.card_notes = []
    for title, note in [
        ("累计用量", "已确认的计量记录"),
        ("本周", "周一至周日"),
        ("本月", "统一起始日"),
    ]:
        f, b = card()
        b.addWidget(QLabel(title, objectName="muted"))
        value = QLabel("—", objectName="amount")
        b.addWidget(value)
        sub = QLabel(note, objectName="muted")
        b.addWidget(sub)
        w.amount_labels.append(value)
        w.card_notes.append(sub)
        totals.addWidget(f, 1)
    report_layout.addLayout(totals)
    f, b = card()
    tools = QHBoxLayout()
    w.week_button = ToggleButton("周报")
    w.month_button = ToggleButton("月报")
    w.week_button.setChecked(True)
    for button, mode in [(w.week_button, "weekly"), (w.month_button, "monthly")]:
        button.clicked.connect(lambda _, m=mode: w.set_mode(m))
        tools.addWidget(button)
    tools.addStretch()
    tools.addWidget(QLabel("每月起始日", objectName="muted"))
    w.month_day = ComboBox()
    w.month_day.addItems([f"{i} 日" for i in range(1, 32)])
    w.month_day.currentIndexChanged.connect(w.day_changed)
    tools.addWidget(w.month_day)
    w.save_button = PrimaryPushButton("保存")
    w.save_button.setEnabled(False)
    w.save_button.clicked.connect(w.save_day)
    tools.addWidget(w.save_button)
    b.addLayout(tools)
    w.report_table = w.make_table(
        ["周期", "总 Token", "输入", "输出", "聊天数", "状态"]
    )
    w.report_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
    b.addWidget(w.report_table, 1)
    report_layout.addWidget(f, 1)
    w.stack.addWidget(report_page)
    # Local chat page (index 1).
    f, b = card()
    b.addWidget(QLabel("本机聊天", objectName="chartHeading"))
    b.addWidget(QLabel("聊天内容保留在这台设备，不向团队上传。", objectName="muted"))
    w.chat_table = w.make_table(["聊天", "入口", "模型", "Token"])
    w.chat_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
    b.addWidget(w.chat_table, 1)
    w.stack.addWidget(f)
    # Native charts (index 2).
    w.charts = ChartsPanel()
    w.stack.addWidget(w.charts)
    # Team page (index 3).
    team_page = QWidget()
    team_box = QVBoxLayout(team_page)
    team_box.setContentsMargins(0, 0, 0, 0)
    team_box.setSpacing(18)
    f, b = card()
    row = QHBoxLayout()
    row.addWidget(QLabel("成员用量", objectName="chartHeading"))
    row.addStretch()
    w.manage_button = PrimaryPushButton(FIF.ADD, "管理成员")
    w.manage_button.setEnabled(False)
    w.manage_button.clicked.connect(w.manage_members)
    row.addWidget(w.manage_button)
    b.addLayout(row)
    f.setMaximumHeight(285)
    w.member_table = w.make_table(
        ["成员", "本周 Token", "本月 Token", "累计 Token", "设备数"]
    )
    w.member_table.verticalHeader().setDefaultSectionSize(44)
    w.member_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
    for c in (1, 2, 3):
        w.member_table.horizontalHeader().setSectionResizeMode(c, QHeaderView.Fixed)
        w.member_table.setColumnWidth(c, 142)
    b.addWidget(w.member_table, 1)
    team_box.addWidget(f, 1)
    f, b = card()
    b.addWidget(QLabel("设备同步", objectName="chartHeading"))
    w.device_table = w.make_table(
        ["设备", "所属成员", "同步状态", "待上传", "最近联系"]
    )
    w.device_table.verticalHeader().setDefaultSectionSize(48)
    w.device_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
    for c, size in [(1, 115), (2, 120), (3, 90), (4, 150)]:
        w.device_table.horizontalHeader().setSectionResizeMode(c, QHeaderView.Fixed)
        w.device_table.setColumnWidth(c, size)
    w.device_table.setItemDelegateForColumn(2, StatusDelegate(w.device_table))
    b.addWidget(w.device_table, 1)
    team_box.addWidget(f, 1)
    w.team_note = QLabel("在设置中建立团队或加入汇总中心。", objectName="muted")
    w.team_note.setWordWrap(True)
    team_box.addWidget(w.team_note)
    w.stack.addWidget(team_page)
    # Overview (index 4): one focal metric, trend, member comparison and coverage.
    home = QWidget()
    home_box = QVBoxLayout(home)
    home_box.setContentsMargins(0, 0, 0, 0)
    home_box.setSpacing(18)
    row = QHBoxLayout()
    w.home_amounts = [None, None, None]
    f, b = card(hero=True)
    b.addWidget(QLabel("本月用量", objectName="heroCaption"))
    w.home_amounts[2] = QLabel("—", objectName="heroAmount")
    b.addWidget(w.home_amounts[2])
    w.hero_note = QLabel("按团队统一周期汇总", objectName="heroCaption")
    b.addWidget(w.hero_note)
    row.addWidget(f, 5)
    for index, title in [(1, "本周用量"), (0, "累计用量")]:
        f, b = card()
        b.addWidget(QLabel(title, objectName="muted"))
        w.home_amounts[index] = QLabel("—", objectName="amount")
        b.addWidget(w.home_amounts[index])
        b.addWidget(QLabel("Token", objectName="muted"))
        row.addWidget(f, 3)
    home_box.addLayout(row)
    row = QHBoxLayout()
    row.setSpacing(18)
    f, b = card()
    b.addWidget(QLabel("用量趋势", objectName="chartHeading"))
    b.addWidget(QLabel("最近 7 天 · Token", objectName="muted"))
    w.home_daily = DailyChart(days=7)
    b.addWidget(w.home_daily, 1)
    row.addWidget(f, 3)
    f, b = card()
    b.addWidget(QLabel("成员用量分布", objectName="chartHeading"))
    b.addWidget(QLabel("全体成员 · 本月用量", objectName="muted"))
    w.contributions = Contributions()
    b.addWidget(w.contributions, 1)
    members = PushButton("查看成员与设备  →")
    members.clicked.connect(lambda: w.show_page(3))
    b.addWidget(members)
    row.addWidget(f, 2)
    home_box.addLayout(row, 1)
    w.coverage_notice = QLabel("正在读取设备同步情况…", objectName="notice")
    w.coverage_notice.setWordWrap(True)
    home_box.addWidget(w.coverage_notice)
    w.stack.addWidget(home)
    footer = QHBoxLayout()
    w.detail_button = QToolButton()
    w.detail_button.setText("统计口径")
    w.detail_button.setCheckable(True)
    w.detail_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    w.detail_button.setArrowType(Qt.RightArrow)
    w.detail_button.toggled.connect(w.toggle_details)
    footer.addWidget(w.detail_button)
    footer.addStretch()
    w.hint = QLabel("北京时间 · 输入已包含缓存", objectName="muted")
    footer.addWidget(w.hint)
    body.addLayout(footer)
    w.details = QLabel(objectName="muted")
    w.details.setWordWrap(True)
    w.details.hide()
    body.addWidget(w.details)
    apply_widget_styles(w)
    w.show_page(4)
