from __future__ import annotations

import functools
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, ParamSpec, TypeVar

from .errors import LedgerError

# ParamSpec / TypeVar 로 "어떤 시그니처의 함수든 그대로 감싼다" 는 사실을 타입으로 표현
# → 데코레이터를 씌워도 IDE 가 원본 함수의 인자·반환 타입을 정확히 안다.
P = ParamSpec("P")
R = TypeVar("R")


def handle_errors(func: Callable[P, R]) -> Callable[P, R | int]:
    """LedgerError 계열 예외를 사용자 친화적 메시지로 바꾸고 종료 코드를 반환한다.

    - 반환값 규약: 핸들러가 정상 종료하면 0 (또는 핸들러 반환값), 오류면 예외의 exit_code.
      main.py 는 이 반환값을 sys.exit() 에 그대로 넘긴다.
    - 예상 못 한 예외(버그)는 다시 던지지 않고 exit 2 로 처리하되,
      환경변수 LEDGER_DEBUG=1 이면 원래 스택트레이스를 보여준다(개발 시 사용).
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R | int:
        try:
            result = func(*args, **kwargs)
            return 0 if result is None else result
        except LedgerError as e:
            print(f"[오류] {e.message}", file=sys.stderr)
            if e.hint:
                print(f"[힌트] {e.hint}", file=sys.stderr)
            return e.exit_code
        except KeyboardInterrupt:
            print("\n[중단] 사용자가 취소했습니다.", file=sys.stderr)
            return 130  # 관례적 SIGINT 종료 코드
        except Exception as e:  # noqa: BLE001 — 최후의 방어선
            if os.environ.get("LEDGER_DEBUG"):
                raise
            print(f"[오류] 예기치 않은 문제가 발생했습니다: {type(e).__name__}: {e}", file=sys.stderr)
            print("[힌트] LEDGER_DEBUG=1 환경변수를 설정하면 상세 정보를 볼 수 있습니다.", file=sys.stderr)
            return 2

    return wrapper


def log_action(log_path: Path | None = None) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """명령 실행 이력을 로그 파일에 한 줄씩 남기는 데코레이터 팩토리.

    사용: @log_action(Path("data/ledger.log"))
    기록 형식: 2026-10-28 12:00:00 | add | ok(0)
    로그 기록 실패는 본 기능을 막아서는 안 되므로 조용히 무시한다.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            result = func(*args, **kwargs)
            status = "ok" if result in (None, 0) else f"fail({result})"
            if log_path is not None:
                try:
                    log_path.parent.mkdir(parents=True, exist_ok=True)
                    with log_path.open("a", encoding="utf-8") as f:
                        f.write(f"{started} | {func.__name__} | {status}\n")
                except OSError:
                    pass
            return result

        return wrapper

    return decorator


def timed(func: Callable[P, R]) -> Callable[P, R]:
    """LEDGER_TIMING=1 일 때만 실행 시간을 stderr 로 출력한다 (대용량 성능 실험용)."""

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        t0 = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            if os.environ.get("LEDGER_TIMING"):
                print(f"[시간] {func.__name__}: {(time.perf_counter() - t0) * 1000:.1f} ms", file=sys.stderr)

    return wrapper
