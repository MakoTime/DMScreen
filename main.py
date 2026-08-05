import sys
from dm_controller import DMController

from PySide6.QtWidgets import QApplication


def main() -> int:
    app = QApplication(sys.argv)

    controller = DMController()
    controller.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())