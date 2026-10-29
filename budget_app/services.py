"""
services.py — 업무 규칙(비즈니스 로직) 계층

[이 모듈의 책임]
- "가계부로서 지켜야 할 규칙" 을 구현한다.
    예) 없는 카테고리로 거래를 추가할 수 없다 / 사용 중인 카테고리는 함부로 지울 수 없다 /
        예산 사용률은 어떻게 계산한다 / 반복 거래는 한 달에 한 번만 생성한다
- 파일 입출력은 storage.JsonlStore 에, 값 검증은 models 에 맡기고
  이 모듈은 두 계층을 "조합" 만 한다.
- 콘솔 출력(print / input)을 하지 않는다 → 결과를 값으로 반환하고, 입출력은 cli.py 가 담당.
  (그래서 단위 테스트에서 print 를 가로채지 않고도 결과를 검증할 수 있다.)

[클래스 책임 경계 — 평가 항목 2]
  TransactionService : 거래 CRUD + 검색/집계 + CSV 교환
  CategoryService    : 카테고리 목록 관리 + "사용 중" 판정 + 재할당 삭제
  BudgetService      : 월 예산 저장/조회
  RecurringService   : 반복 규칙 저장 + 월 단위 거래 생성
  LedgerApp          : 위 서비스들이 공유하는 저장소를 한 번만 만들어 묶어 주는 조립(assembly) 역할
"""

from __future__ import annotations

import builtins
import calendar
import heapq
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
    parse_tags,
    validate_amount,
    validate_category_name,
    validate_date,
    validate_month,
    validate_tx_type,
)
from .storage import BackupManager, JsonlStore

# 저장 파일 이름 (data/ 아래). 명세 "저장 파일 3개 이상" → 4개 사용.
TX_FILE = "transactions.jsonl"
CATEGORY_FILE = "categories.jsonl"
BUDGET_FILE = "budgets.jsonl"
RECURRING_FILE = "recurring.jsonl"
DATA_FILES: tuple[str, ...] = (TX_FILE, CATEGORY_FILE, BUDGET_FILE, RECURRING_FILE)

# 첫 실행 시 자동 생성되는 기본 카테고리 (명세 3-④ "안 A: 기본 카테고리 자동 생성")
SEED_CATEGORIES: tuple[str, ...] = ("식비", "교통", "주거", "급여", DEFAULT_CATEGORY)

# 반복 거래로 생성된 거래에 붙는 태그. 중복 생성 방지의 2차 안전장치로 쓰인다.
RECURRING_TAG = "반복#{rule_id}"


# ---------------------------------------------------------------------------
# 카테고리
# ---------------------------------------------------------------------------


class CategoryService:
    """카테고리 추가/조회/삭제. 삭제 시 거래·반복규칙의 참조를 정리한다."""

    def __init__(
        self,
        store: JsonlStore[Category],
        tx_store: JsonlStore[Transaction],
        recurring_store: JsonlStore[RecurringRule],
    ) -> None:
        self._store = store
        self._tx_store = tx_store
        self._recurring_store = recurring_store

    def ensure_seed(self) -> bool:
        """categories.jsonl 이 아직 없으면 기본 카테고리를 심는다 (최초 1회).

        Returns: 이번 호출에서 새로 생성했으면 True (cli 가 초기화 안내 메시지를 띄우는 데 사용)
        """
        if self._store.path.exists():
            return False
        self._store.write_all(Category(name=n) for n in SEED_CATEGORIES)
        return True

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
        """카테고리를 삭제한다 (명세 10: 사용 중이면 삭제를 막거나 대체 카테고리를 요구).

        - 사용 중인 거래가 있는데 reassign_to 가 없으면 CategoryInUseError (안전 기본값).
        - reassign_to 가 주어지면: 거래·반복규칙의 카테고리를 옮긴다 (대체 카테고리가 없으면 자동 생성).
        - 각 파일은 write_all(원자적)로 기록하고, 카테고리 자체 삭제는 마지막에 수행한다
          → 앞 단계가 실패해도 카테고리가 남아 있어 재시도 가능.

        Returns:
            {"transactions": 옮긴 거래 수, "recurring": 옮긴 규칙 수}
        """
        name = self.require(name)
        used = self.usage_count(name)

        if used and reassign_to is None:
            raise CategoryInUseError(
                f"카테고리 '{name}' 은(는) 거래 {used}건에서 사용 중이라 삭제할 수 없습니다.",
                hint=f"`category remove {name} -reassign {DEFAULT_CATEGORY}` 처럼 옮길 카테고리를 지정하세요.",
            )

        moved_tx = moved_rules = 0
        if reassign_to is not None:
            reassign_to = validate_category_name(reassign_to)
            if reassign_to == name:
                raise ValidationError("삭제할 카테고리와 옮길 카테고리가 같습니다.")
            if not self.exists(reassign_to):
                self._store.append(Category(name=reassign_to))

            txs = self._tx_store.read_all()
            for tx in txs:
                if tx.category == name:
                    tx.category = reassign_to
                    moved_tx += 1
            if moved_tx:
                self._tx_store.write_all(txs)

            rules = self._recurring_store.read_all()
            for r in rules:
                if r.category == name:
                    r.category = reassign_to
                    moved_rules += 1
            if moved_rules:
                self._recurring_store.write_all(rules)

        self._store.write_all(c for c in self._store.read_all() if c.name != name)
        return {"transactions": moved_tx, "recurring": moved_rules}


# ---------------------------------------------------------------------------
# 거래
# ---------------------------------------------------------------------------


@dataclass
class Summary:
    """summary 명령의 계산 결과 묶음 (출력은 cli.py 가 담당)."""

    month: str
    income: int = 0
    expense: int = 0
    count: int = 0
    by_category: dict[str, int] = field(default_factory=dict)   # 지출 카테고리별 합계
    budget: Budget | None = None

    @property
    def balance(self) -> int:
        """잔액 = 총수입 - 총지출 (명세 용어)."""
        return self.income - self.expense

    def top_categories(self, n: int) -> list[tuple[str, int]]:
        """지출이 큰 카테고리 TOP N."""
        return sorted(self.by_category.items(), key=lambda kv: kv[1], reverse=True)[:n]

    # --- 예산 사용 현황 (예산이 설정된 경우에만 의미 있음) -------------------
    @property
    def budget_ratio(self) -> float:
        return self.expense / self.budget.amount if self.budget else 0.0

    @property
    def budget_status(self) -> str:
        if not self.budget:
            return "-"
        if self.expense > self.budget.amount:
            return "초과"
        if self.budget_ratio >= 0.8:
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
    def add(
        self, date: str, type: str, category: str, amount: int | str, memo: str = "",
        tags: str | list[str] | None = None,
    ) -> Transaction:
        tx = Transaction(
            id=self.next_id(),
            date=validate_date(date),
            type=validate_tx_type(type),
            category=self._categories.require(category),
            amount=validate_amount(amount),
            memo=memo,
            tags=parse_tags(tags),
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
        tag: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> Iterator[Transaction]:
        """조건에 맞는 거래를 "발견하는 즉시" 하나씩 내보내는 제너레이터 (파일 기록순).

        - list / search / summary / export 가 모두 이 함수를 쓴다.
        - 파일 → json.loads → 조건 검사 → yield 가 한 건 단위로 파이프라인처럼 흐르므로,
          거래가 아무리 많아도 메모리에는 한 건만 머문다.
        """
        if month:
            validate_month(month)
        if type:
            type = validate_tx_type(type)
        if date_from:
            date_from = validate_date(date_from)
        if date_to:
            date_to = validate_date(date_to)
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
            if kw and kw not in tx.memo.lower():
                continue
            if tag and tag not in tx.tags:
                continue
            yield tx

    @staticmethod
    def newest_first(txs: Iterator[Transaction], limit: int = 0) -> list[Transaction]:
        """스트림을 '최신순'(날짜↓, id↓) 으로 정렬해 상위 limit 건을 돌려준다.

        - limit > 0 : heapq.nlargest 로 스트림을 한 번 훑으며 **상위 limit 건만** 메모리에 유지한다.
                      시간 O(n·log limit), 메모리 O(limit) → 10만 건이어도 limit=20 이면 20건만 들고 있다.
        - limit == 0: 전체가 필요하므로 어쩔 수 없이 전부 모아 정렬한다 (사용자가 명시적으로 선택).
        최신순 정렬은 "모든 레코드를 봐야" 결정되므로 읽기 자체를 건너뛸 수는 없지만,
        제너레이터 입력 + 고정 크기 힙 덕분에 메모리는 파일 크기와 무관하다.
        """
        if limit > 0:
            return heapq.nlargest(limit, txs, key=lambda t: t.sort_key)
        return sorted(txs, key=lambda t: t.sort_key, reverse=True)

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
        tags: str | None = None,
    ) -> Transaction:
        """지정 필드만 바꾼다. 하나도 안 주면 오류.

        처리 순서(안전성):
          1) 전체 읽기 → 2) 메모리에서 대상 교체(검증 포함) → 3) write_all(임시 파일 + os.replace)
        3) 이 중간에 죽어도 원본은 그대로 남는다.
        """
        if all(v is None for v in (date, type, category, amount, memo, tags)):
            raise ValidationError(
                "변경할 항목이 없습니다.",
                hint="-date / -type / -category / -amount / -memo / -tags 중 하나 이상을 지정하세요.",
            )
        txs = self._store.read_all()
        for i, tx in enumerate(txs):
            if tx.id == tx_id:
                new_tx = Transaction(
                    id=tx.id,
                    date=date if date is not None else tx.date,
                    type=type if type is not None else tx.type,
                    category=self._categories.require(category) if category is not None else tx.category,
                    amount=validate_amount(amount) if amount is not None else tx.amount,
                    memo=memo if memo is not None else tx.memo,
                    tags=parse_tags(tags) if tags is not None else tx.tags,
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
    def summarize(self, month: str, budget: Budget | None) -> Summary:
        """해당 월의 총수입/총지출/잔액/카테고리별 지출을 한 번의 순회로 계산."""
        s = Summary(month=validate_month(month), budget=budget)
        for tx in self.iter_filtered(month=month):
            s.count += 1
            if tx.type == "income":
                s.income += tx.amount
            else:
                s.expense += tx.amount
                s.by_category[tx.category] = s.by_category.get(tx.category, 0) + tx.amount
        return s

    # --- CSV ---------------------------------------------------------------
    def export(
        self, out_path: Path, month: str | None = None,
        date_from: str | None = None, date_to: str | None = None,
    ) -> int:
        """조건에 맞는 거래를 최신순 CSV 로 내보낸다. 조건(월 또는 기간)은 필수 (명세 11)."""
        if not month and not (date_from or date_to):
            raise ValidationError(
                "export 에는 조건이 필요합니다.",
                hint="-month YYYY-MM 또는 -from YYYY-MM-DD / -to YYYY-MM-DD 중 하나 이상을 지정하세요.",
            )
        rows = self.newest_first(self.iter_filtered(month=month, date_from=date_from, date_to=date_to))
        return export_csv(rows, out_path)

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
        new_categories: list[str] = []
        for line_no, tx in result.valid:
            if tx.category in known:
                still_valid.append((line_no, tx))
            elif create_categories:
                known.add(tx.category)
                new_categories.append(tx.category)
                still_valid.append((line_no, tx))
            else:
                result.errors.append(ImportError_(
                    line_no=line_no,
                    reason=f"미등록 카테고리: {tx.category} (-create-categories 로 자동 등록 가능)",
                    raw={**tx.to_csv_row()},
                ))
        result.valid = still_valid
        result.errors.sort(key=lambda e: e.line_no)

        if mode == "strict" and result.errors:
            raise StorageError(
                f"strict 모드: 오류 행 {len(result.errors)}건이 있어 아무것도 저장하지 않았습니다.",
                hint="오류 행을 수정하거나 `-mode partial` 로 정상 행만 가져오세요.",
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
            # 거래 저장이 성공한 뒤에 카테고리를 등록 → 거래 없이 카테고리만 남는 상태를 피한다
            for name in new_categories:
                self._categories.add(name)
        return result


# ---------------------------------------------------------------------------
# 예산 (월 단위)
# ---------------------------------------------------------------------------


class BudgetService:
    """월 예산 설정/조회 (명세 9: budget set --month YYYY-MM --amount 금액)."""

    def __init__(self, store: JsonlStore[Budget]) -> None:
        self._store = store

    def set(self, month: str, amount: int | str) -> Budget:
        """같은 월이 있으면 덮어쓰고, 없으면 추가한다 — 원자적 write_all."""
        b = Budget(month=month, amount=validate_amount(amount))
        budgets = [x for x in self._store.read_all() if x.month != b.month]
        budgets.append(b)
        budgets.sort(key=lambda x: x.month)
        self._store.write_all(budgets)
        return b

    def get(self, month: str) -> Budget | None:
        validate_month(month)
        return next((b for b in self._store.iter_all() if b.month == month), None)

    def list(self) -> list[Budget]:
        return self._store.read_all()


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

    def add(self, day: int, type: str, category: str, amount: int | str, memo: str = "",
            tags: str | None = None) -> RecurringRule:
        rule = RecurringRule(
            id=max((r.id for r in self._store.iter_all()), default=0) + 1,
            day=day,
            type=type,
            category=self._categories.require(category),
            amount=validate_amount(amount),
            memo=memo,
            tags=parse_tags(tags),
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

    def apply(self, month: str) -> builtins.list[Transaction]:
        """month 에 해당하는 반복 거래를 생성한다. 이미 생성한 규칙은 건너뛴다.

        중복 방지 2중 장치:
          1) rule.applied_months 에 month 가 있으면 건너뜀
          2) 같은 달 거래에 '반복#id' 태그가 이미 있으면 건너뜀
             (1)을 기록하기 직전에 프로세스가 죽었을 때를 대비)
        """
        validate_month(month)
        year, mon = int(month[:4]), int(month[5:7])
        last_day = calendar.monthrange(year, mon)[1]

        already: set[str] = set()
        for tx in self._tx.iter_filtered(month=month):
            already.update(t for t in tx.tags if t.startswith("반복#"))

        rules = self._store.read_all()
        created: builtins.list[Transaction] = []   # 이 클래스의 list() 메서드와 이름이 겹쳐 builtins 로 명시
        for r in rules:
            tag = RECURRING_TAG.format(rule_id=r.id)
            if month in r.applied_months or tag in already:
                continue
            day = min(r.day, last_day)   # 31일 규칙이 2월이면 28/29일로 보정
            tx = self._tx.add(f"{year:04d}-{mon:02d}-{day:02d}", r.type, r.category, r.amount,
                              r.memo, r.tags + [tag])
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

        self.categories = CategoryService(cat_store, tx_store, rec_store)
        self.initialized = self.categories.ensure_seed()   # True 면 이번 실행에서 data/ 를 새로 만든 것
        self.transactions = TransactionService(tx_store, self.categories)
        self.budgets = BudgetService(budget_store)
        self.recurring = RecurringService(rec_store, self.transactions, self.categories)
        self.backup = BackupManager(data_dir, self.backup_dir, DATA_FILES)
