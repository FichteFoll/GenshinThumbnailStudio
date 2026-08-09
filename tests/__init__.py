"""The test suite.

This package marker is load-bearing: without it, pytest's prepend import mode
puts `tests/` itself on `sys.path`, which makes `tests/enka/` shadow the
installed `enka` distribution that `enka/client.py` imports.
"""
