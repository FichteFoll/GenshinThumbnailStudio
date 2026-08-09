"""The offscreen Qt environment, set before PySide6 is imported."""

import os

# This must run before PySide6 is imported anywhere in the process, which is
# why it lives in a conftest: pytest imports a package's conftest before it
# imports any of the package's test modules.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
