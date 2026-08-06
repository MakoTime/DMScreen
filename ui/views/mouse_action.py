from enum import Enum, auto

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QSpinBox,
)


class MouseActionState(Enum):
    SELECT = auto()
    PAN = auto()
    PLAYER_PAN = auto()
    PING = auto()
    MASK = auto()
    MASK_FILL_ADD = auto()
    MASK_FILL_REMOVE = auto()


class MouseActionMenu(QFrame):
    state_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAutoFillBackground(True)
        self.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self.player_pan_button = None
        self.mask_button = None
        self.mask_draw_button = None
        self.mask_erase_button = None
        self.mask_fill_add_button = None
        self.mask_fill_remove_button = None
        self.mask_brush_size = None
        self._state = MouseActionState.SELECT

        self.select_button = self._make_button("Select")
        self.pan_button = self._make_button("Pan")
        self.ping_button = self._make_button("Ping")
        self.select_button.setChecked(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        layout.addWidget(self.select_button)
        layout.addWidget(self.pan_button)
        layout.addWidget(self.ping_button)

        self.select_button.clicked.connect(
            lambda: self._set_state(MouseActionState.SELECT)
        )
        self.pan_button.clicked.connect(
            lambda: self._set_state(MouseActionState.PAN)
        )
        self.ping_button.clicked.connect(
            lambda: self._set_state(MouseActionState.PING)
        )
        self._set_state(MouseActionState.SELECT)

    @staticmethod
    def _make_button(text):
        button = QPushButton(text)
        button.setCheckable(True)
        button.setAutoExclusive(True)
        button.setFixedHeight(24)
        button.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        return button

    def add_player_pan_option(self):
        if self.player_pan_button is not None:
            return
        self.player_pan_button = self._make_button("Player Pan")
        self.layout().addWidget(self.player_pan_button)
        self.player_pan_button.clicked.connect(
            lambda: self._set_state(MouseActionState.PLAYER_PAN)
        )

    def add_mask_option(self):
        if self.mask_button is not None:
            return
        self.mask_button = self._make_button("Mask")
        self.mask_draw_button = self._make_button("Draw")
        self.mask_erase_button = self._make_button("Erase")
        self.mask_fill_add_button = self._make_button("Fill Add")
        self.mask_fill_remove_button = self._make_button("Fill Remove")
        self.mask_draw_button.setAutoExclusive(False)
        self.mask_erase_button.setAutoExclusive(False)
        self.mask_draw_button.setChecked(True)
        self.mask_brush_size = QSpinBox()
        self.mask_brush_size.setRange(1, 200)
        self.mask_brush_size.setValue(20)
        for widget in (
            self.mask_button,
            self.mask_draw_button,
            self.mask_erase_button,
            self.mask_fill_add_button,
            self.mask_fill_remove_button,
            self.mask_brush_size,
        ):
            self.layout().addWidget(widget)
        self.mask_button.clicked.connect(
            lambda: self._set_state(MouseActionState.MASK)
        )
        self.mask_draw_button.clicked.connect(self._set_draw_mode)
        self.mask_erase_button.clicked.connect(self._set_erase_mode)
        self.mask_fill_remove_button.clicked.connect(
            lambda: self._set_fill_mode(True)
        )
        self.mask_fill_add_button.clicked.connect(
            lambda: self._set_fill_mode(False)
        )
        self.set_mask_available(False)

    def set_mask_available(self, available):
        if self.mask_button is None:
            return
        for widget in (
            self.mask_button,
            self.mask_draw_button,
            self.mask_erase_button,
            self.mask_fill_add_button,
            self.mask_fill_remove_button,
            self.mask_brush_size,
        ):
            widget.setVisible(available)
            widget.setEnabled(available)
        if not available and self.state in (
            MouseActionState.MASK,
            MouseActionState.MASK_FILL_ADD,
            MouseActionState.MASK_FILL_REMOVE,
        ):
            self._set_state(MouseActionState.SELECT)
        self.adjustSize()

    @property
    def mask_erase(self):
        return self.mask_erase_button is not None and self.mask_erase_button.isChecked()

    def _set_draw_mode(self):
        self.mask_draw_button.setChecked(True)
        self.mask_erase_button.setChecked(False)
        self._set_state(MouseActionState.MASK)

    def _set_erase_mode(self):
        self.mask_draw_button.setChecked(False)
        self.mask_erase_button.setChecked(True)
        self._set_state(MouseActionState.MASK)

    def _set_fill_mode(self, erase):
        self.mask_draw_button.setChecked(False)
        self.mask_erase_button.setChecked(False)
        self._set_state(
            MouseActionState.MASK_FILL_REMOVE
            if erase
            else MouseActionState.MASK_FILL_ADD
        )

    @property
    def state(self):
        return self._state

    def _set_state(self, state):
        self._state = state
        self.select_button.setChecked(state is MouseActionState.SELECT)
        self.pan_button.setChecked(state is MouseActionState.PAN)
        self.ping_button.setChecked(state is MouseActionState.PING)
        if self.player_pan_button is not None:
            self.player_pan_button.setChecked(
                state is MouseActionState.PLAYER_PAN
            )
        if self.mask_button is not None:
            self.mask_button.setChecked(state is MouseActionState.MASK)
        self.state_changed.emit(state)
