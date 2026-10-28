from __future__ import annotations

import calendar
import itertools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from .csv_io import ImportError_, ImportResult, export_csv, parse_csv
from .errors import CategoryInUseError, NotFoundError, StorageError, ValidationError
from .models import (
    DEFAULT_CATEGORY,
    Budget,
    Category,
    RecurringRule,
    Transaction,
    validate_amount,
    validate_category_name,
    validate_date,
    validate_month,
    validate_tx_type,
)
from .storage import BackupManager, JsonlStore

# 저장 파일 이름 (data/ 아래). 요구사항 "저장 파일 3개 이상" → 4개 사용.
TX_FILE = "transactions.jsonl"
CATEGORY_FILE = "categories.jsonl"
BUDGET_FILE = "budgets.jsonl"
RECURRING_FILE = "recurring.jsonl"
DATA_FILES: tuple[str, ...] = (TX_FILE, CATEGORY_FILE, BUDGET_FILE, RECURRING_FILE)

# 첫 실행 시 자동 생성되는 기본 카테고리
SEED_CATEGORIES: tuple[str, ...] = ("식비", "교통", "주거", "급여", DEFAULT_CATEGORY)

# 반복 거래로 생성된 메모에 붙는 꼬리표. 중복 생성 방지의 2차 안전장치로 쓰인다.
RECURRING_TAG = "[반복#{rule_id}]"


# ---------------------------------------------------------------------------
# 카테고리
# ---------------------------------------------------------------------------


class CategoryService:
    """카테고리 추가/조회/삭제. 삭제 시 거래·예산·반복규칙의 참조를 정리한다."""

    def __init__(
        self,
        store: JsonlStore[Category],
        tx_store: JsonlStore[Transaction],
        budget_store: JsonlStore[Budget],
        recurring_store: JsonlStore[RecurringRule],
    ) -> None:
        self._store = store
        self._tx_store = tx_store
        self._budget_store = budget_store
        self._recurring_store = recurring_store

    def ensure_seed(self) -> None:
        """categories.jsonl 이 아직 없으면 기본 카테고리를 심는다 (최초 1회)."""
        if not self._store.path.exists():
            self._store.write_all(Category(name=n) for n in SEED_CATEGORIES)

    def names(self) -> list[str]:
        return [c.name for c in self._store.iter_all()]

    def exists(self, name: str) -> bool:
        return name in self.names()

    def require(self, name: str) -> str:
        """카테고리가 존재해야 하는 자리에서 호출. 없으면 친절한 힌트와 함께 실패."""
        name = validate_category_name(name)
        if not self.exists(name):
            raise NotFoundError(
                f"존재하지 않는 카테고리입니다: {name}",
                hint=f"`category add {name}` 으로 먼저 등록하거나 `category list` 로 목록을 확인하세요.",
            )
        return name

    def list(self) -> list[Category]:
        return self._store.read_all()

    def add(self, name: str) -> Category:
        cat = Category(name=name)
        if self.exists(cat.name):
            raise ValidationError(f"이미 존재하는 카테고리입니다: {cat.name}")
        self._store.append(cat)
        return cat

    def usage_count(self, name: str) -> int:
        """해당 카테고리를 쓰는 거래 수 (제너레이터로 세므로 메모리 부담 없음)."""
        return sum(1 for tx in self._tx_store.iter_all() if tx.category == name)

    def remove(self, name: str, reassign_to: str | None = None) -> dict[str, int]:
        """카테고리를 삭제한다.

        - 사용 중인 거래가 있는데 reassign_to 가 없으면 CategoryInUseError (안전 기본값).
        - reassign_to 가 주어지면: 거래·반복규칙의 카테고리를 옮기고, 해당 카테고리의
          예산은 삭제한다(예산은 카테고리별 한도이므로 다른 카테고리로 합치는 것이 부자연스러움).
        - 각 파일은 write_all(원자적)로 기록한다.

        Returns:
            {"transactions": 옮긴 거래 수, "budgets": 삭제한 예산 수, "recurring": 옮긴 규칙 수}
        """
        name = self.require(name)
        used = self.usage_count(name)

        if used and reassign_to is None:
            raise CategoryInUseError(
                f"카테고리 '{name}' 은(는) 거래 {used}건에서 사용 중이라 삭제할 수 없습니다.",
                hint=f"`category remove {name} --reassign {DEFAULT_CATEGORY}` 처럼 옮길 카테고리를 지정하세요.",
            )

        moved_tx = moved_rules = removed_budgets = 0
        if reassign_to is not None:
            reassign_to = validate_category_name(reassign_to)
            if reassign_to == name:
                raise ValidationError("삭제할 카테고리와 옮길 카테고리가 같습니다.")
            if not self.exists(reassign_to):
                self._store.append(Category(name=reassign_to))  # 없으면 자동 생성

            # 1) 거래 재할당
            txs = self._tx_store.read_all()
            for tx in txs:
                if tx.category == name:
                    tx.category = reassign_to
                    moved_tx += 1
            if moved_tx:
                self._tx_store.write_all(txs)

            # 2) 반복 규칙 재할당
            rules = self._recurring_store.read_all()
            for r in rules:
                if r.category == name:
                    r.category = reassign_to
                    moved_rules += 1
            if moved_rules:
                self._recurring_store.write_all(rules)

        # 3) 예산 정리 (사용 여부와 무관하게 해당 카테고리 예산은 제거)
        budgets = self._budget_store.read_all()
        kept = [b for b in budgets if b.category != name]
        removed_budgets = len(budgets) - len(kept)
        if removed_budgets:
            self._budget_store.write_all(kept)

        # 4) 카테고리 자체 삭제 (마지막에 수행 → 앞 단계가 실패하면 카테고리는 남아 있어 재시도 가능)
        self._store.write_all(c for c in self._store.read_all() if c.name != name)
        return {"transactions": moved_tx, "budgets": removed_budgets, "recurring": moved_rules}


# ---------------------------------------------------------------------------
# 거래
# ---------------------------------------------------------------------------


@dataclass
class Summary:
    """summary 명령의 계산 결과 묶음 (출력은 cli.py 가 담당)."""

    month: str | None
    income: int = 0
    expense: int = 0
    count: int = 0
    by_category: dict[str, int] = field(default_factory=dict)   # 지출 카테고리별 합계
    budget_rows: list["BudgetUsage"] = field(default_factory=list)

    @property
    def net(self) -> int:
        return self.income - self.expense


@dataclass
class BudgetUsage:
    """예산 1건의 사용 현황."""

    category: str
    limit: int
    used: int

    @property
    def ratio(self) -> float:
        return self.used / self.limit if self.limit else 0.0

    @property
    def status(self) -> str:
        if self.used > self.limit:
            return "초과"
        if self.ratio >= 0.8:
            return "주의"
        return "정상"


class TransactionService:
    """거래 추가/조회/검색/수정/삭제/집계 + CSV 교환."""

    def __init__(self, store: JsonlStore[Transaction], categories: CategoryService) -> None:
        self._store = store
        self._categories = categories

    # --- ID ----------------------------------------------------------------
    def next_id(self) -> int:
        """현재 최대 ID + 1. 제너레이터로 훑으므로 전체를 메모리에 올리지 않는다.

        (10만 건 규모에서는 O(n) 스캔이 되므로 README 의 '병목' 항목에서 개선안을 다룬다.)
        """
        return max((tx.id for tx in self._store.iter_all()), default=0) + 1

    # --- 생성 --------------------------------------------------------------
    def add(self, date: str, type: str, category: str, amount: int | str, memo: str = "") -> Transaction:
        tx = Transaction(
            id=self.next_id(),
            date=validate_date(date),
            type=validate_tx_type(type),
            category=self._categories.require(category),
            amount=validate_amount(amount),
            memo=memo,
        )
        self._store.append(tx)  # JSONL 의 장점: 한 줄 append
        return tx

    # --- 조회(제너레이터) --------------------------------------------------
    def iter_filtered(
        self,
        month: str | None = None,
        type: str | None = None,
        category: str | None = None,
        keyword: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        min_amount: int | None = None,
        max_amount: int | None = None,
    ) -> Iterator[Transaction]:
        """조건에 맞는 거래를 "발견하는 즉시" 하나씩 내보내는 제너레이터.

        - list 와 search 가 모두 이 함수를 쓴다 (list = 조건이 적은 search).
        - 파일 → json.loads → 조건 검사 → yield 가 한 건 단위로 파이프라인처럼 흐르므로,
          거래가 아무리 많아도 메모리에는 한 건만 머문다.
        - 호출자가 중간에 멈추면(예: --limit 5) 나머지 파일은 읽지도 않는다.
        """
        if month:
            validate_month(month)
        if type:
            validate_tx_type(type)
        if date_from:
            validate_date(date_from)
        if date_to:
            validate_date(date_to)
        kw = keyword.lower() if keyword else None

        for tx in self._store.iter_all():
            if month and tx.month != month:
                continue
            if type and tx.type != type:
                continue
            if category and tx.category != category:
                continue
            if date_from and tx.date < date_from:    # ISO 날짜는 문자열 비교 = 시간 비교
                continue
            if date_to and tx.date > date_to:
                continue
            if min_amount is not None and tx.amount < min_amount:
                continue
            if max_amount is not None and tx.amount > max_amount:
                continue
            if kw and kw not in tx.memo.lower() and kw not in tx.category.lower():
                continue
            yield tx

    def get(self, tx_id: int) -> Transaction:
        for tx in self._store.iter_all():
            if tx.id == tx_id:
                return tx
        raise NotFoundError(
            f"거래 ID {tx_id} 를 찾을 수 없습니다.",
            hint="`list` 명령으로 존재하는 ID 를 확인하세요.",
        )

    # --- 수정 / 삭제 (원자적) ---------------------------------------------
    def update(
        self,
        tx_id: int,
        *,
        date: str | None = None,
        type: str | None = None,
        category: str | None = None,
        amount: int | str | None = None,
        memo: str | None = None,
    ) -> Transaction:
        """지정 필드만 바꾼다. 하나도 안 주면 오류.

        처리 순서(안전성):
          1) 전체 읽기 → 2) 메모리에서 대상 교체(검증 포함) → 3) write_all(임시 파일 + os.replace)
        3) 이 중간에 죽어도 원본은 그대로 남는다.
        """
        if all(v is None for v in (date, type, category, amount, memo)):
            raise ValidationError(
                "변경할 항목이 없습니다.",
                hint="--date / --type / --category / --amount / --memo 중 하나 이상을 지정하세요.",
            )
        txs = self._store.read_all()
        for i, tx in enumerate(txs):
            if tx.id == tx_id:
                new_tx = Transaction(
                    id=tx.id,
                    date=date if date is not None else tx.date,
                    type=type if type is not None else tx.type,
                    category=self._categories.require(category) if category is not None else tx.category,
                    amount=amount if amount is not None else tx.amount,
                    memo=memo if memo is not None else tx.memo,
                )
                txs[i] = new_tx
                self._store.write_all(txs)
                return new_tx
        raise NotFoundError(f"거래 ID {tx_id} 를 찾을 수 없습니다.", hint="`list` 로 ID 를 확인하세요.")

    def delete(self, tx_id: int) -> Transaction:
        """대상을 제외한 나머지를 원자적으로 다시 쓴다."""
        txs = self._store.read_all()
        remaining = [tx for tx in txs if tx.id != tx_id]
        if len(remaining) == len(txs):
            raise NotFoundError(f"거래 ID {tx_id} 를 찾을 수 없습니다.", hint="`list` 로 ID 를 확인하세요.")
        deleted = next(tx for tx in txs if tx.id == tx_id)
        self._store.write_all(remaining)
        return deleted

    # --- 집계 --------------------------------------------------------------
    def summarize(self, month: str | None, budgets: list[Budget]) -> Summary:
        """월(또는 전체) 수입/지출/순액, 카테고리별 지출, 예산 사용률을 한 번의 순회로 계산."""
        s = Summary(month=month)
        for tx in self.iter_filtered(month=month):
            s.count += 1
            if tx.type == "income":
                s.income += tx.amount
            else:
                s.expense += tx.amount
                s.by_category[tx.category] = s.by_category.get(tx.category, 0) + tx.amount
        for b in budgets:
            if month is None or b.month == month:
                s.budget_rows.append(BudgetUsage(b.category, b.amount, s.by_category.get(b.category, 0)))
        s.budget_rows.sort(key=lambda r: r.ratio, reverse=True)
        return s

    # --- CSV ---------------------------------------------------------------
    def export(self, out_path: Path, month: str | None = None) -> int:
        """제너레이터를 그대로 넘겨 스트리밍으로 기록한다."""
        return export_csv(self.iter_filtered(month=month), out_path)

    def import_csv(self, path: Path, mode: str = "partial", create_categories: bool = False) -> ImportResult:
        """CSV 를 읽어 거래를 추가한다.

        Args:
            mode: 'partial' → 정상 행만 저장, 오류 행은 리포트 / 'strict' → 오류가 있으면 전체 중단
            create_categories: 미등록 카테고리를 자동 등록할지 여부(False 면 해당 행은 오류 처리)

        저장은 write_all 한 번으로 끝나므로 "절반만 들어간" 상태는 없다.
        """
        if mode not in ("partial", "strict"):
            raise ValidationError(f"mode 는 partial 또는 strict 여야 합니다: {mode}")

        result = parse_csv(path, itertools.count(self.next_id()))

        # 카테고리 존재 여부는 csv_io 가 모르는 "업무 규칙" 이므로 여기서 검사한다.
        known = set(self._categories.names())
        still_valid: list[tuple[int, Transaction]] = []
        for line_no, tx in result.valid:
            if tx.category in known:
                still_valid.append((line_no, tx))
            elif create_categories:
                self._categories.add(tx.category)
                known.add(tx.category)
                still_valid.append((line_no, tx))
            else:
                result.errors.append(ImportError_(
                    line_no=line_no,
                    reason=f"미등록 카테고리: {tx.category} (--create-categories 로 자동 등록 가능)",
                    raw={**tx.to_dict(), "id": ""},   # id 는 아직 발급 전이므로 비워서 표시
                ))
        result.valid = still_valid
        result.errors.sort(key=lambda e: e.line_no)

        if mode == "strict" and result.errors:
            raise StorageError(
                f"strict 모드: 오류 행 {len(result.errors)}건이 있어 아무것도 저장하지 않았습니다.",
                hint="오류 행을 수정하거나 `--mode partial` 로 정상 행만 가져오세요.",
            )
        if result.valid:
            # 오류 행이 중간에 ID 를 소비했을 수 있으므로 연속되게 다시 번호를 매긴 뒤 한 번에 기록
            existing = self._store.read_all()
            next_no = max((t.id for t in existing), default=0) + 1
            new_txs: list[Transaction] = []
            for _, tx in result.valid:
                tx.id = next_no
                next_no += 1
                new_txs.append(tx)
            self._store.write_all(existing + new_txs)
        return result


# ---------------------------------------------------------------------------
# 예산
# ---------------------------------------------------------------------------


class BudgetService:
    """월별·카테고리별 예산 설정/조회."""

    def __init__(self, store: JsonlStore[Budget], categories: CategoryService) -> None:
        self._store = store
        self._categories = categories

    def set(self, month: str, category: str, amount: int | str) -> Budget:
        """같은 (월, 카테고리) 가 있으면 덮어쓰고, 없으면 추가한다 — 원자적 write_all."""
        b = Budget(month=month, category=self._categories.require(category), amount=amount)
        budgets = [x for x in self._store.read_all() if x.key != b.key]
        budgets.append(b)
        budgets.sort(key=lambda x: x.key)
        self._store.write_all(budgets)
        return b

    def list(self, month: str | None = None) -> list[Budget]:
        if month:
            validate_month(month)
        return [b for b in self._store.iter_all() if month is None or b.month == month]


# ---------------------------------------------------------------------------
# 반복 내역 (보너스)
# ---------------------------------------------------------------------------


class RecurringService:
    """매월 반복되는 거래 규칙을 저장하고, 월 단위로 실제 거래를 생성한다."""

    def __init__(
        self,
        store: JsonlStore[RecurringRule],
        tx_service: TransactionService,
        categories: CategoryService,
    ) -> None:
        self._store = store
        self._tx = tx_service
        self._categories = categories

    def add(self, day: int, type: str, category: str, amount: int | str, memo: str = "") -> RecurringRule:
        rule = RecurringRule(
            id=max((r.id for r in self._store.iter_all()), default=0) + 1,
            day=day,
            type=type,
            category=self._categories.require(category),
            amount=amount,
            memo=memo,
        )
        self._store.append(rule)
        return rule

    def list(self) -> list[RecurringRule]:
        return self._store.read_all()

    def remove(self, rule_id: int) -> RecurringRule:
        rules = self._store.read_all()
        target = next((r for r in rules if r.id == rule_id), None)
        if target is None:
            raise NotFoundError(f"반복 규칙 ID {rule_id} 를 찾을 수 없습니다.", hint="`recurring list` 로 확인하세요.")
        self._store.write_all(r for r in rules if r.id != rule_id)
        return target

    def apply(self, month: str) -> list[Transaction]:
        """month 에 해당하는 반복 거래를 생성한다. 이미 생성한 규칙은 건너뛴다.

        중복 방지 2중 장치:
          1) rule.applied_months 에 month 가 있으면 건너뜀
          2) 거래 메모에 '[반복#id]' 꼬리표가 붙은 같은 달 거래가 있으면 건너뜀
             (1)을 기록하기 직전에 프로세스가 죽었을 때를 대비)
        """
        validate_month(month)
        year, mon = int(month[:4]), int(month[5:7])
        last_day = calendar.monthrange(year, mon)[1]

        # 2차 장치용: 이 달에 이미 생성된 반복 거래의 규칙 ID 집합
        already: set[str] = set()
        for tx in self._tx.iter_filtered(month=month):
            tag = tx.memo.rsplit(" ", 1)[-1]   # 메모의 마지막 토큰이 꼬리표
            if tag.startswith("[반복#"):
                already.add(tag)

        rules = self._store.read_all()
        created: list[Transaction] = []
        for r in rules:
            tag = RECURRING_TAG.format(rule_id=r.id)
            if month in r.applied_months or tag in already:
                continue
            day = min(r.day, last_day)   # 31일 규칙이 2월이면 28/29일로 보정
            memo = f"{r.memo} {tag}".strip()
            tx = self._tx.add(f"{year:04d}-{mon:02d}-{day:02d}", r.type, r.category, r.amount, memo)
            created.append(tx)
            r.applied_months.append(month)
        if created:
            self._store.write_all(rules)
        return created


# ---------------------------------------------------------------------------
# 조립(assembly)
# ---------------------------------------------------------------------------


class LedgerApp:
    """저장소 4개와 서비스 4개를 한 번만 만들어 cli.py 에 제공한다.

    data_dir 를 바꾸면 전혀 다른 가계부를 열 수 있으므로
    테스트에서는 임시 디렉터리를 넘겨 실제 데이터와 격리한다.
    """

    def __init__(self, data_dir: Path, backup_dir: Path | None = None) -> None:
        self.data_dir = data_dir
        self.backup_dir = backup_dir or data_dir.parent / "backups"

        tx_store: JsonlStore[Transaction] = JsonlStore(data_dir / TX_FILE, Transaction.from_dict)
        cat_store: JsonlStore[Category] = JsonlStore(data_dir / CATEGORY_FILE, Category.from_dict)
        budget_store: JsonlStore[Budget] = JsonlStore(data_dir / BUDGET_FILE, Budget.from_dict)
        rec_store: JsonlStore[RecurringRule] = JsonlStore(data_dir / RECURRING_FILE, RecurringRule.from_dict)

        self.categories = CategoryService(cat_store, tx_store, budget_store, rec_store)
        self.categories.ensure_seed()
        self.transactions = TransactionService(tx_store, self.categories)
        self.budgets = BudgetService(budget_store, self.categories)
        self.recurring = RecurringService(rec_store, self.transactions, self.categories)
        self.backup = BackupManager(data_dir, self.backup_dir, DATA_FILES)
