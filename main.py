"""
main.py — 프로그램 진입점

사용법:
    python main.py <command> [options]
    python main.py -h            # 전체 명령 목록
    python main.py add -h        # 특정 명령의 옵션

이 파일은 의도적으로 얇게 유지한다:
  - 실제 로직은 ledger/ 패키지에 있고, 여기서는 cli.main() 의 반환값(종료 코드)을
    sys.exit() 에 그대로 넘겨 셸에서 `echo $?` / `echo %ERRORLEVEL%` 로 성공·실패를 확인할 수 있게 한다.
"""

from __future__ import annotations

import sys

from ledger.cli import main

if __name__ == "__main__":
    sys.exit(main())
