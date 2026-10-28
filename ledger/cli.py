"""
cli.py — 명령줄 인터페이스(인자 파싱 + 결과 출력)

[이 모듈의 책임]
- argparse 로 명령/옵션을 해석해 services 계층의 메서드를 호출하고,
  돌아온 값을 formatters 로 예쁘게 출력한다.
- 업무 규칙은 전혀 담지 않는다 (예산 초과 판정, 중복 검사 등은 services 담당).
- 모든 핸들러는 @handle_errors 로 감싸져 있어 예외 → 메시지/힌트/종료코드 로 변환된다.

[명령 요약]
  add / list / search / summary / export / import / update / delete   … 기본 8개
  category add|list|remove                                            … 기본 9번째
  budget set|list                                                     … 기본 10번째
  backup create|list|restore                                          … 보너스(백업)
  recurring add|list|apply|remove                                     … 보너스(반복 내역)
  (모든 목록 출력은 보너스 '테이블 정렬' 을 적용)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Iterator, Sequence

from .decorators import handle_errors, log_action, timed
from .errors import LedgerError
from .formatters import fmt_money, render_table
from .models import TX_TYPE_LABEL, Transaction
from .services import LedgerApp

# 기본 데이터 위치: 프로젝트 루트/data, 백업: 프로젝트 루트/backups
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
LOG_PATH = DEFAULT_DATA_DIR / "ledger.log"

# 거래 목록 표의 열 정의 (list / search / recurring apply 가 공유)
TX_HEADERS = ("ID", "날짜", "유형", "카테고리", "금액", "메모")
TX_ALIGNS = ("right", "left", "left", "left", "right", "left")


class FriendlyParser(argparse.ArgumentParser):
    """argparse 기본 오류(영문, exit 2)를 한국어 메시지 + exit 1 로 바꾼다."""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"[오류] 인자가 올바르지 않습니다: {message}", file=sys.stderr)
        print(f"[힌트] `{self.prog} -h` 로 사용법을 확인하세요.", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# 출력 헬퍼
# ---------------------------------------------------------------------------

def _tx_row(tx: Transaction) -> tuple[object, ...]:
    """Transaction → 표 한 행. 금액은 int 로 넘겨 render_table 이 쉼표를 찍게 한다."""
    return (tx.id, tx.date, TX_TYPE_LABEL[tx.type], tx.category, tx.amount, tx.memo)


def _print_transactions(txs: Iterator[Transaction], limit: int | None, fmt: str, sort: str | None = None) -> int:
    """제너레이터를 소비하며 출력.

    - sort 가 없으면(기본) 파일에 기록된 순서대로 흘려보내며, limit 만큼만 꺼내면
      나머지 파일은 읽지 않는다 → 지연 평가의 이점.
    - sort 가 있으면 정렬을 위해 어쩔 수 없이 전체를 메모리에 올린다
      (정렬은 모든 원소를 봐야 하므로). 이 트레이드오프를 옵션으로 사용자에게 맡긴다.

    Returns: 출력한 건수
    """
    rows: list[tuple[object, ...]] = []
    if sort:
        key = {"date": lambda t: (t.date, t.id), "amount": lambda t: (-t.amount, t.id)}[sort]
        txs = iter(sorted(txs, key=key))   # 여기서만 전체 materialize
    for tx in txs:
        if limit is not None and len(rows) >= limit:
            break
        rows.append(_tx_row(tx))
    if not rows:
        print("조회된 거래가 없습니다.")
        return 0
    if fmt == "plain":
        for r in rows:
            print(f"#{r[0]} {r[1]} {r[2]} {r[3]} {fmt_money(int(r[4]))} {r[5]}")
    else:
        print(render_table(TX_HEADERS, rows, TX_ALIGNS))
    return len(rows)


def _raw_row(raw: dict[object, object]) -> str:
    """깨진 CSV 행의 원본을 한 줄 문자열로. 초과 컬럼(None 키의 리스트)도 평탄화한다."""
    parts: list[str] = []
    for v in raw.values():
        if isinstance(v, list):
            parts.extend(str(x) for x in v)
        elif v is not None:
            parts.append(str(v))
    return ",".join(parts)


def _describe(tx: Transaction) -> str:
    return f"#{tx.id} {tx.date} {TX_TYPE_LABEL[tx.type]} {tx.category} {fmt_money(tx.amount)}원 {tx.memo}".rstrip()


# ---------------------------------------------------------------------------
# 명령 핸들러 — 각 함수는 (app, args) 를 받고 0 또는 종료 코드를 반환
# ---------------------------------------------------------------------------

@log_action(LOG_PATH)   # 가장 바깥: 성공/실패 종료코드까지 기록
@handle_errors           # 예외 → 메시지/힌트/종료코드
@timed                   # 가장 안쪽: 순수 실행 시간만 측정
def cmd_add(app: LedgerApp, a: argparse.Namespace) -> int:
    tx = app.transactions.add(a.date, a.type, a.category, a.amount, a.memo or "")
    print(f"추가됨: {_describe(tx)}")
    return 0


@log_action(LOG_PATH)   # 가장 바깥: 성공/실패 종료코드까지 기록
@handle_errors           # 예외 → 메시지/힌트/종료코드
@timed                   # 가장 안쪽: 순수 실행 시간만 측정
def cmd_list(app: LedgerApp, a: argparse.Namespace) -> int:
    gen = app.transactions.iter_filtered(month=a.month, type=a.type, category=a.category)
    n = _print_transactions(gen, a.limit, a.format, a.sort)
    if n:
        print(f"({n}건 표시)")
    return 0


@log_action(LOG_PATH)   # 가장 바깥: 성공/실패 종료코드까지 기록
@handle_errors           # 예외 → 메시지/힌트/종료코드
@timed                   # 가장 안쪽: 순수 실행 시간만 측정
def cmd_search(app: LedgerApp, a: argparse.Namespace) -> int:
    if not any([a.keyword, a.date_from, a.date_to, a.min, a.max, a.category, a.type]):
        print("[오류] 검색 조건을 하나 이상 지정하세요.", file=sys.stderr)
        print("[힌트] 예) search --keyword 커피  /  search --from 2026-10-01 --to 2026-10-31 --min 10000", file=sys.stderr)
        return 1
    gen = app.transactions.iter_filtered(
        type=a.type, category=a.category, keyword=a.keyword,
        date_from=a.date_from, date_to=a.date_to, min_amount=a.min, max_amount=a.max,
    )
    n = _print_transactions(gen, a.limit, a.format, a.sort)
    if n:
        print(f"({n}건 일치)")
    return 0


@log_action(LOG_PATH)   # 가장 바깥: 성공/실패 종료코드까지 기록
@handle_errors           # 예외 → 메시지/힌트/종료코드
@timed                   # 가장 안쪽: 순수 실행 시간만 측정
def cmd_summary(app: LedgerApp, a: argparse.Namespace) -> int:
    s = app.transactions.summarize(a.month, app.budgets.list(a.month))
    title = f"{a.month} 요약" if a.month else "전체 기간 요약"
    print(f"== {title} ({s.count}건) ==")
    print(f"수입  : {fmt_money(s.income):>14}원")
    print(f"지출  : {fmt_money(s.expense):>14}원")
    print(f"순액  : {fmt_money(s.net, signed=True):>14}원")

    if s.by_category:
        print("\n[카테고리별 지출]")
        rows = sorted(s.by_category.items(), key=lambda kv: kv[1], reverse=True)
        pct_rows = [(c, amt, f"{amt / s.expense * 100:5.1f}%") for c, amt in rows]
        print(render_table(("카테고리", "지출", "비중"), pct_rows, ("left", "right", "right")))

    if s.budget_rows:
        print("\n[예산 사용 현황]")
        rows2 = [
            (r.category, r.limit, r.used, r.limit - r.used, f"{r.ratio * 100:5.1f}%", r.status)
            for r in s.budget_rows
        ]
        print(render_table(("카테고리", "예산", "사용", "잔여", "사용률", "상태"), rows2,
                           ("left", "right", "right", "right", "right", "left")))
        over = [r.category for r in s.budget_rows if r.status == "초과"]
        if over:
            print(f"※ 예산 초과: {', '.join(over)}")
    elif a.month:
        print(f"\n(이 달에 설정된 예산이 없습니다. `budget set --month {a.month} --category <이름> --amount <금액>`)")
    return 0


@log_action(LOG_PATH)   # 가장 바깥: 성공/실패 종료코드까지 기록
@handle_errors           # 예외 → 메시지/힌트/종료코드
@timed                   # 가장 안쪽: 순수 실행 시간만 측정
def cmd_export(app: LedgerApp, a: argparse.Namespace) -> int:
    n = app.transactions.export(Path(a.out), a.month)
    print(f"내보내기 완료: {n}건 → {a.out} (UTF-8, 헤더: {','.join(Transaction.CSV_COLUMNS)})")
    return 0


@log_action(LOG_PATH)   # 가장 바깥: 성공/실패 종료코드까지 기록
@handle_errors           # 예외 → 메시지/힌트/종료코드
@timed                   # 가장 안쪽: 순수 실행 시간만 측정
def cmd_import(app: LedgerApp, a: argparse.Namespace) -> int:
    r = app.transactions.import_csv(Path(a.file), a.mode, a.create_categories)
    print(f"가져오기 결과: 총 {r.total}행 중 성공 {len(r.valid)}건, 실패 {len(r.errors)}건 (mode={a.mode})")
    if r.errors:
        print("\n[실패한 행 — 수정 후 다시 가져오면 됩니다]")
        print(render_table(("줄", "원인", "원본"),
                           [(e.line_no, e.reason, _raw_row(e.raw)) for e in r.errors],
                           ("right", "left", "left"), max_col_width=90))
        return 1 if not r.valid else 0   # 하나도 못 들어갔으면 실패로 간주
    return 0


@log_action(LOG_PATH)   # 가장 바깥: 성공/실패 종료코드까지 기록
@handle_errors           # 예외 → 메시지/힌트/종료코드
@timed                   # 가장 안쪽: 순수 실행 시간만 측정
def cmd_update(app: LedgerApp, a: argparse.Namespace) -> int:
    before = app.transactions.get(a.id)
    after = app.transactions.update(
        a.id, date=a.date, type=a.type, category=a.category, amount=a.amount, memo=a.memo,
    )
    print(f"수정 전: {_describe(before)}")
    print(f"수정 후: {_describe(after)}")
    return 0


@log_action(LOG_PATH)   # 가장 바깥: 성공/실패 종료코드까지 기록
@handle_errors           # 예외 → 메시지/힌트/종료코드
@timed                   # 가장 안쪽: 순수 실행 시간만 측정
def cmd_delete(app: LedgerApp, a: argparse.Namespace) -> int:
    tx = app.transactions.delete(a.id)
    print(f"삭제됨: {_describe(tx)}")
    return 0


@log_action(LOG_PATH)   # 가장 바깥: 성공/실패 종료코드까지 기록
@handle_errors           # 예외 → 메시지/힌트/종료코드
@timed                   # 가장 안쪽: 순수 실행 시간만 측정
def cmd_category(app: LedgerApp, a: argparse.Namespace) -> int:
    if a.sub == "add":
        c = app.categories.add(a.name)
        print(f"카테고리 추가됨: {c.name}")
    elif a.sub == "list":
        cats = app.categories.list()
        rows = [(c.name, app.categories.usage_count(c.name), c.created_at) for c in cats]
        print(render_table(("카테고리", "거래수", "생성일"), rows, ("left", "right", "left")))
    elif a.sub == "remove":
        info = app.categories.remove(a.name, a.reassign)
        msg = f"카테고리 삭제됨: {a.name}"
        if a.reassign:
            msg += (f" (거래 {info['transactions']}건·반복규칙 {info['recurring']}건 → '{a.reassign}' 로 이동, "
                    f"예산 {info['budgets']}건 삭제)")
        print(msg)
    return 0


@log_action(LOG_PATH)   # 가장 바깥: 성공/실패 종료코드까지 기록
@handle_errors           # 예외 → 메시지/힌트/종료코드
@timed                   # 가장 안쪽: 순수 실행 시간만 측정
def cmd_budget(app: LedgerApp, a: argparse.Namespace) -> int:
    if a.sub == "set":
        b = app.budgets.set(a.month, a.category, a.amount)
        print(f"예산 설정됨: {b.month} {b.category} {fmt_money(b.amount)}원")
    elif a.sub == "list":
        rows = [(b.month, b.category, b.amount) for b in app.budgets.list(a.month)]
        print(render_table(("월", "카테고리", "예산"), rows, ("left", "left", "right")))
    return 0


@log_action(LOG_PATH)   # 가장 바깥: 성공/실패 종료코드까지 기록
@handle_errors           # 예외 → 메시지/힌트/종료코드
@timed                   # 가장 안쪽: 순수 실행 시간만 측정
def cmd_backup(app: LedgerApp, a: argparse.Namespace) -> int:
    if a.sub == "create":
        p = app.backup.create(a.label)
        print(f"백업 생성됨: {p.name} ({sum(1 for _ in p.iterdir())}개 파일)")
    elif a.sub == "list":
        print(render_table(("백업명", "생성시각", "파일수"), app.backup.list(), ("left", "left", "right"), max_col_width=60))
    elif a.sub == "restore":
        p = app.backup.restore(a.name)
        print(f"복원 완료: {p.name} → {app.data_dir}  (복원 직전 상태는 '*-pre-restore' 백업으로 보관)")
    return 0


@log_action(LOG_PATH)   # 가장 바깥: 성공/실패 종료코드까지 기록
@handle_errors           # 예외 → 메시지/힌트/종료코드
@timed                   # 가장 안쪽: 순수 실행 시간만 측정
def cmd_recurring(app: LedgerApp, a: argparse.Namespace) -> int:
    if a.sub == "add":
        r = app.recurring.add(a.day, a.type, a.category, a.amount, a.memo or "")
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
            print(render_table(TX_HEADERS, [_tx_row(t) for t in created], TX_ALIGNS))
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
        prog="python main.py",
        description="JSONL 기반 개인 가계부 CLI",
        epilog="예) python main.py add --date 2026-10-28 --type expense --category 식비 --amount 12000 --memo 점심",
    )
    p.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="저장 디렉터리 (기본: ./data)")
    sub = p.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    # 공통 옵션 묶음 (parents 로 재사용)
    fmt = argparse.ArgumentParser(add_help=False)
    fmt.add_argument("--format", choices=("table", "plain"), default="table", help="출력 형식")
    fmt.add_argument("--limit", type=int, help="최대 표시 건수")
    fmt.add_argument("--sort", choices=("date", "amount"), help="정렬 기준(지정 시 전체를 메모리에 올림)")

    s = sub.add_parser("add", help="거래 추가")
    s.add_argument("--date", required=True, help="YYYY-MM-DD")
    s.add_argument("--type", required=True, help="income | expense")
    s.add_argument("--category", required=True)
    s.add_argument("--amount", required=True, help="정수(원). 쉼표 허용")
    s.add_argument("--memo", default="")
    s.set_defaults(func=cmd_add)

    s = sub.add_parser("list", help="거래 목록", parents=[fmt])
    s.add_argument("--month", help="YYYY-MM")
    s.add_argument("--type", help="income | expense")
    s.add_argument("--category")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("search", help="거래 검색", parents=[fmt])
    s.add_argument("--keyword", help="메모/카테고리 부분 일치(대소문자 무시)")
    s.add_argument("--from", dest="date_from", help="시작일 YYYY-MM-DD")
    s.add_argument("--to", dest="date_to", help="종료일 YYYY-MM-DD")
    s.add_argument("--min", type=int, help="최소 금액")
    s.add_argument("--max", type=int, help="최대 금액")
    s.add_argument("--category")
    s.add_argument("--type", help="income | expense")
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("summary", help="월별/전체 요약 + 예산 사용률")
    s.add_argument("--month", help="YYYY-MM (생략 시 전체)")
    s.set_defaults(func=cmd_summary)

    s = sub.add_parser("export", help="CSV 내보내기")
    s.add_argument("--out", required=True, help="출력 CSV 경로")
    s.add_argument("--month", help="특정 월만 내보내기")
    s.set_defaults(func=cmd_export)

    s = sub.add_parser("import", help="CSV 가져오기")
    s.add_argument("--file", required=True, help="입력 CSV 경로")
    s.add_argument("--mode", choices=("partial", "strict"), default="partial",
                   help="partial: 정상 행만 저장(기본) / strict: 오류 있으면 전체 중단")
    s.add_argument("--create-categories", action="store_true", help="미등록 카테고리 자동 등록")
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("update", help="거래 수정")
    s.add_argument("id", type=int)
    s.add_argument("--date")
    s.add_argument("--type")
    s.add_argument("--category")
    s.add_argument("--amount")
    s.add_argument("--memo")
    s.set_defaults(func=cmd_update)

    s = sub.add_parser("delete", help="거래 삭제")
    s.add_argument("id", type=int)
    s.set_defaults(func=cmd_delete)

    s = sub.add_parser("category", help="카테고리 관리")
    ss = s.add_subparsers(dest="sub", metavar="{add,list,remove}")
    ss.required = True
    x = ss.add_parser("add"); x.add_argument("name")
    ss.add_parser("list")
    x = ss.add_parser("remove"); x.add_argument("name")
    x.add_argument("--reassign", help="사용 중인 거래를 옮길 카테고리(없으면 생성)")
    s.set_defaults(func=cmd_category)

    s = sub.add_parser("budget", help="예산 관리")
    ss = s.add_subparsers(dest="sub", metavar="{set,list}")
    ss.required = True
    x = ss.add_parser("set")
    x.add_argument("--month", required=True); x.add_argument("--category", required=True)
    x.add_argument("--amount", required=True)
    x = ss.add_parser("list"); x.add_argument("--month")
    s.set_defaults(func=cmd_budget)

    s = sub.add_parser("backup", help="[보너스] 백업/복원")
    ss = s.add_subparsers(dest="sub", metavar="{create,list,restore}")
    ss.required = True
    x = ss.add_parser("create"); x.add_argument("--label", help="백업 이름 꼬리표")
    ss.add_parser("list")
    x = ss.add_parser("restore"); x.add_argument("name")
    s.set_defaults(func=cmd_backup)

    s = sub.add_parser("recurring", help="[보너스] 반복 내역")
    ss = s.add_subparsers(dest="sub", metavar="{add,list,apply,remove}")
    ss.required = True
    x = ss.add_parser("add")
    x.add_argument("--day", type=int, required=True, help="매월 며칠(1~31)")
    x.add_argument("--type", required=True); x.add_argument("--category", required=True)
    x.add_argument("--amount", required=True); x.add_argument("--memo", default="")
    ss.add_parser("list")
    x = ss.add_parser("apply"); x.add_argument("--month", required=True, help="YYYY-MM")
    x = ss.add_parser("remove"); x.add_argument("id", type=int)
    s.set_defaults(func=cmd_recurring)

    return p


def main(argv: Sequence[str] | None = None) -> int:
    """엔트리포인트. 종료 코드를 반환한다 (main.py 가 sys.exit 에 넘김)."""
    args = build_parser().parse_args(argv)
    try:
        app = LedgerApp(Path(args.data_dir))
    except LedgerError as e:  # 저장소 초기화 실패(권한 등)도 스택트레이스 없이
        print(f"[오류] 저장소를 열 수 없습니다: {e.message}", file=sys.stderr)
        if e.hint:
            print(f"[힌트] {e.hint}", file=sys.stderr)
        return e.exit_code
    func: Callable[[LedgerApp, argparse.Namespace], int] = args.func
    return func(app, args)
