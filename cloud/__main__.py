"""`python -m cloud` 入口（见 cli.py）。"""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
