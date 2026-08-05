import os
import sys
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false;qt.multimedia.*=false")

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false;qt.multimedia.*=false")

def main() -> int:
    app = QApplication.instance() or QApplication([])
    suite = unittest.defaultTestLoader.discover(
        str(ROOT / "tests"), pattern="test_*.py"
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    app.quit()
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
