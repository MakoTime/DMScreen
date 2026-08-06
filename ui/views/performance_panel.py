from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem

from performance import PerformanceRecord


class PerformancePanel(QFrame):
    """Compact periodic view of named worker and UI timings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumHeight(32)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)

        title = QLabel("Performance")
        layout.addWidget(title, 0, Qt.AlignmentFlag.AlignTop)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Task", "Last ms", "Average ms", "Max ms", "Calls"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        layout.addWidget(self.table, 1)

    def set_records(self, records: list[PerformanceRecord]):
        self.table.setRowCount(len(records))
        for row, record in enumerate(records):
            values = (
                record.name,
                f"{record.last_ms:.2f}",
                f"{record.average_ms:.2f}",
                f"{record.maximum_ms:.2f}",
                str(record.calls),
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.table.resizeColumnsToContents()

    def set_checkers(self, checkers):
        records = []
        for prefix, checker in checkers:
            records.extend(
                replace(record, name=f"{prefix}.{record.name}")
                for record in checker.snapshot()
            )
        self.set_records(records)
