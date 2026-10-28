from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Generic, Iterable, Iterator, Protocol, TypeVar

from .errors import NotFoundError, StorageError

# ---------------------------------------------------------------------------
# 타입 정의
# ---------------------------------------------------------------------------


class Serializable(Protocol):
    """JsonlStore 가 다룰 수 있는 모델의 최소 조건 (구조적 타이핑).

    Transaction / Category / Budget / RecurringRule 모두 이 두 메서드를 갖는다.
    별도 상속 없이도 '모양'만 맞으면 통과한다.
    """

    def to_dict(self) -> dict[str, Any]: ...


# T 는 Serializable 을 만족하는 어떤 모델 타입이든 될 수 있다.
# → JsonlStore[Transaction], JsonlStore[Budget] 처럼 하나의 클래스를 재사용한다.
T = TypeVar("T", bound=Serializable)


# ---------------------------------------------------------------------------
# 원자적 파일 쓰기 (모듈 레벨 함수 — 저장소·백업 모두 사용)
# ---------------------------------------------------------------------------

def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """content 를 path 에 원자적으로 기록한다.

    순서:
      1) path 와 같은 디렉터리에 임시 파일 생성 (os.replace 는 같은 파일시스템에서만 원자적)
      2) 내용 기록 → flush → fsync (OS 버퍼가 아닌 디스크까지 내려보냄)
      3) os.replace(tmp, path)  ← 이 한 줄이 원자적 교체
      4) 실패 시 임시 파일을 지워 쓰레기를 남기지 않음
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)  # 원자적 교체
    except OSError as e:
        tmp_path.unlink(missing_ok=True)
        raise StorageError(
            f"파일을 저장할 수 없습니다: {path}",
            hint=f"디스크 공간/권한을 확인하세요. (원인: {e.strerror or e})",
        ) from None


# ---------------------------------------------------------------------------
# JSONL 저장소 (제네릭)
# ---------------------------------------------------------------------------


class JsonlStore(Generic[T]):
    """모델 리스트 하나를 JSONL 파일 하나에 대응시키는 저장소.

    사용 예:
        store = JsonlStore(Path("data/transactions.jsonl"), Transaction.from_dict)
        for tx in store.iter_all():   # 제너레이터: 한 줄씩 읽음
            ...
        store.append(tx)              # 끝에 한 줄 추가
        store.write_all(list_of_tx)   # 전체 교체 (원자적)
    """

    def __init__(self, path: Path, from_dict: Callable[[dict[str, Any]], T]) -> None:
        self.path = path
        self._from_dict = from_dict   # dict → 모델 변환 함수 (models.py 가 제공)

    # --- 읽기 ---------------------------------------------------------------

    def iter_lines(self) -> Iterator[tuple[int, str]]:
        """(줄 번호, 원본 문자열) 을 한 줄씩 내보내는 저수준 제너레이터.

        파일이 없으면 '레코드 0건' 으로 간주하고 조용히 끝난다
        (첫 실행 시 data/ 가 비어 있는 것은 정상 상황).
        """
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                for lineno, raw in enumerate(f, start=1):
                    line = raw.strip()
                    if line:               # 빈 줄은 무시
                        yield lineno, line
        except OSError as e:
            raise StorageError(
                f"파일을 읽을 수 없습니다: {self.path}",
                hint=f"파일 권한을 확인하세요. (원인: {e.strerror or e})",
            ) from None

    def iter_all(self) -> Iterator[T]:
        """모델 객체를 한 건씩 내보내는 제너레이터 (스트리밍 처리의 핵심).

        - 파일 전체를 리스트로 올리지 않으므로 거래가 수십만 건이어도
          메모리 사용량은 '현재 처리 중인 한 줄' 수준에 머문다.
        - list / search 는 이 제너레이터 위에 filter 를 얹어 지연 평가한다.
        - 깨진 줄이 발견되면 줄 번호를 포함한 StorageError 를 던진다
          (어느 줄을 고쳐야 하는지 사용자가 바로 알 수 있도록).
        """
        for lineno, line in self.iter_lines():
            try:
                yield self._from_dict(json.loads(line))
            except json.JSONDecodeError as e:
                raise StorageError(
                    f"{self.path.name} {lineno}번째 줄이 올바른 JSON 이 아닙니다.",
                    hint=f"해당 줄을 수정하거나 삭제한 뒤 다시 실행하세요. (원인: {e.msg})",
                ) from None
            except Exception as e:  # ValidationError 등 모델 변환 실패
                raise StorageError(
                    f"{self.path.name} {lineno}번째 줄의 데이터가 유효하지 않습니다: {e}",
                    hint="backup restore 로 정상 백업을 복원하거나 해당 줄을 수정하세요.",
                ) from None

    def read_all(self) -> list[T]:
        """전체를 리스트로 읽는다 (update/delete 처럼 전체 재기록이 필요할 때만 사용)."""
        return list(self.iter_all())

    # --- 쓰기 ---------------------------------------------------------------

    def append(self, item: T) -> None:
        """파일 끝에 레코드 한 줄을 추가한다 (add 전용, O(1)).

        - ensure_ascii=False : 한글을 \\uXXXX 로 바꾸지 않고 그대로 저장 → 사람이 읽기 쉬움.
        - 한 줄 전체를 한 번의 write 로 기록하고 fsync 까지 수행한다.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(item.to_dict(), ensure_ascii=False) + "\n"
        try:
            with self.path.open("a", encoding="utf-8", newline="\n") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
        except OSError as e:
            raise StorageError(
                f"파일에 추가할 수 없습니다: {self.path}",
                hint=f"디스크 공간/권한을 확인하세요. (원인: {e.strerror or e})",
            ) from None

    def write_all(self, items: Iterable[T]) -> None:
        """전체 내용을 items 로 교체한다 — 원자적(임시 파일 + os.replace).

        update / delete / import(부분 실패 롤백) / category remove(재할당) 에서 사용.
        """
        content = "".join(json.dumps(it.to_dict(), ensure_ascii=False) + "\n" for it in items)
        atomic_write_text(self.path, content)


# ---------------------------------------------------------------------------
# 백업 관리자 (보너스 기능)
# ---------------------------------------------------------------------------


class BackupManager:
    """data/ 디렉터리의 저장 파일들을 backups/<타임스탬프>/ 로 복사·복원한다.

    - create(): 현재 상태 스냅샷 생성
    - list():   스냅샷 목록(이름, 생성 시각, 파일 수)
    - restore(name): 스냅샷으로 되돌리기. 되돌리기 직전 상태도 자동 백업해 두어
      "복원을 잘못 했을 때" 다시 돌아올 수 있게 한다.
    """

    def __init__(self, data_dir: Path, backup_dir: Path, file_names: tuple[str, ...]) -> None:
        self.data_dir = data_dir
        self.backup_dir = backup_dir
        self.file_names = file_names   # 백업 대상 파일명 목록 (services.py 가 지정)

    def create(self, label: str | None = None) -> Path:
        """backups/YYYYMMDD-HHMMSS[-label]/ 에 저장 파일들을 복사한다."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"{stamp}-{label}" if label else stamp
        target = self.backup_dir / name
        try:
            target.mkdir(parents=True, exist_ok=False)
            copied = 0
            for fname in self.file_names:
                src = self.data_dir / fname
                if src.exists():
                    shutil.copy2(src, target / fname)  # copy2: 수정 시각 등 메타데이터 유지
                    copied += 1
            if copied == 0:  # 백업할 파일이 하나도 없으면 빈 디렉터리를 남기지 않음
                target.rmdir()
                raise StorageError(
                    "백업할 데이터 파일이 없습니다.",
                    hint="먼저 add 로 거래를 추가한 뒤 백업하세요.",
                )
        except FileExistsError:
            raise StorageError(
                f"같은 이름의 백업이 이미 존재합니다: {name}",
                hint="1초 뒤 다시 시도하거나 --label 로 다른 이름을 주세요.",
            ) from None
        except OSError as e:
            raise StorageError(f"백업 생성 실패: {e}") from None
        return target

    def list(self) -> list[tuple[str, str, int]]:
        """(백업명, 생성시각 'YYYY-MM-DD HH:MM:SS', 파일 수) 를 최신순으로 반환."""
        if not self.backup_dir.exists():
            return []
        dirs = [d for d in self.backup_dir.iterdir() if d.is_dir()]
        dirs.sort(key=lambda d: (d.stat().st_mtime, d.name), reverse=True)   # 최신 백업이 위로
        return [
            (d.name,
             datetime.fromtimestamp(d.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
             sum(1 for _ in d.glob("*.jsonl")))
            for d in dirs
        ]

    def restore(self, name: str) -> Path:
        """지정 백업을 data/ 로 복원한다. 복원 전 현재 상태를 'pre-restore' 로 자동 백업."""
        src_dir = self.backup_dir / name
        if not src_dir.is_dir():
            raise NotFoundError(
                f"백업을 찾을 수 없습니다: {name}",
                hint="`backup list` 로 사용 가능한 백업 이름을 확인하세요.",
            )
        # 안전장치: 현재 데이터가 하나라도 있으면 먼저 보존
        if any((self.data_dir / f).exists() for f in self.file_names):
            self.create(label="pre-restore")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for fname in self.file_names:
            src = src_dir / fname
            dst = self.data_dir / fname
            if src.exists():
                # 복원도 원자적으로: 내용을 읽어 atomic_write_text 로 교체
                atomic_write_text(dst, src.read_text(encoding="utf-8"))
            elif dst.exists():
                dst.unlink()  # 백업에 없던 파일은 제거해 스냅샷과 동일한 상태로 맞춤
        return src_dir
