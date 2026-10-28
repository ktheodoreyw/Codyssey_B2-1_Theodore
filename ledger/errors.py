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
