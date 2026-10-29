"""
prompt.py — 대화형 입력(input) 헬퍼

[이 모듈의 책임]
- 명세 4-①/4-④: "add 는 input() 으로 날짜/타입/카테고리/금액 등을 순차 입력" 을 구현한다.
- 입력값 검증은 models.py 의 validate_* 함수를 그대로 재사용한다
  → 옵션 인자로 받든 대화형으로 받든 같은 규칙이 적용되고, 검증 코드가 중복되지 않는다.
- 잘못된 값이면 [오류]/[힌트] 를 보여 주고 그 항목만 다시 묻는다 (명세 "재입력 요구").
- Enter 만 치면 기본값(오늘 날짜 등)을 쓰거나, 선택 항목(메모·태그)은 비워 둔다.

[분리한 이유]
- cli.py 는 "명령 해석 + 결과 출력", prompt.py 는 "사용자에게 묻기" 로 역할이 다르다.
- 테스트에서 builtins.input 을 가짜 함수로 바꿔 끼우면 사람이 없이도 대화형 흐름을 검증할 수 있다.
"""

from __future__ import annotations

import sys
from datetime import date
from typing import Callable, TypeVar

from .errors import LedgerError, ValidationError
from .models import TX_TYPE_LABEL, parse_tags, validate_amount, validate_date, validate_tx_type

T = TypeVar("T")


def _read(prompt: str) -> str:
    """input() 래퍼. 파이프 등으로 입력이 끊기면(EOF) 스택트레이스 대신 LedgerError 로 바꾼다."""
    try:
        return input(prompt)
    except EOFError:
        raise LedgerError(
            "대화형 입력이 중단되었습니다 (입력 없음).",
            hint="터미널에서 직접 실행해 값을 입력하거나, 옵션 인자를 지원하는 명령(search/list 등)을 사용하세요.",
        ) from None


def ask(
    label: str,
    validator: Callable[[str], T],
    default: str | None = None,
    optional: bool = False,
    max_retries: int = 5,
) -> T | None:
    """한 항목을 올바른 값이 들어올 때까지 묻는다.

    Args:
        label:      안내 문구 (예: '날짜')
        validator:  문자열 → 검증·변환 함수. 실패 시 ValidationError 를 던져야 한다.
        default:    Enter 만 쳤을 때 사용할 값 (None 이면 기본값 없음)
        optional:   True 면 Enter 만 쳤을 때 None 을 반환 (메모·태그 같은 선택 항목)
        max_retries: 이 횟수만큼 틀리면 포기하고 오류 종료 (무한 루프 방지)
    """
    suffix = f" [기본: {default}]" if default is not None else (" [Enter = 생략]" if optional else "")
    for _ in range(max_retries):
        raw = _read(f"{label}{suffix}: ").strip()
        if not raw:
            if default is not None:
                raw = default
            elif optional:
                return None
            else:
                print("[오류] 값을 입력해야 합니다.", file=sys.stderr)
                continue
        try:
            return validator(raw)
        except ValidationError as e:
            print(f"[오류] {e.message}", file=sys.stderr)
            if e.hint:
                print(f"[힌트] {e.hint}", file=sys.stderr)
    raise ValidationError(f"'{label}' 입력을 {max_retries}회 실패해 중단합니다.", hint="값 형식을 확인한 뒤 다시 실행하세요.")


def ask_yes_no(question: str, default: bool = False) -> bool:
    """y/n 질문. Enter 는 default."""
    raw = _read(f"{question} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes", "ㅇ", "예", "네")


def ask_category(names: list[str], register: Callable[[str], object] | None = None) -> str:
    """카테고리를 번호 또는 이름으로 고른다. 없는 이름이면 등록을 제안한다 (명세 4-④)."""
    print("카테고리 목록: " + "  ".join(f"{i}) {n}" for i, n in enumerate(names, 1)))
    for _ in range(5):
        raw = _read("카테고리 (번호 또는 이름): ").strip()
        if not raw:
            print("[오류] 카테고리를 선택해야 합니다.", file=sys.stderr)
            continue
        if raw.isdigit() and 1 <= int(raw) <= len(names):
            return names[int(raw) - 1]
        if raw in names:
            return raw
        print(f"[오류] 존재하지 않는 카테고리입니다: {raw}", file=sys.stderr)
        if register is not None and ask_yes_no(f"'{raw}' 을(를) 새 카테고리로 등록할까요?"):
            try:
                register(raw)
                names.append(raw)
                return raw
            except ValidationError as e:
                print(f"[오류] {e.message}", file=sys.stderr)
        else:
            print("[힌트] 목록의 번호를 고르거나 `category add <이름>` 으로 먼저 등록하세요.", file=sys.stderr)
    raise ValidationError("카테고리 입력을 5회 실패해 중단합니다.")


def ask_transaction(categories: list[str], register: Callable[[str], object] | None = None) -> dict[str, object]:
    """add 명령의 대화형 흐름. 검증을 통과한 값들을 dict 로 돌려준다."""
    print("── 거래 추가 (Ctrl+C 로 취소) ──")
    date_ = ask("날짜 (YYYY-MM-DD)", validate_date, default=date.today().isoformat())
    type_ = ask(f"유형 (1={TX_TYPE_LABEL['income']} income / 2={TX_TYPE_LABEL['expense']} expense)", validate_tx_type)
    category = ask_category(list(categories), register)
    amount = ask("금액 (원, 정수)", validate_amount)
    memo = ask("메모", lambda s: s.strip(), optional=True) or ""
    tags = ask("태그 (쉼표로 구분)", parse_tags, optional=True) or []
    return {"date": date_, "type": type_, "category": category, "amount": amount, "memo": memo, "tags": tags}
