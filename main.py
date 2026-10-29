"""
main.py — `python main.py ...` 로도 실행할 수 있게 남겨 둔 호환용 래퍼.
권장 실행 방법은 명세대로 `python -m budget_app <command> [options]` 이다.
"""

from __future__ import annotations

import sys

from budget_app.cli import main

if __name__ == "__main__":
    sys.exit(main())
