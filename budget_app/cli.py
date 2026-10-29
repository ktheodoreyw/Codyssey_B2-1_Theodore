"""
cli.py — 명령줄 인터페이스(인자 파싱 + 결과 출력)

[이 모듈의 책임]
- argparse 로 명령/옵션을 해석해 services 계층의 메서드를 호출하고,
  돌아온 값을 formatters 로 표 형태로 출력한다.
- 업무 규칙은 전혀 담지 않는다 (예산 초과 판정, 중복 검사 등은 services 담당).
- 모든 핸들러는 @handle_errors 로 감싸져 있어 예외 → 메시지/힌트/종료코드 로 변환된다.

[옵션 표기 — 명세 4-①]
- 명세는 리눅스 표준 단일 대시(`-help`, `-limit`, `-from`) 로 통일하라고 하며,
  명세 예시 일부는 `--id`, `--month` 처럼 이중 대시로도 적혀 있다.
- 따라서 모든 옵션을 `-name` 과 `--name` 두 표기로 **모두** 등록한다 (_opt 헬퍼).
  평가자가 어느 쪽으로 입력해도 동작하고, 문서에는 단일 대시를 기본으로 적는다.
- 모든 명령(하위 명령 포함)에 `-help` 를 제공한다.

[입력 방식 — 명세 4-①]
- 기본은 대화형: `add` 는 인자 없이 실행하면 날짜/유형/카테고리/금액/메모/태그를 순서대로 묻는다.
- search / list / summary / export / import / delete 는 옵션 인자 방식.
- update 는 "안 A: 옵션 기반" 으로 고정 (update -id <id> [-date ...] [-amount ...] ...).

[명령 요약]
  add / list / search / summary / budget / category / update / delete / import / export  … 기본 10개
  backup [create|list|restore]      … 보너스(백업)
  recurring add|list|apply|remove   … 보너스(반복 내역)
  (모든 목록 출력은 보너스 '테이블 정렬' 적용)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from . import prompt
from .decorators import handle_errors, log_action, timed
from .errors import LedgerError
from .formatters import Align, fmt_money, render_table
from .models import TX_TYPE_LABEL, Transaction
from .services import SEED_CATEGORIES, LedgerApp

# 기본 데이터 위치: 프로젝트 루트/data, 백업: 프로젝트 루트/backups
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
LOG_PATH = DEFAULT_DATA_DIR / "ledger.log"

DEFAULT_LIST_LIMIT = 20   # 명세 5: -limit 기본값 제공
DEFAULT_TOP = 5           # 명세 8: 카테고리별 지출 TOP N 기본값

# 거래 목록 표의 열 정의 (list / search / recurring apply 가 공유)
TX_HEADERS = ("ID", "날짜", "유형", "카테고리", "금액", "메모", "태그")
TX_ALIGNS: tuple[Align, ...] = ("right", "left", "left", "left", "right", "left", "left")


# ---------------------------------------------------------------------------
# argparse 보조: 한국어 오류 + -help + 단일/이중 대시 동시 등록
# ---------------------------------------------------------------------------

class FriendlyParser(argparse.ArgumentParser):
    """argparse 기본 오류(영문, exit 2)를 한국어 메시지 + exit 1 로 바꾸고, -help 를 제공한다."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("add_help", False)          # 기본 -h/--help 대신 아래에서 직접 등록
        super().__init__(*args, **kwargs)
        self.add_argument("-h", "-help", "--help", action="help", help="이 사용법을 출력하고 종료")

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"[오류] 인자가 올바르지 않습니다: {message}", file=sys.stderr)
        print(f"[힌트] `{self.prog} -help` 로 사용법을 확인하세요.", file=sys.stderr)
        sys.exit(1)


def _opt(p: argparse.ArgumentParser, name: str, **kwargs: Any) -> None:
    """옵션을 `-name` 과 `--name` 두 표기로 등록한다. dest 는 name 의 '-' 를 '_' 로 바꾼 값."""
    kwargs.setdefault("dest", name.replace("-", "_"))
    p.add_argument(f"-{name}", f"--{name}", **kwargs)


# ---------------------------------------------------------------------------
# 출력 헬퍼
# ---------------------------------------------------------------------------

def _tx_row(tx: Transaction) -> tuple[object, ...]:
    """Transaction → 표 한 행. 금액은 int 로 넘겨 render_table 이 쉼표를 찍게 한다."""
    return (tx.id, tx.date, TX_TYPE_LABEL[tx.type], tx.category, tx.amount, tx.memo, ",".join(tx.tags))


def _print_transactions(txs: Iterable[Transaction], fmt: str = "table") -> int:
    items = list(txs)
    if not items:
        print("조회된 거래가 없습니다.")
        return 0
    if fmt == "plain":          # 스크립트 파이프용 한 줄 출력
        for t in items:
            print(_describe(t))
    else:
        print(render_table(TX_HEADERS, [_tx_row(t) for t in items], TX_ALIGNS))
    return len(items)


def _describe(tx: Transaction) -> str:
    s = f"#{tx.id} {tx.date} {TX_TYPE_LABEL[tx.type]} {tx.category} {fmt_money(tx.amount)}원 {tx.memo}"
    if tx.tags:
        s += f" [{', '.join(tx.tags)}]"
    return s.rstrip()


def _raw_row(raw: dict[Any, Any]) -> str:
    """깨진 CSV 행의 원본을 한 줄 문자열로. 초과 컬럼(None 키의 리스트)도 평탄화한다."""
    parts: list[str] = []
    for v in raw.values():
        if isinstance(v, list):
            parts.extend(str(x) for x in v)
        elif v is not None:
            parts.append(str(v))
    return ",".join(parts)


# ---------------------------------------------------------------------------
# 명령 핸들러 — 각 함수는 (app, args) 를 받고 0 또는 종료 코드를 반환
# 데코레이터 순서: log_action(바깥: 실패 코드까지 기록) → handle_errors(예외→코드) → timed(안쪽: 순수 시간)
# ---------------------------------------------------------------------------

@log_action(LOG_PATH)
@handle_errors
@timed
def cmd_add(app: LedgerApp, a: argparse.Namespace) -> int:
    """대화형 입력 (명세 4-④). 카테고리가 없으면 등록을 제안한다."""
    values = prompt.ask_transaction(app.categories.names(), register=lambda n: app.categories.add(n))
    tx = app.transactions.add(**values)  # type: ignore[arg-type]
    print(f"저장 완료: 거래 id={tx.id}  ({_describe(tx)})")
    return 0


@log_action(LOG_PATH)
@handle_errors
@timed
def cmd_list(app: LedgerApp, a: argparse.Namespace) -> int:
    stream = app.transactions.iter_filtered(month=a.month, type=a.type, category=a.category)
    rows = app.transactions.newest_first(stream, a.limit)
    n = _print_transactions(rows, a.format)
    if n:
        print(f"(최신순 {n}건 표시" + (f", -limit {a.limit}" if a.limit else ", 전체") + ")")
    return 0


@log_action(LOG_PATH)
@handle_errors
@timed
def cmd_search(app: LedgerApp, a: argparse.Namespace) -> int:
    if not any([a.q, a.tag, a.date_from, a.date_to, a.category, a.type]):
        print("[오류] 검색 조건을 하나 이상 지정하세요.", file=sys.stderr)
        print("[힌트] 예) search -q 커피  /  search -from 2026-10-01 -to 2026-10-31 -category 식비", file=sys.stderr)
        return 1
    stream = app.transactions.iter_filtered(
        type=a.type, category=a.category, keyword=a.q, tag=a.tag,
        date_from=a.date_from, date_to=a.date_to,
    )
    rows = app.transactions.newest_first(stream, a.limit)
    n = _print_transactions(rows, a.format)
    if n:
        print(f"({n}건 일치, 최신순)")
    return 0


@log_action(LOG_PATH)
@handle_errors
@timed
def cmd_summary(app: LedgerApp, a: argparse.Namespace) -> int:
    s = app.transactions.summarize(a.month, app.budgets.get(a.month))
    print(f"== {a.month} 월별 요약 ==")
    if s.count == 0:
        print(f"{a.month}: 데이터 없음 (거래가 한 건도 없습니다)")
        if s.budget:
            print(f"설정된 예산: {fmt_money(s.budget.amount)}원 (사용 0%)")
        return 0
    print(f"거래 건수 : {s.count}건")
    print(f"총 수입   : {fmt_money(s.income):>14}원")
    print(f"총 지출   : {fmt_money(s.expense):>14}원")
    print(f"잔액      : {fmt_money(s.balance, signed=True):>14}원")

    if s.by_category:
        print(f"\n[카테고리별 지출 TOP {a.top}]")
        rows = [(i, c, amt, f"{amt / s.expense * 100:5.1f}%")
                for i, (c, amt) in enumerate(s.top_categories(a.top), 1)]
        print(render_table(("순위", "카테고리", "지출", "비중"), rows, ("right", "left", "right", "right")))

    if s.budget:
        print("\n[예산 사용 현황]")
        print(f"월 예산   : {fmt_money(s.budget.amount):>14}원")
        print(f"사용률    : {s.budget_ratio * 100:13.1f}%  ({s.budget_status})")
        print(f"잔여 예산 : {fmt_money(s.budget.amount - s.expense, signed=True):>14}원")
        if s.budget_status == "초과":
            print(f"※ 경고: 예산을 {fmt_money(s.expense - s.budget.amount)}원 초과했습니다!")
        elif s.budget_status == "주의":
            print("※ 주의: 예산의 80% 이상을 사용했습니다.")
    else:
        print(f"\n(이 달의 예산이 없습니다. `budget set -month {a.month} -amount <금액>` 으로 설정할 수 있습니다)")
    return 0


@log_action(LOG_PATH)
@handle_errors
@timed
def cmd_budget(app: LedgerApp, a: argparse.Namespace) -> int:
    if a.sub == "set":
        b = app.budgets.set(a.month, a.amount)
        print(f"예산 저장 완료: {b.month} 월 예산 {fmt_money(b.amount)}원")
    else:  # list
        rows = [(b.month, b.amount) for b in app.budgets.list()]
        print(render_table(("월", "예산"), rows, ("left", "right")))
    return 0


@log_action(LOG_PATH)
@handle_errors
@timed
def cmd_category(app: LedgerApp, a: argparse.Namespace) -> int:
    if a.sub == "add":
        c = app.categories.add(a.name)
        print(f"카테고리 추가됨: {c.name}")
    elif a.sub == "list":
        rows = [(c.name, app.categories.usage_count(c.name), c.created_at) for c in app.categories.list()]
        print(render_table(("카테고리", "거래수", "생성일"), rows, ("left", "right", "left")))
    elif a.sub == "remove":
        info = app.categories.remove(a.name, a.reassign)
        msg = f"카테고리 삭제됨: {a.name}"
        if a.reassign:
            msg += f" (거래 {info['transactions']}건·반복규칙 {info['recurring']}건 → '{a.reassign}' 로 이동)"
        print(msg)
    return 0


@log_action(LOG_PATH)
@handle_errors
@timed
def cmd_update(app: LedgerApp, a: argparse.Namespace) -> int:
    """안 A(옵션 기반) 로 고정: update -id <id> [-date] [-type] [-category] [-amount] [-memo] [-tags]"""
    before = app.transactions.get(a.id)
    after = app.transactions.update(
        a.id, date=a.date, type=a.type, category=a.category, amount=a.amount, memo=a.memo, tags=a.tags,
    )
    print(f"수정 완료 (id={a.id})")
    print(f"  수정 전: {_describe(before)}")
    print(f"  수정 후: {_describe(after)}")
    return 0


@log_action(LOG_PATH)
@handle_errors
@timed
def cmd_delete(app: LedgerApp, a: argparse.Namespace) -> int:
    tx = app.transactions.delete(a.id)
    print(f"삭제 완료: {_describe(tx)}")
    return 0


@log_action(LOG_PATH)
@handle_errors
@timed
def cmd_import(app: LedgerApp, a: argparse.Namespace) -> int:
    r = app.transactions.import_csv(Path(a.src), a.mode, a.create_categories)
    print(f"가져오기 결과: 총 {r.total}행 중 성공 {len(r.valid)}건, 실패 {len(r.errors)}건 (mode={a.mode})")
    if r.errors:
        print("\n[실패한 행 — 수정 후 다시 가져오면 됩니다]")
        print(render_table(("줄", "원인", "원본"),
                           [(e.line_no, e.reason, _raw_row(e.raw)) for e in r.errors],
                           ("right", "left", "left"), max_col_width=90))
        return 1 if not r.valid else 0   # 하나도 못 들어갔으면 실패로 간주
    return 0


@log_action(LOG_PATH)
@handle_errors
@timed
def cmd_export(app: LedgerApp, a: argparse.Namespace) -> int:
    n = app.transactions.export(Path(a.out), a.month, a.date_from, a.date_to)
    cond = f"-month {a.month}" if a.month else f"-from {a.date_from or '…'} -to {a.date_to or '…'}"
    print(f"내보내기 완료: {n}건 → {a.out}  (조건: {cond}, UTF-8, 헤더: {','.join(Transaction.CSV_COLUMNS)})")
    return 0


@log_action(LOG_PATH)
@handle_errors
@timed
def cmd_backup(app: LedgerApp, a: argparse.Namespace) -> int:
    sub = a.sub or "create"   # `backup` 만 입력하면 생성 (명세 보너스 1)
    if sub == "create":
        p = app.backup.create(a.label)
        print(f"백업 생성됨: {p}  ({sum(1 for _ in p.iterdir())}개 파일)")
    elif sub == "list":
        print(render_table(("백업명", "생성시각", "파일수"), app.backup.list(), ("left", "left", "right"), max_col_width=60))
    elif sub == "restore":
        p = app.backup.restore(a.name)
        print(f"복원 완료: {p.name} → {app.data_dir}  (복원 직전 상태는 '*-pre-restore' 백업으로 보관)")
    return 0


@log_action(LOG_PATH)
@handle_errors
@timed
def cmd_recurring(app: LedgerApp, a: argparse.Namespace) -> int:
    if a.sub == "add":
        r = app.recurring.add(a.day, a.type, a.category, a.amount, a.memo or "", a.tags)
        print(f"반복 규칙 추가됨: #{r.id} 매월 {r.day}일 {TX_TYPE_LABEL[r.type]} {r.category} {fmt_money(r.amount)}원 {r.memo}".rstrip())
    elif a.sub == "list":
        rows = [(r.id, f"매월 {r.day}일", TX_TYPE_LABEL[r.type], r.category, r.amount, r.memo,
                 ", ".join(r.applied_months[-3:]) or "-") for r in app.recurring.list()]
        print(render_table(("ID", "주기", "유형", "카테고리", "금액", "메모", "최근 적용"), rows,
                           ("right", "left", "left", "left", "right", "left", "left")))
    elif a.sub == "apply":
        created = app.recurring.apply(a.month)
        if created:
            print(f"{a.month} 반복 거래 {len(created)}건 생성:")
            _print_transactions(created)
        else:
            print(f"{a.month} 에 새로 생성할 반복 거래가 없습니다 (이미 적용됐거나 규칙 없음).")
    elif a.sub == "remove":
        r = app.recurring.remove(a.id)
        print(f"반복 규칙 삭제됨: #{r.id} {r.category} {fmt_money(r.amount)}원")
    return 0


# ---------------------------------------------------------------------------
# 파서 구성
# ---------------------------------------------------------------------------

def build_parser() -> FriendlyParser:
    p = FriendlyParser(
        prog="python -m budget_app",
        description="JSONL 기반 개인 가계부 CLI (옵션은 -name / --name 모두 허용)",
        epilog="예) python -m budget_app add   ← 대화형 입력 / python -m budget_app list -limit 5",
    )
    _opt(p, "data-dir", default=str(DEFAULT_DATA_DIR), help="저장 디렉터리 (기본: ./data)")
    sub = p.add_subparsers(dest="command", metavar="<command>", parser_class=FriendlyParser)
    sub.required = True

    def fmt_opts(sp: argparse.ArgumentParser, limit_default: int) -> None:
        _opt(sp, "limit", type=int, default=limit_default, help=f"최대 표시 건수 (기본 {limit_default}, 0=전체)")
        _opt(sp, "format", choices=("table", "plain"), default="table", help="출력 형식")

    s = sub.add_parser("add", help="거래 추가 (대화형 입력)")
    s.set_defaults(func=cmd_add)

    s = sub.add_parser("list", help="거래 목록 (최신순, 스트리밍)")
    fmt_opts(s, DEFAULT_LIST_LIMIT)
    _opt(s, "month", help="YYYY-MM 로 필터")
    _opt(s, "type", help="income | expense")
    _opt(s, "category")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("search", help="거래 검색 (최신순)")
    _opt(s, "from", dest="date_from", help="시작일 YYYY-MM-DD")
    _opt(s, "to", dest="date_to", help="종료일 YYYY-MM-DD")
    _opt(s, "category")
    _opt(s, "type", help="income | expense")
    _opt(s, "q", help="메모 키워드 (부분 일치, 대소문자 무시)")
    _opt(s, "tag", help="태그 (정확히 일치)")
    fmt_opts(s, 0)
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("summary", help="월별 요약 + 카테고리 TOP N + 예산 사용률")
    _opt(s, "month", required=True, help="YYYY-MM")
    _opt(s, "top", type=int, default=DEFAULT_TOP, help=f"카테고리별 지출 TOP N (기본 {DEFAULT_TOP})")
    s.set_defaults(func=cmd_summary)

    s = sub.add_parser("budget", help="월 예산 설정/조회")
    ss = s.add_subparsers(dest="sub", metavar="{set,list}", parser_class=FriendlyParser)
    ss.required = True
    x = ss.add_parser("set", help="월 예산 저장(덮어쓰기)")
    _opt(x, "month", required=True, help="YYYY-MM")
    _opt(x, "amount", required=True, help="예산 금액(원)")
    ss.add_parser("list", help="예산 목록")
    s.set_defaults(func=cmd_budget)

    s = sub.add_parser("category", help="카테고리 관리")
    ss = s.add_subparsers(dest="sub", metavar="{add,list,remove}", parser_class=FriendlyParser)
    ss.required = True
    x = ss.add_parser("add"); x.add_argument("name", help="카테고리 이름")
    ss.add_parser("list")
    x = ss.add_parser("remove"); x.add_argument("name")
    _opt(x, "reassign", help="사용 중인 거래를 옮길 대체 카테고리 (없으면 생성)")
    s.set_defaults(func=cmd_category)

    s = sub.add_parser("update", help="거래 수정 (옵션 기반: -id 필수, 바꿀 항목만 지정)")
    _opt(s, "id", type=int, required=True)
    _opt(s, "date"); _opt(s, "type"); _opt(s, "category"); _opt(s, "amount")
    _opt(s, "memo"); _opt(s, "tags", help="쉼표 구분. 빈 문자열('')이면 태그 제거")
    s.set_defaults(func=cmd_update)

    s = sub.add_parser("delete", help="거래 삭제")
    _opt(s, "id", type=int, required=True)
    s.set_defaults(func=cmd_delete)

    s = sub.add_parser("import", help="CSV 가져오기")
    _opt(s, "from", dest="src", required=True, help="입력 CSV 경로")
    _opt(s, "mode", choices=("partial", "strict"), default="partial",
         help="partial: 정상 행만 저장(기본) / strict: 오류 있으면 전체 중단")
    _opt(s, "create-categories", action="store_true", help="미등록 카테고리 자동 등록")
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("export", help="CSV 내보내기 (-month 또는 -from/-to 필수)")
    _opt(s, "out", required=True, help="출력 CSV 경로")
    _opt(s, "month", help="YYYY-MM")
    _opt(s, "from", dest="date_from", help="시작일 YYYY-MM-DD")
    _opt(s, "to", dest="date_to", help="종료일 YYYY-MM-DD")
    s.set_defaults(func=cmd_export)

    s = sub.add_parser("backup", help="[보너스] 백업 (하위 명령 없으면 create)")
    ss = s.add_subparsers(dest="sub", metavar="[create|list|restore]", parser_class=FriendlyParser)
    x = ss.add_parser("create"); _opt(x, "label", help="백업 이름 꼬리표")
    ss.add_parser("list")
    x = ss.add_parser("restore"); _opt(x, "name", required=True, help="backup list 에 나온 백업명")
    s.set_defaults(func=cmd_backup, label=None)

    s = sub.add_parser("recurring", help="[보너스] 반복 내역")
    ss = s.add_subparsers(dest="sub", metavar="{add,list,apply,remove}", parser_class=FriendlyParser)
    ss.required = True
    x = ss.add_parser("add")
    _opt(x, "day", type=int, required=True, help="매월 며칠(1~31)")
    _opt(x, "type", required=True); _opt(x, "category", required=True)
    _opt(x, "amount", required=True); _opt(x, "memo", default=""); _opt(x, "tags")
    ss.add_parser("list")
    x = ss.add_parser("apply"); _opt(x, "month", required=True, help="YYYY-MM")
    x = ss.add_parser("remove"); _opt(x, "id", type=int, required=True)
    s.set_defaults(func=cmd_recurring)

    return p


def main(argv: Sequence[str] | None = None) -> int:
    """엔트리포인트. 종료 코드를 반환한다 (__main__.py 가 sys.exit 에 넘김)."""
    args = build_parser().parse_args(argv)
    try:
        app = LedgerApp(Path(args.data_dir))
    except LedgerError as e:  # 저장소 초기화 실패(권한 등)도 스택트레이스 없이
        print(f"[오류] 저장소를 열 수 없습니다: {e.message}", file=sys.stderr)
        if e.hint:
            print(f"[힌트] {e.hint}", file=sys.stderr)
        return e.exit_code
    if app.initialized:   # 명세 3-④: 초기 실행 안내
        print(f"[안내] 저장 폴더를 초기화했습니다: {app.data_dir}  "
              f"(기본 카테고리 자동 생성: {', '.join(SEED_CATEGORIES)})", file=sys.stderr)
    func: Callable[[LedgerApp, argparse.Namespace], int] = args.func
    return func(app, args)
