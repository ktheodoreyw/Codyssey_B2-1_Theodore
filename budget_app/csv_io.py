"""
csv_io.py — CSV 내보내기(export) / 가져오기(import)

[CSV 스키마 (명세 고정)]
  | column   | required | 설명                    |
  | date     | Y        | YYYY-MM-DD              |
  | type     | Y        | income / expense        |
  | category | Y        | 등록된 카테고리         |
  | amount   | Y        | 양수 정수               |
  | memo     | N        | 문자열                  |
  | tags     | N        | 쉼표(,) 구분 문자열     |
  공통: UTF-8(BOM 없음), 헤더 포함, 구분자 쉼표
- export 는 위 6개 열을 이 순서로 기록한다.
- import 는 필수 4개 열이 헤더에 있으면 받아들인다. memo/tags 가 없으면 빈 값으로,
  스키마 밖의 열(예: 다른 프로그램의 id, 비고)은 무시한다 → "최소 스키마" 를 유연하게 해석.
- 메모·태그에 쉼표가 있으면 csv 모듈이 자동으로 "..." 로 감싸므로 열이 밀리지 않는다.

[import 시 깨진 행 처리 — 평가 항목 4]
- 행마다 독립적으로 검증하여 "정상 행 목록"과 "오류 행 보고서"를 분리한다.
- 모드:
    partial(기본) : 정상 행만 저장하고, 오류 행은 줄 번호·원인과 함께 리포트로 출력
    strict        : 오류가 1건이라도 있으면 아무것도 저장하지 않고 종료(롤백)
- 어느 모드든 저장 자체는 services.py 가 write_all(원자적) 로 한 번에 수행하므로
  "절반만 들어간 상태" 는 발생하지 않는다.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from .errors import LedgerError, StorageError, ValidationError
from .models import Transaction

CSV_ENCODING = "utf-8"


# ---------------------------------------------------------------------------
# 내보내기
# ---------------------------------------------------------------------------

def export_csv(transactions: Iterable[Transaction], out_path: Path) -> int:
    """거래 이터러블을 CSV 로 기록하고, 기록한 행 수를 반환한다.

    - transactions 는 리스트가 아니라 제너레이터여도 된다 → 대용량도 스트리밍으로 기록.
    - newline="" : csv 모듈 권장 설정. 이 설정이 없으면 Windows 에서 빈 줄이 끼어든다.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    try:
        with out_path.open("w", encoding=CSV_ENCODING, newline="") as f:
            writer = csv.DictWriter(f, fieldnames=Transaction.CSV_COLUMNS)
            writer.writeheader()
            for tx in transactions:
                writer.writerow(tx.to_csv_row())
                count += 1
    except OSError as e:
        raise StorageError(
            f"CSV 파일을 쓸 수 없습니다: {out_path}",
            hint=f"경로와 권한을 확인하세요. (원인: {e.strerror or e})",
        ) from None
    return count


# ---------------------------------------------------------------------------
# 가져오기
# ---------------------------------------------------------------------------

@dataclass
class ImportError_:
    """깨진 행 1건에 대한 기록. (내장 ImportError 와 이름 충돌을 피하려 _ 를 붙임)"""

    line_no: int         # CSV 파일 내 줄 번호 (헤더 = 1행)
    reason: str          # 사람이 읽을 수 있는 원인
    raw: dict[str, Any]  # 원본 행 (디버깅용)


@dataclass
class ImportResult:
    """parse_csv 의 결과 — 정상 행과 오류 행을 분리해 담는다."""

    # (줄 번호, 거래) 쌍으로 보관 → 이후 단계(카테고리 검사)에서 오류로 바뀌어도 줄 번호를 보고할 수 있다
    valid: list[tuple[int, Transaction]] = field(default_factory=list)
    errors: list[ImportError_] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.valid) + len(self.errors)


def _normalize_header(fieldnames: Sequence[str] | None) -> list[str]:
    """헤더를 소문자·공백 제거로 정규화하고, 일부 편집기가 붙이는 BOM(\\ufeff) 을 제거한다.

    매개변수 타입을 list 가 아닌 Sequence 로 둔 이유:
      csv.DictReader.fieldnames 는 표준 타입 정의(typeshed)에서 `Sequence[str] | None` 으로
      선언돼 있다. 이 함수는 순회만 하므로 list 를 요구할 이유가 없고, list 로 좁혀 적으면
      정적 검사기가 "Sequence 를 list 자리에 넣을 수 없다" 고 경고한다
      (함수는 필요한 최소 능력만 요구하는 넓은 타입으로 받는 것이 원칙).
    """
    names = [h.strip().lower() for h in (fieldnames or [])]
    if names and names[0].startswith("﻿"):
        names[0] = names[0].lstrip("﻿")
    return names


def _check_header(fieldnames: Sequence[str] | None, path: Path) -> None:
    """필수 열(date, type, category, amount)이 모두 있는지 검사한다. 순서는 무관, 추가 열은 허용."""
    actual = _normalize_header(fieldnames)
    missing = [c for c in Transaction.CSV_REQUIRED if c not in actual]
    if missing:
        raise StorageError(
            f"CSV 헤더에 필수 열이 없습니다: {', '.join(missing)}  (파일: {path.name})",
            hint=f"헤더에 `{','.join(Transaction.CSV_COLUMNS)}` 가 포함되어야 합니다 (memo, tags 는 선택). "
                 f"현재 헤더: `{','.join(actual) or '(없음)'}`",
        )


def parse_csv(path: Path, id_allocator: Iterator[int]) -> ImportResult:
    """CSV 를 읽어 행마다 검증하고 ImportResult 로 돌려준다.

    Args:
        path:         읽을 CSV 경로
        id_allocator: 새 ID 를 하나씩 내주는 이터레이터(services.py 가 제공).
                      CSV 에 id 열이 있어도 무시한다 — 기존 거래와 충돌할 수 있으므로
                      import 되는 행은 항상 새 ID 를 받는다.

    Returns:
        ImportResult(valid=[(줄번호, Transaction)...], errors=[...])
    """
    if not path.exists():
        raise StorageError(
            f"CSV 파일이 없습니다: {path}",
            hint="경로를 확인하세요. 예) import -from samples/sample_import.csv",
        )

    result = ImportResult()
    try:
        with path.open("r", encoding=CSV_ENCODING, newline="") as f:
            reader = csv.DictReader(f)
            _check_header(reader.fieldnames, path)
            header = _normalize_header(reader.fieldnames)

            # reader 는 헤더 다음 행부터 돌므로 실제 파일 줄 번호는 +2 부터
            for offset, row in enumerate(reader):
                line_no = offset + 2
                try:
                    tx = _row_to_transaction(row, header, next(id_allocator))
                    result.valid.append((line_no, tx))
                except LedgerError as e:
                    # 한 행이 깨져도 전체를 멈추지 않고 사유만 기록한다
                    result.errors.append(ImportError_(line_no, e.message, dict(row)))
    except UnicodeDecodeError:
        raise StorageError(
            f"CSV 인코딩이 UTF-8 이 아닙니다: {path.name}",
            hint="파일을 UTF-8 로 다시 저장하세요. (Excel: 다른 이름으로 저장 > CSV UTF-8)",
        ) from None
    except OSError as e:
        raise StorageError(f"CSV 파일을 읽을 수 없습니다: {path} ({e.strerror or e})") from None
    return result


def _row_to_transaction(row: dict[str | None, Any], header: list[str], new_id: int) -> Transaction:
    """CSV 한 행(dict) → Transaction. 컬럼 개수 불일치도 여기서 잡는다.

    DictReader 는 값이 헤더보다 많으면 None 키에 리스트로, 적으면 값에 None 을 넣는다.
    """
    if None in row:
        raise ValidationError('컬럼 개수가 헤더보다 많습니다 (쉼표가 들어간 메모·태그는 "..." 로 감싸야 합니다)')
    if any(v is None for v in row.values()):
        raise ValidationError("컬럼 개수가 헤더보다 적습니다")
    # 원본 헤더 → 정규화된 이름으로 매핑 (원본 헤더에 대문자/BOM 이 있어도 동작)
    data: dict[str, Any] = {}
    for raw_key, norm_key in zip(row.keys(), header):
        data[norm_key] = (row[raw_key] or "").strip()
    data["id"] = new_id   # CSV 의 id 는 무시하고 새로 발급
    return Transaction.from_dict(data)
