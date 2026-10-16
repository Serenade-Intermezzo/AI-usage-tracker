"""Locally painted Qt Charts and a QWidget activity heatmap."""

from datetime import datetime, timedelta, timezone
import math

from PyQt5.QtCore import Qt, QRectF, QMargins
from PyQt5.QtGui import QBrush, QColor, QCursor, QFont, QPainter, QPen
from PyQt5.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QToolTip,
    QVBoxLayout,
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


class ChartsPanel(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        self.daily = DailyChart()
        self.activity = ActivityHeatmap()
        self.models = ModelChart()
        for title, note, widget in [
            ("每日用量", "近 14 天", self.daily),
            ("活跃时段", "近 30 天 · 北京时间", self.activity),
            ("模型用量", "所选范围累计 · 输入与输出构成", self.models),
        ]:
            frame = QFrame(objectName="report")
            box = QVBoxLayout(frame)
            box.setContentsMargins(22, 18, 22, 16)
            heading = QLabel(title)
            heading.setObjectName("chartHeading")
            box.addWidget(heading)
            label = QLabel(note)
            label.setObjectName("muted")
            box.addWidget(label)
            box.addWidget(widget)
            layout.addWidget(frame)
        layout.addStretch()
        self.setWidget(content)

    def set_data(self, overview):
        self.daily.set_data(overview.get("localDailyUsage", []))
        self.activity.set_data(overview.get("hourlyActivity", []))
        self.models.set_data(overview.get("modelUsage", []))
