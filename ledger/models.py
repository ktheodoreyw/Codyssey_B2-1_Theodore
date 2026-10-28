from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, ClassVar, Final, Literal

from .errors import ValidationError

# ---------------------------------------------------------------------------
# 공통 상수 / 타입 별칭
# ---------------------------------------------------------------------------

# 거래 유형은 수입(income) 또는 지출(expense) 두 가지만 허용한다.
# Literal 타입을 쓰면 "income" / "expense" 이외의 문자열이 들어오는 코드를
# 정적 검사기가 미리 잡아낼 수 있다.
TxType = Literal["income", "expense"]
TX_TYPES: Final[tuple[str, ...]] = ("income", "expense")

# 사용자에게 보여줄 때 쓰는 한글 라벨
TX_TYPE_LABEL: Final[dict[str, str]] = {"income": "수입", "expense": "지출"}

# 날짜 형식은 ISO 8601 (YYYY-MM-DD) 로 고정 → 문자열 정렬 = 시간 정렬이 되어 편리하다.
_DATE_RE: Final[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE: Final[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}$")

# 카테고리 삭제 시, 해당 카테고리를 쓰던 거래가 옮겨갈 기본 카테고리
DEFAULT_CATEGORY: Final[str] = "기타"


# ---------------------------------------------------------------------------
# 검증 헬퍼 함수 (모델 여러 곳에서 재사용)
# ---------------------------------------------------------------------------

def validate_date(value: str) -> str:
    """'YYYY-MM-DD' 문자열인지, 실제 달력상 존재하는 날짜인지 검사한다.

    예: '2026-02-30' 은 형식은 맞지만 존재하지 않는 날짜이므로 거부된다.
    """
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise ValidationError(
            f"날짜 형식이 올바르지 않습니다: {value!r}",
            hint="YYYY-MM-DD 형식으로 입력하세요. 예) 2026-10-28",
        )
    try:
        date.fromisoformat(value)  # 실제 존재하는 날짜인지 확인
    except ValueError:
        raise ValidationError(
            f"존재하지 않는 날짜입니다: {value}",
            hint="월(01~12)과 일(01~31) 범위를 확인하세요.",
        ) from None
    return value


def validate_month(value: str) -> str:
    """'YYYY-MM' 형식인지 검사한다 (summary / budget / recurring apply 에서 사용)."""
    if not isinstance(value, str) or not _MONTH_RE.match(value):
        raise ValidationError(
            f"월 형식이 올바르지 않습니다: {value!r}",
            hint="YYYY-MM 형식으로 입력하세요. 예) 2026-10",
        )
    month = int(value[5:7])
    if not 1 <= month <= 12:
        raise ValidationError(f"월은 01~12 사이여야 합니다: {value}")
    return value


def validate_tx_type(value: str) -> str:
    """거래 유형이 income / expense 중 하나인지 검사한다."""
    if value not in TX_TYPES:
        raise ValidationError(
            f"거래 유형이 올바르지 않습니다: {value!r}",
            hint="income(수입) 또는 expense(지출) 중 하나를 입력하세요.",
        )
    return value


def validate_amount(value: Any) -> int:
    """금액을 정수(원 단위)로 변환하고 0 초과인지 검사한다.

    - 문자열 '12,000' 처럼 천 단위 구분자가 섞여 있어도 허용한다.
    - 실수(소수점)는 원 단위 가계부에서 의미가 없으므로 거부한다.
    """
    try:
        if isinstance(value, bool):  # bool 은 int 의 하위 타입이라 별도 차단
            raise TypeError
        if isinstance(value, str):
            value = value.replace(",", "").strip()
        amount = int(value)
    except (TypeError, ValueError):
        raise ValidationError(
            f"금액은 정수여야 합니다: {value!r}",
            hint="예) --amount 12000  (소수점·문자 불가, 쉼표는 허용)",
        ) from None
    if amount <= 0:
        raise ValidationError(
            f"금액은 0보다 커야 합니다: {amount}",
            hint="환불 등 음수 금액은 type 을 income 으로 입력하세요.",
        )
    return amount


def validate_category_name(value: str) -> str:
    """카테고리 이름: 공백 제거 후 1~20자, 비어 있으면 거부."""
    name = (value or "").strip()
    if not name:
        raise ValidationError("카테고리 이름이 비어 있습니다.")
    if len(name) > 20:
        raise ValidationError(
            f"카테고리 이름이 너무 깁니다({len(name)}자): {name}",
            hint="20자 이하로 입력하세요.",
        )
    return name


# ---------------------------------------------------------------------------
# 1) 거래(Transaction)
# ---------------------------------------------------------------------------

@dataclass
class Transaction:
    """가계부의 핵심 단위인 '거래 1건'.

    Fields:
        id:       1부터 증가하는 정수 식별자 (update / delete 의 대상 지정용)
        date:     거래일 'YYYY-MM-DD'
        type:     'income' | 'expense'
        category: 카테고리 이름 (Category 모델과 이름으로 연결)
        amount:   금액(원, 양의 정수)
        memo:     자유 메모 (search 의 키워드 검색 대상)
    """

    # 클래스 변수: CSV export/import 시 사용하는 컬럼 순서를 모델이 "소유"한다.
    # → csv_io.py 가 이 값을 참조하므로, 컬럼이 바뀌어도 한 곳만 고치면 된다.
    CSV_COLUMNS: ClassVar[tuple[str, ...]] = (
        "id", "date", "type", "category", "amount", "memo",
    )

    id: int
    date: str
    type: str
    category: str
    amount: int
    memo: str = ""

    def __post_init__(self) -> None:
        """dataclass 생성 직후 자동 호출 → 생성 시점에 항상 검증이 보장된다."""
        self.validate()

    def validate(self) -> None:
        """모든 필드를 검증하고, 정규화된 값으로 갱신한다."""
        if not isinstance(self.id, int) or isinstance(self.id, bool) or self.id < 1:
            raise ValidationError(f"거래 ID 는 1 이상의 정수여야 합니다: {self.id!r}")
        self.date = validate_date(self.date)
        self.type = validate_tx_type(self.type)
        self.category = validate_category_name(self.category)
        self.amount = validate_amount(self.amount)
        self.memo = (self.memo or "").strip()

    # --- 직렬화 ------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """JSONL 한 줄로 저장할 dict 로 변환."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Transaction":
        """dict(JSONL 한 줄 또는 CSV 한 행) → Transaction.

        필수 키가 빠져 있으면 KeyError 대신 ValidationError 로 바꿔 던진다.
        """
        try:
            return cls(
                id=int(data["id"]),
                date=str(data["date"]),
                type=str(data["type"]),
                category=str(data["category"]),
                amount=data["amount"],
                memo=str(data.get("memo", "")),
            )
        except KeyError as e:
            raise ValidationError(f"필수 항목이 없습니다: {e.args[0]}") from None

    # --- 편의 속성 ---------------------------------------------------------
    @property
    def month(self) -> str:
        """'2026-10-28' → '2026-10' (월별 집계용)."""
        return self.date[:7]

    @property
    def signed_amount(self) -> int:
        """수입은 +, 지출은 - 로 부호를 붙인 금액 (순이익 계산용)."""
        return self.amount if self.type == "income" else -self.amount


# ---------------------------------------------------------------------------
# 2) 카테고리(Category)
# ---------------------------------------------------------------------------

@dataclass
class Category:
    """거래 분류용 카테고리. 이름이 곧 식별자(유일)이다."""

    name: str
    created_at: str = field(default_factory=lambda: date.today().isoformat())

    def __post_init__(self) -> None:
        self.name = validate_category_name(self.name)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Category":
        try:
            return cls(name=str(data["name"]), created_at=str(data.get("created_at", "")))
        except KeyError as e:
            raise ValidationError(f"필수 항목이 없습니다: {e.args[0]}") from None


# ---------------------------------------------------------------------------
# 3) 예산(Budget)
# ---------------------------------------------------------------------------

@dataclass
class Budget:
    """특정 월 + 카테고리에 대한 지출 한도.

    (month, category) 쌍이 유일 키 역할을 한다.
    같은 쌍으로 다시 set 하면 금액을 덮어쓴다.
    """

    month: str      # 'YYYY-MM'
    category: str
    amount: int     # 한도 금액(원)

    def __post_init__(self) -> None:
        self.month = validate_month(self.month)
        self.category = validate_category_name(self.category)
        self.amount = validate_amount(self.amount)

    @property
    def key(self) -> tuple[str, str]:
        """중복 판별용 복합 키."""
        return (self.month, self.category)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Budget":
        try:
            return cls(month=str(data["month"]), category=str(data["category"]), amount=data["amount"])
        except KeyError as e:
            raise ValidationError(f"필수 항목이 없습니다: {e.args[0]}") from None


# ---------------------------------------------------------------------------
# 4) 반복 내역 규칙(RecurringRule) — 보너스 기능
# ---------------------------------------------------------------------------

@dataclass
class RecurringRule:
    """매달 같은 날 반복되는 거래(월세, 급여, 구독료 등)의 템플릿.

    Fields:
        id:        규칙 식별자
        day:       매월 며칠에 발생하는지 (1~31; 해당 월에 없는 날이면 말일로 보정)
        type / category / amount / memo: 생성될 거래의 내용
        applied_months: 이미 거래를 생성한 월 목록 → 같은 달에 두 번 생성되는 것을 막는다.
    """

    id: int
    day: int
    type: str
    category: str
    amount: int
    memo: str = ""
    applied_months: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.id, int) or self.id < 1:
            raise ValidationError(f"규칙 ID 는 1 이상의 정수여야 합니다: {self.id!r}")
        try:
            self.day = int(self.day)
        except (TypeError, ValueError):
            raise ValidationError(f"day 는 정수여야 합니다: {self.day!r}") from None
        if not 1 <= self.day <= 31:
            raise ValidationError(
                f"day 는 1~31 사이여야 합니다: {self.day}",
                hint="예) --day 25  (해당 월에 없는 날짜는 자동으로 말일로 조정됩니다)",
            )
        self.type = validate_tx_type(self.type)
        self.category = validate_category_name(self.category)
        self.amount = validate_amount(self.amount)
        self.memo = (self.memo or "").strip()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RecurringRule":
        try:
            return cls(
                id=int(data["id"]),
                day=data["day"],
                type=str(data["type"]),
                category=str(data["category"]),
                amount=data["amount"],
                memo=str(data.get("memo", "")),
                applied_months=list(data.get("applied_months", [])),
            )
        except KeyError as e:
            raise ValidationError(f"필수 항목이 없습니다: {e.args[0]}") from None
