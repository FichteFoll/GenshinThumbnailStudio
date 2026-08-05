"""The offscreen Qt/QtWebEngine environment, set before PySide6 is imported."""

import os

# These must run before PySide6 is imported anywhere in the process, which is
# why they live in a conftest: pytest imports a package's conftest before it
# imports any of the package's test modules.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox")
