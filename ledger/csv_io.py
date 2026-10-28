from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

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
                writer.writerow(tx.to_dict())
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

    line_no: int       # CSV 파일 내 줄 번호 (헤더 = 1행)
    reason: str        # 사람이 읽을 수 있는 원인
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


def _check_header(fieldnames: list[str] | None, path: Path) -> None:
    """헤더가 정확히 스키마와 일치하는지 검사한다 (순서·이름·개수)."""
    expected = list(Transaction.CSV_COLUMNS)
    actual = [h.strip().lower() for h in (fieldnames or [])]
    # 일부 편집기는 맨 앞에 BOM(﻿) 을 붙인다 → 첫 컬럼에서 제거
    if actual and actual[0].startswith("﻿"):
        actual[0] = actual[0].lstrip("﻿")
    if actual != expected:
        raise StorageError(
            f"CSV 헤더가 스키마와 다릅니다: {path.name}",
            hint=f"헤더는 정확히 `{','.join(expected)}` 이어야 합니다. 현재: `{','.join(actual)}`",
        )


def parse_csv(path: Path, id_allocator: Iterator[int]) -> ImportResult:
    """CSV 를 읽어 행마다 검증하고 ImportResult 로 돌려준다.

    Args:
        path:         읽을 CSV 경로
        id_allocator: 새 ID 를 하나씩 내주는 이터레이터(services.py 가 제공).
                      CSV 의 id 컬럼은 "참고용" 으로만 보고 무시한다 — 기존 거래와
                      충돌할 수 있으므로 import 되는 행은 항상 새 ID 를 받는다.

    Returns:
        ImportResult(valid=[...], errors=[...])
    """
    if not path.exists():
        raise StorageError(
            f"CSV 파일이 없습니다: {path}",
            hint="경로를 확인하세요. 예) --file samples/sample_import.csv",
        )

    result = ImportResult()
    try:
        with path.open("r", encoding=CSV_ENCODING, newline="") as f:
            reader = csv.DictReader(f)
            _check_header(reader.fieldnames, path)

            # reader 는 헤더 다음 행부터 돌므로 실제 파일 줄 번호는 +2 부터
            for offset, row in enumerate(reader):
                line_no = offset + 2
                try:
                    tx = _row_to_transaction(row, next(id_allocator))
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


def _row_to_transaction(row: dict[str, Any], new_id: int) -> Transaction:
    """CSV 한 행(dict) → Transaction. 컬럼 개수 불일치도 여기서 잡는다."""
    # DictReader 는 컬럼이 모자라면 None 을, 넘치면 None 키에 리스트를 넣는다.
    if None in row:
        raise ValidationError("컬럼 개수가 헤더보다 많습니다 (쉼표가 들어간 메모는 \"...\" 로 감싸야 합니다)")
    if any(v is None for v in row.values()):
        raise ValidationError("컬럼 개수가 헤더보다 적습니다")
    data: dict[str, Any] = {k.strip().lower().lstrip("﻿"): (v or "").strip() for k, v in row.items()}
    data["id"] = new_id   # CSV 의 id 는 무시하고 새로 발급
    return Transaction.from_dict(data)
