from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QHBoxLayout, QTabBar, QToolButton, QWidget


class SceneTabs(QWidget):
    current_changed = Signal(int)
    add_requested = Signal()
    rename_requested = Signal(int)
    close_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tab_bar = QTabBar(self)
        self.tab_bar.setExpanding(False)
        self.tab_bar.setDrawBase(False)
        self.tab_bar.currentChanged.connect(self.current_changed.emit)
        self.tab_bar.tabBarDoubleClicked.connect(self.rename_requested.emit)
        self.tab_bar.setTabsClosable(True)
        self.tab_bar.tabCloseRequested.connect(self.close_requested.emit)

        self.add_button = QToolButton(self)
        self.add_button.setText("+")
        self.add_button.setToolTip("Add scene")
        self.add_button.clicked.connect(self.add_requested.emit)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.tab_bar)
        layout.addWidget(self.add_button)

    def set_scene_names(self, names):
        self.tab_bar.blockSignals(True)
        while self.tab_bar.count():
            self.tab_bar.removeTab(self.tab_bar.count() - 1)
        for name in names:
            self.tab_bar.addTab(name)
        self.tab_bar.blockSignals(False)
        self.add_button.setEnabled(True)

    def set_scene_labels(self, labels):
        if self.tab_bar.count() != len(labels):
            self.set_scene_names(labels)
            return
        self.tab_bar.blockSignals(True)
        for index, label in enumerate(labels):
            if index < self.tab_bar.count():
                self.tab_bar.setTabText(index, label)
        self.tab_bar.blockSignals(False)

    def set_current_index(self, index: int):
        self.tab_bar.setCurrentIndex(index)

    def set_add_enabled(self, enabled: bool):
        self.add_button.setEnabled(enabled)
