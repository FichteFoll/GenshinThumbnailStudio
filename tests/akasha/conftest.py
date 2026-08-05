"""The offscreen Qt/QtWebEngine environment, set before PySide6 is imported."""

import os

# Must be set before PySide6 is imported; only the facade import pulls in QtWebEngine,
# but setting these defaults here keeps the whole package's tests safe to run in any
# order.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox")
