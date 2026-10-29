"""
errors.py — 프로그램 전용 예외 계층 정의

[설계 의도]
- 사용자가 잘못된 입력을 주거나 파일에 문제가 생겼을 때, Python 기본 예외
  (ValueError, FileNotFoundError 등)를 그대로 노출하면 스택트레이스가 출력되어
  일반 사용자가 이해하기 어렵다.
- 따라서 모든 "예상 가능한 오류"는 LedgerError 계열로 변환해 던지고,
  cli.py 의 @handle_errors 데코레이터가 이를 한 곳에서 받아
  "오류 메시지 + 해결 힌트 + 종료 코드" 형태로 출력한다.
- 종료 코드(exit_code)를 예외 클래스에 붙여 두면, 셸 스크립트나 CI에서
  `echo $?` / `echo %ERRORLEVEL%` 로 실패 종류를 구분할 수 있다.

[종료 코드 규약]
  0 : 정상 종료
  1 : 사용자 입력 오류 (잘못된 날짜·금액·카테고리 등)
  2 : 파일/저장소 오류 (파일 손상, 권한 문제, CSV 스키마 불일치 등)
  3 : 대상 없음 (존재하지 않는 거래 ID, 백업 이름 등)
"""

from __future__ import annotations


class LedgerError(Exception):
    """모든 가계부 예외의 공통 부모 클래스.

    Attributes:
        message: 사용자에게 보여줄 한 줄 오류 설명
        hint:    문제를 해결하기 위한 구체적인 조치 안내 (없으면 None)
        exit_code: 프로세스 종료 코드 (하위 클래스에서 재정의)
    """

    exit_code: int = 1  # 기본값: 사용자 입력 오류

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:  # print(e) 시 메시지만 보이도록
        return self.message


class ValidationError(LedgerError):
    """입력값 검증 실패 (날짜 형식, 금액 범위, 거래 유형 등). exit 1"""

    exit_code = 1


class NotFoundError(LedgerError):
    """조회 대상이 존재하지 않음 (거래 ID, 카테고리, 백업명 등). exit 3"""

    exit_code = 3


class CategoryInUseError(LedgerError):
    """사용 중인 카테고리를 삭제하려 할 때. exit 1"""

    exit_code = 1


class StorageError(LedgerError):
    """파일 읽기/쓰기 실패, JSON 손상, CSV 스키마 불일치 등. exit 2"""

    exit_code = 2
