"""
__main__.py — `python -m budget_app <command> [options]` 로 실행될 때의 진입점 (명세 4-①)

- `python -m 패키지명` 은 패키지 안의 이 파일을 찾아 실행한다.
- 의도적으로 얇게 유지: cli.main() 이 돌려준 종료 코드를 sys.exit() 에 넘기는 것이 전부.
  (정상 0 / 입력 오류 1 / 파일 오류 2 / 대상 없음 3 — errors.py 참고)
"""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
