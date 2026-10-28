from __future__ import annotations

import unicodedata
from typing import Iterable, Literal, Sequence

Align = Literal["left", "right"]


def display_width(text: str) -> int:
    """터미널에서 차지하는 칸 수. 동아시아 전각(W)·모호(F) 문자는 2칸으로 계산."""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def truncate(text: str, max_width: int) -> str:
    """보이는 폭이 max_width 를 넘으면 잘라 '…' 를 붙인다."""
    if display_width(text) <= max_width:
        return text
    out = ""
    for ch in text:
        if display_width(out + ch) > max_width - 1:
            break
        out += ch
    return out + "…"


def pad(text: str, width: int, align: Align = "left") -> str:
    """보이는 폭 기준으로 width 까지 공백을 채운다."""
    gap = max(0, width - display_width(text))
    return (" " * gap + text) if align == "right" else (text + " " * gap)


def fmt_money(amount: int, signed: bool = False) -> str:
    """12000 → '12,000'  /  signed=True 면 +12,000 / -3,000 처럼 부호를 붙인다."""
    if signed:
        return f"{amount:+,}"
    return f"{amount:,}"


def render_table(
    headers: Sequence[str],
    rows: Iterable[Sequence[object]],
    aligns: Sequence[Align] | None = None,
    max_col_width: int = 30,
) -> str:
    """헤더 + 행 목록을 정렬된 표 문자열로 만든다.

    Args:
        headers:  열 제목
        rows:     각 행 (리스트/튜플). 제너레이터여도 되지만 폭 계산을 위해 내부에서 1회 소비한다.
        aligns:   열별 정렬. 생략하면 int 값이 있는 열은 right, 나머지는 left 로 자동 판정.
        max_col_width: 셀 하나의 최대 폭 (초과 시 '…' 로 잘림)

    Returns:
        여러 줄로 된 표 문자열. 행이 없으면 헤더와 "(0건)" 안내만 반환.
    """
    str_rows: list[list[str]] = []
    for row in rows:
        str_rows.append([
            truncate(fmt_money(c) if isinstance(c, int) and not isinstance(c, bool) else str(c),
                     max_col_width)
            for c in row
        ])

    ncol = len(headers)
    if aligns is None:
        # 열에 숫자가 하나라도 있으면 오른쪽 정렬 (첫 번째 행 기준 추정)
        aligns = ["left"] * ncol
        if str_rows:
            for i in range(ncol):
                sample = str_rows[0][i].replace(",", "").replace("-", "").replace("+", "").replace("%", "")
                if sample.strip().isdigit():
                    aligns[i] = "right"

    widths = [display_width(h) for h in headers]
    for r in str_rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], display_width(cell))

    sep = "-+-".join("-" * w for w in widths)
    lines = [" | ".join(pad(h, widths[i], aligns[i]) for i, h in enumerate(headers)), sep]
    for r in str_rows:
        lines.append(" | ".join(pad(c, widths[i], aligns[i]) for i, c in enumerate(r)))
    if not str_rows:
        lines.append("(0건)")
    return "\n".join(lines)
