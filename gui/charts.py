"""Locally painted Qt Charts and a QWidget activity heatmap."""

from datetime import datetime, timedelta, timezone
from qfluentwidgets import ComboBox
from .utils import compact
import math

from PyQt5.QtCore import Qt, QRectF, QMargins
from PyQt5.QtGui import QBrush, QColor, QCursor, QFont, QPainter, QPen
from PyQt5.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QToolTip,
    QVBoxLayout,
    QHBoxLayout,
    QGraphicsSimpleTextItem,
    QWidget,
    QApplication,
)
from PyQt5.QtChart import (
    QBarCategoryAxis,
    QBarSeries,
    QBarSet,
    QChart,
    QChartView,
    QHorizontalStackedBarSeries,
    QValueAxis,
    QPieSeries,
)

SHANGHAI = timezone(timedelta(hours=8))
COLORS = ["#4e8c7c", "#c5dcd0", "#244f54"]


def number(value):
    return f"{int(value):,}"


def chart_font():
    font = QFont(QApplication.font())
    font.setPixelSize(15)
    return font


def chart_base():
    chart = QChart()
    chart.setBackgroundVisible(False)
    chart.setPlotAreaBackgroundVisible(False)
    chart.setMargins(QMargins(0, 10, 10, 0))
    chart.setAnimationOptions(QChart.NoAnimation)
    chart.legend().hide()
    return chart


def style_axis(axis):
    axis.setLabelsFont(chart_font())
    axis.setLabelsColor(QColor("#7b8593"))
    axis.setGridLinePen(QPen(QColor("#e9eef5"), 1))
    axis.setLineVisible(False)
    axis.setTitleFont(chart_font())
    axis.setTitleBrush(QBrush(QColor("#7b8593")))


class DailyChart(QChartView):
    def __init__(self, days=14):
        super().__init__(chart_base())
        self.setRenderHint(QPainter.Antialiasing)
        self.setBackgroundBrush(QBrush(Qt.white))
        self.setMinimumHeight(300)
        self.rows = []
        self.days = days

    def set_data(self, rows):
        by_date = {r["date"]: int(r["tokens"]) for r in rows}
        today = datetime.now(SHANGHAI).date()
        self.rows = [
            {
                "date": (today - timedelta(days=i)).isoformat(),
                "tokens": by_date.get((today - timedelta(days=i)).isoformat(), 0),
            }
            for i in reversed(range(self.days))
        ]
        peak = max((r["tokens"] for r in self.rows), default=0)
        unit, suffix = (
            (1_000_000, "M")
            if peak >= 1_000_000
            else (1000, "K") if peak >= 1000 else (1, "")
        )
        values = QBarSet("Token")
        values.setColor(QColor(COLORS[0]))
        values.setBorderColor(QColor(COLORS[0]))
        values.append([r["tokens"] / unit for r in self.rows])
        values.hovered.connect(
            lambda active, index: (
                QToolTip.showText(
                    QCursor.pos(),
                    f"{self.rows[index]['date']}\n{number(self.rows[index]['tokens'])} Token",
                    self,
                )
                if active
                else QToolTip.hideText()
            )
        )
        series = QBarSeries()
        series.append(values)
        series.setBarWidth(0.55)
        chart = chart_base()
        chart.addSeries(series)
        x = QBarCategoryAxis()
        x.append([r["date"][5:].replace("-", "/") for r in self.rows])
        style_axis(x)
        x.setGridLineVisible(False)
        x.setLabelsAngle(-40)
        y = QValueAxis()
        y.setRange(0, max(1, peak / unit * 1.15))
        y.setTickCount(5)
        y.setLabelFormat("%.1f" + suffix)
        style_axis(y)
        chart.addAxis(x, Qt.AlignBottom)
        chart.addAxis(y, Qt.AlignLeft)
        series.attachAxis(x)
        series.attachAxis(y)
        old = self.chart()
        self.setChart(chart)
        old.deleteLater()


class ActivityHeatmap(QWidget):
    def __init__(self):
        super().__init__()
        self.grid = [[0] * 24 for _ in range(7)]
        self.setMinimumHeight(250)
        self.setMouseTracking(True)
        self.cells = []

    def set_data(self, grid):
        self.grid = [
            [
                int(grid[d][h]) if d < len(grid) and h < len(grid[d]) else 0
                for h in range(24)
            ]
            for d in range(7)
        ]
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        font = QFont(self.font())
        font.setPixelSize(14)
        painter.setFont(font)
        left, top, right, bottom = 45, 30, 12, 16
        width = (self.width() - left - right) / 24
        height = (self.height() - top - bottom) / 7
        maximum = max((v for day in self.grid for v in day), default=0)
        self.cells = []
        painter.setPen(QColor("#7b8593"))
        for hour in [0, 4, 8, 12, 16, 20, 23]:
            painter.drawText(
                QRectF(left + hour * width, 0, width, 24), Qt.AlignCenter, str(hour)
            )
        for index, day in enumerate([1, 2, 3, 4, 5, 6, 0]):
            painter.setPen(QColor("#7b8593"))
            painter.drawText(
                QRectF(0, top + index * height, left - 10, height),
                Qt.AlignVCenter | Qt.AlignRight,
                "一二三四五六日"[index],
            )
            for hour in range(24):
                value = self.grid[day][hour]
                ratio = math.sqrt(value / maximum) if maximum else 0
                color = (
                    QColor("#edf3f0")
                    if value == 0
                    else QColor.fromRgbF(
                        0.80 - 0.55 * ratio, 0.90 - 0.40 * ratio, 0.84 - 0.40 * ratio
                    )
                )
                rect = QRectF(
                    left + hour * width + 2,
                    top + index * height + 2,
                    max(1, width - 4),
                    max(1, height - 4),
                )
                painter.setPen(Qt.NoPen)
                painter.setBrush(color)
                painter.drawRoundedRect(rect, 6, 6)
                self.cells.append((rect, index, hour, value))

    def mouseMoveEvent(self, event):
        for rect, index, hour, value in self.cells:
            if rect.contains(event.pos()):
                QToolTip.showText(
                    event.globalPos(),
                    f"周{'一二三四五六日'[index]} {hour:02}:00–{hour + 1:02}:00\n{number(value)} Token",
                    self,
                )
                return
        QToolTip.hideText()


class ModelChart(QChartView):
    def __init__(self):
        super().__init__(chart_base())
        self.setRenderHint(QPainter.Antialiasing)
        self.setBackgroundBrush(QBrush(Qt.white))
        self.setMinimumHeight(300)
        self.rows = []

    def set_data(self, rows):
        self.rows = sorted(
            [r for r in rows if r.get("totalTokens", 0) > 0],
            key=lambda r: r["totalTokens"],
            reverse=True,
        )[:6][::-1]
        chart = chart_base()
        if self.rows:
            peak = max(
                r.get("inputTokens", 0) + r.get("outputTokens", 0) for r in self.rows
            )
            unit, suffix = (
                (1_000_000, "M")
                if peak >= 1_000_000
                else (1000, "K") if peak >= 1000 else (1, "")
            )
            series = QHorizontalStackedBarSeries()
            series.setBarWidth(0.48)
            for label, color, getter in [
                ("缓存输入", COLORS[1], lambda r: r.get("cachedInputTokens", 0)),
                (
                    "新增输入",
                    COLORS[0],
                    lambda r: max(
                        0, r.get("inputTokens", 0) - r.get("cachedInputTokens", 0)
                    ),
                ),
                ("输出", COLORS[2], lambda r: r.get("outputTokens", 0)),
            ]:
                values = QBarSet(label)
                values.setColor(QColor(color))
                values.setBorderColor(QColor(color))
                values.append([getter(r) / unit for r in self.rows])
                series.append(values)
            chart.addSeries(series)
            x = QValueAxis()
            x.setRange(0, max(1, peak / unit * 1.1))
            x.setLabelFormat("%.1f" + suffix)
            x.setTickCount(5)
            style_axis(x)
            y = QBarCategoryAxis()
            y.append([r["model"] for r in self.rows])
            style_axis(y)
            y.setGridLineVisible(False)
            chart.addAxis(x, Qt.AlignBottom)
            chart.addAxis(y, Qt.AlignLeft)
            series.attachAxis(x)
            series.attachAxis(y)
            chart.legend().setVisible(True)
            chart.legend().setAlignment(Qt.AlignTop)
            chart.legend().setFont(chart_font())
        old = self.chart()
        self.setChart(chart)
        old.deleteLater()


class MemberPie(QWidget):
    def __init__(self):
        super().__init__()
        self.members = []
        self.rows = []
        self.period = "month"
        self.total = 0
        self.series = None
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        toolbar.addStretch()
        self.period_combo = ComboBox()
        for title, key in [("本月", "month"), ("本周", "week"), ("累计", "total")]:
            self.period_combo.addItem(title, userData=key)
        self.period_combo.currentIndexChanged.connect(self.period_changed)
        toolbar.addWidget(self.period_combo)
        box.addLayout(toolbar)
        row = QHBoxLayout()
        self.view = QChartView(chart_base())
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setMinimumSize(300, 280)
        self.view.setBackgroundBrush(QBrush(Qt.white))
        row.addWidget(self.view, 1)
        self.legend = QVBoxLayout()
        self.legend.setSpacing(12)
        row.addLayout(self.legend, 1)
        box.addLayout(row)

    def period_changed(self):
        self.period = self.period_combo.currentData() or "month"
        self.set_members(self.members)

    def set_members(self, members):
        self.members = list(members)
        self.rows = sorted(
            [
                {"id": m["id"], "name": m["name"], "tokens": int(m.get(self.period, 0))}
                for m in members
            ],
            key=lambda m: m["tokens"],
            reverse=True,
        )
        self.total = sum(m["tokens"] for m in self.rows)
        while self.legend.count():
            item = self.legend.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
            if item.layout():
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.widget():
                        child.widget().hide()
                        child.widget().deleteLater()
                item.layout().deleteLater()
        chart = chart_base()
        self.series = QPieSeries()
        self.series.setHoleSize(0.50)
        palette = [
            "#387d70",
            "#76a48d",
            "#afc59e",
            "#698997",
            "#b3bfc1",
            "#c1ac8c",
            "#79955d",
            "#568a9d",
        ]
        for index, member in enumerate(self.rows):
            value = member["tokens"]
            color = palette[index % len(palette)]
            share = value / self.total if self.total else 0
            if value > 0:
                segment = self.series.append(member["name"], value)
                segment.setColor(QColor(color))
                segment.setBorderColor(QColor("white"))
                segment.setBorderWidth(3)
                segment.hovered.connect(
                    lambda active, m=member, p=share: (
                        QToolTip.showText(
                            QCursor.pos(),
                            f"{m['name']}\n{m['tokens']:,} Token · {p:.1%}",
                            self,
                        )
                        if active
                        else QToolTip.hideText()
                    )
                )
            line = QHBoxLayout()
            dot = QLabel("●")
            dot.setStyleSheet("color:" + color)
            line.addWidget(dot)
            name = QLabel()
            name.setTextFormat(Qt.PlainText)
            name.setText(
                name.fontMetrics().elidedText(member["name"], Qt.ElideRight, 190)
            )
            name.setMaximumWidth(200)
            name.setToolTip(member["name"])
            line.addWidget(name, 1)
            value_label = QLabel(f"{compact(value)}   {share:.1%}")
            value_label.setToolTip(f"{value:,} Token")
            line.addWidget(value_label)
            self.legend.addLayout(line)
        if not self.rows:
            empty = QLabel("暂无成员用量", objectName="muted")
            self.legend.addWidget(empty)
        self.legend.addStretch()
        chart.addSeries(self.series)
        label = QGraphicsSimpleTextItem(
            compact(self.total) if self.total else "—", chart
        )
        font = QFont(QApplication.font())
        font.setPixelSize(26)
        font.setWeight(QFont.Medium)
        label.setFont(font)
        label.setBrush(QColor("#315957"))

        def center_label(area):
            size = label.boundingRect()
            label.setPos(
                area.center().x() - size.width() / 2,
                area.center().y() - size.height() / 2,
            )

        chart.plotAreaChanged.connect(center_label)
        old = self.view.chart()
        self.view.setChart(chart)
        old.deleteLater()


class ChartsPanel(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        self.pie = MemberPie()
        self.daily = DailyChart()
        self.activity = ActivityHeatmap()
        self.models = ModelChart()
        for title, widget in [
            ("全体成员用量占比", self.pie),
            ("每日用量 · 近 14 天", self.daily),
            ("活跃时段 · 近 30 天", self.activity),
            ("模型用量", self.models),
        ]:
            frame = QFrame(objectName="report")
            box = QVBoxLayout(frame)
            box.setContentsMargins(22, 18, 22, 16)
            heading = QLabel(title)
            heading.setObjectName("chartHeading")
            box.addWidget(heading)
            box.addWidget(widget)
            layout.addWidget(frame)
        layout.addStretch()
        self.setWidget(content)

    def set_data(self, overview):
        self.daily.set_data(overview.get("localDailyUsage", []))
        self.activity.set_data(overview.get("hourlyActivity", []))
        self.models.set_data(overview.get("modelUsage", []))
