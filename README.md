# ledger-cli — JSONL 기반 개인 가계부 CLI

> Python 표준 라이브러리만으로 구현한 콘솔 가계부.
> 기본 기능 10개 + 보너스 기능 3개(백업 / 반복 내역 / 테이블 정렬) = **총 13개 기능**,
> 보너스 '저장 원자성 강화' 는 update / delete 구현에 포함.

---

## 목차

1. [빠른 시작 (VS Code → GitHub)](#1-빠른-시작-vs-code--github)
2. [프로젝트 구조](#2-프로젝트-구조)
3. [저장 포맷 선택: JSONL (근거)](#3-저장-포맷-선택-jsonl-근거)
4. [구현 기능 13개 — 구현 방법과 실행 예시](#4-구현-기능-13개--구현-방법과-실행-예시)
5. [평가문항 대응 설명](#5-평가문항-대응-설명)
   - [항목 1 — 기능 동작](#항목-1--기능-동작)
   - [항목 2 — 모듈·클래스 책임 / 안전한 update·delete](#항목-2--모듈클래스-책임--안전한-updatedelete)
   - [항목 3 — 제너레이터 / 데코레이터 / 타입 힌트](#항목-3--제너레이터--데코레이터--타입-힌트)
   - [항목 4 — 포맷 비교 / 10만 건 병목 / 깨진 CSV](#항목-4--포맷-비교--10만-건-병목--깨진-csv)
6. [테스트](#6-테스트)
7. [종료 코드 규약](#7-종료-코드-규약)

---

## 1. 빠른 시작 (VS Code → GitHub)

### 요구 사항
- Python **3.10 이상** (3.13 에서 검증)
- 외부 패키지 **없음** — `requirements.txt` 는 비어 있음

### VS Code 에서 열고 GitHub 로 올리기
```powershell
# 1) 압축 해제 후 VS Code 로 열기
cd ledger-cli
code .

# 2) (선택) 가상환경 — 표준 라이브러리만 쓰므로 생략 가능
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate

# 3) 동작 확인
python main.py -h
python -m unittest -v                  # 31개 테스트 통과 확인

# 4) Git 초기화 → GitHub 푸시
git init
git add .
git commit -m "feat: JSONL 기반 가계부 CLI 초기 구현 (기본 10 + 보너스 3)"
git branch -M main
git remote add origin https://github.com/<계정>/<저장소>.git
git push -u origin main
```
- `.gitignore` 가 `data/*.jsonl`, `backups/*`, `*.csv`(samples 제외) 를 제외하므로 개인 데이터는 커밋되지 않음
- `.vscode/launch.json` 에 디버그 구성 2개 포함 (F5 로 바로 실행, `LEDGER_DEBUG=1` 설정됨)
- `.vscode/settings.json` 에서 unittest 탐색 설정 → VS Code 테스트 탭에서 실행 가능

### 가장 짧은 사용 예
```powershell
python main.py add --date 2026-10-28 --type expense --category 식비 --amount 12000 --memo 점심
python main.py list --month 2026-10
python main.py summary --month 2026-10
```

---

## 2. 프로젝트 구조

```
ledger-cli/
├── main.py                 # 진입점: cli.main() 의 반환값을 sys.exit 에 전달
├── ledger/                 # 패키지 (의존 방향: cli → services → storage/csv_io → models → errors)
│   ├── errors.py           # 예외 계층 + 종료 코드 (LedgerError 와 4개 하위 클래스)
│   ├── models.py           # 데이터 모델 4개 + 검증 규칙 (Transaction/Category/Budget/RecurringRule)
│   ├── storage.py          # JSONL 저장소(제너레이터 읽기, 원자적 쓰기), BackupManager
│   ├── csv_io.py           # CSV 내보내기/가져오기, 깨진 행 리포트
│   ├── formatters.py       # 한글 폭 보정 테이블 정렬, 금액 표기
│   ├── decorators.py       # handle_errors / log_action / timed
│   ├── services.py         # 업무 규칙: Transaction/Category/Budget/Recurring Service + LedgerApp
│   └── cli.py              # argparse 명령 정의, 출력
├── tests/test_ledger.py    # unittest 31개
├── samples/
│   ├── sample_import.csv   # 정상 CSV
│   └── broken_import.csv   # 깨진 행 5개가 섞인 CSV (항목 4 시연용)
├── data/                   # 저장 파일 4개 (실행 시 자동 생성, git 제외)
│   ├── transactions.jsonl  # 거래
│   ├── categories.jsonl    # 카테고리
│   ├── budgets.jsonl       # 예산
│   ├── recurring.jsonl     # 반복 규칙
│   └── ledger.log          # 명령 실행 로그 (데코레이터가 기록)
├── backups/                # backup create 결과 (git 제외)
├── .vscode/                # 디버그·테스트 설정
├── .gitignore
└── requirements.txt
```

### 모듈 간 책임 (한눈에)
| 모듈 | 아는 것 | 모르는 것 |
|---|---|---|
| `models.py` | 필드 구조, 유효성 규칙 | 파일, 콘솔 |
| `storage.py` | 파일 읽기/쓰기/백업 | 예산·카테고리 규칙 |
| `csv_io.py` | CSV 스키마, 행 단위 검증 | 카테고리 존재 여부 (업무 규칙) |
| `services.py` | 가계부 규칙, 서비스 조합 | print, argparse |
| `cli.py` | 명령 해석, 출력 | 파일 포맷 |
| `decorators.py` | 예외→메시지, 로그, 시간 | 명령 내용 |
| `formatters.py` | 화면 폭, 정렬 | 데이터 의미 |

---

## 3. 저장 포맷 선택: JSONL (근거)

### 결론
- **주 저장소 = JSONL**, **교환 포맷 = CSV** (export / import 전용)

### JSONL 을 선택한 이유
| 관점 | JSONL | CSV |
|---|---|---|
| `add` 비용 | 끝에 한 줄 append → **O(1)**, 전체 재기록 없음 | append 가능하지만 헤더 관리·따옴표 이스케이프 부담 |
| 손상 격리 | 한 줄 = 한 레코드 → 깨진 줄만 번호로 지목 가능 | 메모 안 줄바꿈/쉼표가 다음 행까지 오염시킬 수 있음 |
| 타입 | `int`, `list`(applied_months) 그대로 보존 | 모든 값이 문자열 → 매번 형변환·검증 필요 |
| 스키마 변경 | 필드 추가 시 기존 줄과 공존 (키 없으면 기본값) | 열 추가 시 모든 행·헤더 재작성 |
| 스트리밍 | `for line in f` → `json.loads` → yield 가 자연스러움 | 가능하지만 `csv` 모듈 상태 의존 |
| 사람이 읽기 | 키 이름이 보여 자기설명적 (`"amount": 12000`) | 헤더를 기억해야 함 |
| 엑셀 호환 | 직접 열기 불편 | **우수** → 이 장점은 export 로 확보 |

### 트레이드오프 인정
- 파일 크기: JSONL 은 키 이름이 반복되어 CSV 보다 약 2배 큼 (10만 건 ≈ 11.6 MB) → 개인 가계부 규모에서는 무시 가능
- 엑셀 편집: 사용자는 `export` → 엑셀 → `import` 흐름으로 해결
- 같은 이유로 **CSV 는 버리지 않고 교환 포맷으로 남겼다** (두 포맷의 장점을 역할별로 분리)

---

## 4. 구현 기능 13개 — 구현 방법과 실행 예시

> 모든 예시는 실제 실행 결과를 붙여 넣은 것 (`[exit=n]` 은 종료 코드).

### 기본 기능

#### 4-1. `add` — 거래 추가
- **구현**
  - `TransactionService.add()` 가 `Transaction(...)` 을 생성 → `__post_init__` 에서 날짜·유형·금액·카테고리 검증
  - 카테고리는 `CategoryService.require()` 로 존재 확인 (없으면 `category add` 힌트와 함께 실패)
  - 저장은 `JsonlStore.append()` — 파일 끝에 한 줄 + `fsync` (전체 재기록 없음)
  - 금액은 `3,000,000` 처럼 쉼표 허용, 소수·0·음수 거부
- **예시**
```
$ python main.py add --date 2026-10-01 --type income --category 급여 --amount 3,000,000 --memo "10월 급여"
추가됨: #1 2026-10-01 수입 급여 3,000,000원 10월 급여
[exit=0]

$ python main.py add --date 2026-02-30 --type expense --category 식비 --amount 1000
[오류] 존재하지 않는 날짜입니다: 2026-02-30
[힌트] 월(01~12)과 일(01~31) 범위를 확인하세요.
[exit=1]
```
- **저장 결과 (`data/transactions.jsonl`)**
```json
{"id": 1, "date": "2026-10-01", "type": "income", "category": "급여", "amount": 3000000, "memo": "10월 급여"}
```

#### 4-2. `list` — 거래 목록
- **구현**
  - `TransactionService.iter_filtered()` **제너레이터** 가 파일을 한 줄씩 읽으며 조건(월/유형/카테고리)에 맞는 것만 `yield`
  - `--limit N` 이면 N건을 받는 즉시 순회를 멈춰 나머지 파일은 읽지 않음
  - `--sort date|amount` 를 주면 그때만 전체를 메모리에 올려 정렬 (트레이드오프를 옵션으로 노출)
  - 출력은 `formatters.render_table()` (보너스 4-13)
- **예시**
```
$ python main.py list --month 2026-10 --type expense --limit 2
ID | 날짜       | 유형 | 카테고리 |   금액 | 메모
---+------------+------+----------+--------+--------------
 2 | 2026-10-02 | 지출 | 식비     | 12,000 | 점심 김치찌개
 3 | 2026-10-02 | 지출 | 교통     |  1,550 | 지하철
(2건 표시)
```

#### 4-3. `search` — 거래 검색
- **구현**
  - `list` 와 같은 제너레이터를 재사용하되 키워드(메모·카테고리 부분일치, 대소문자 무시), 기간(`--from/--to`), 금액 범위(`--min/--max`) 조건을 추가
  - 날짜가 ISO 형식이므로 문자열 비교(`tx.date < date_from`)가 곧 시간 비교 → 파싱 비용 없음
  - 조건이 하나도 없으면 안내 후 `exit 1`
- **예시**
```
$ python main.py search --keyword 커피
ID | 날짜       | 유형 | 카테고리 |  금액 | 메모
---+------------+------+----------+-------+----------------
 4 | 2026-10-05 | 지출 | 식비     | 4,500 | 아메리카노 커피
(1건 일치)

$ python main.py search --from 2026-10-01 --to 2026-10-31 --min 10000
ID | 날짜       | 유형 | 카테고리 |      금액 | 메모
---+------------+------+----------+-----------+--------------
 1 | 2026-10-01 | 수입 | 급여     | 3,000,000 | 10월 급여
 2 | 2026-10-02 | 지출 | 식비     |    12,000 | 점심 김치찌개
 5 | 2026-10-10 | 지출 | 주거     |   650,000 | 월세
(3건 일치)
```

#### 4-4. `summary` — 월별/전체 요약 + 예산 사용률
- **구현**
  - `TransactionService.summarize()` 가 제너레이터를 **한 번만** 순회하며 수입·지출·건수·카테고리별 지출을 동시에 누적
  - 예산은 `BudgetService.list(month)` 결과와 조인해 `BudgetUsage(limit, used)` 생성 → `ratio`, `status`(정상 / 주의 ≥80% / 초과 >100%) 를 프로퍼티로 계산
  - 서비스는 `Summary` 객체만 반환, 출력 형식은 `cli.cmd_summary` 담당
- **예시**
```
$ python main.py summary --month 2026-10
== 2026-10 요약 (5건) ==
수입  :      3,000,000원
지출  :        668,050원
순액  :     +2,331,950원

[카테고리별 지출]
카테고리 |    지출 |   비중
---------+---------+-------
주거     | 650,000 |  97.3%
식비     |  16,500 |   2.5%
교통     |   1,550 |   0.2%

[예산 사용 현황]
카테고리 |    예산 |    사용 |   잔여 | 사용률 | 상태
---------+---------+---------+--------+--------+-----
식비     |  15,000 |  16,500 | -1,500 | 110.0% | 초과
주거     | 700,000 | 650,000 | 50,000 |  92.9% | 주의
※ 예산 초과: 식비
```

#### 4-5. `export` — CSV 내보내기
- **구현**
  - 스키마 고정: **UTF-8**, 헤더 `id,date,type,category,amount,memo` (`Transaction.CSV_COLUMNS` 가 단일 출처)
  - `csv.DictWriter` + `newline=""` → 쉼표·줄바꿈이 든 메모는 자동으로 `"..."` 처리, Windows 빈 줄 문제 방지
  - 제너레이터를 그대로 넘겨 **스트리밍 기록** (10만 건도 메모리 상수)
- **예시**
```
$ python main.py export --out export_2026-10.csv --month 2026-10
내보내기 완료: 5건 → export_2026-10.csv (UTF-8, 헤더: id,date,type,category,amount,memo)

$ cat export_2026-10.csv
id,date,type,category,amount,memo
1,2026-10-01,income,급여,3000000,10월 급여
2,2026-10-02,expense,식비,12000,점심 김치찌개
...
```

#### 4-6. `import` — CSV 가져오기 (깨진 행 처리 포함)
- **구현**
  - `csv_io.parse_csv()` 가 헤더를 스키마와 정확히 대조(순서·개수·BOM 제거) → 다르면 즉시 `exit 2`
  - 행마다 독립 검증 → `ImportResult(valid=[(줄번호, Transaction)], errors=[(줄번호, 원인, 원본)])`
  - 컬럼 수 초과/부족도 행 단위 오류로 분류 (`DictReader` 의 `None` 키/값 감지)
  - 카테고리 존재 여부는 **업무 규칙** 이므로 `services` 에서 2차 검사 (`--create-categories` 로 자동 등록 가능)
  - 모드: `partial`(기본, 정상 행만 저장 + 리포트) / `strict`(오류 1건이라도 있으면 저장 0건)
  - 저장은 `write_all()` **한 번** → 절반만 들어가는 상태 없음; CSV 의 `id` 는 무시하고 새로 발급
- **예시**
```
$ python main.py import --file samples/sample_import.csv
가져오기 결과: 총 4행 중 성공 4건, 실패 0건 (mode=partial)

$ python main.py import --file samples/broken_import.csv
가져오기 결과: 총 7행 중 성공 2건, 실패 5건 (mode=partial)

[실패한 행 — 수정 후 다시 가져오면 됩니다]
줄 | 원인                                                                  | 원본
---+-----------------------------------------------------------------------+---------------------------------------------------
 3 | 존재하지 않는 날짜입니다: 2026-13-03                                  | ,2026-13-03,expense,식비,8500,월이 13 (잘못된 날짜)
 4 | 거래 유형이 올바르지 않습니다: 'expens'                               | ,2026-10-04,expens,식비,8500,유형 오타
 5 | 금액은 정수여야 합니다: 'abc'                                         | ,2026-10-04,expense,식비,abc,금액이 문자
 6 | 컬럼 개수가 헤더보다 많습니다 (쉼표가 들어간 메모는 "..." 로 감싸야 … | ,2026-10-04,expense,식비,8500,컬럼이,하나,더,많음
 7 | 미등록 카테고리: 취미 (--create-categories 로 자동 등록 가능)         | ,2026-10-04,expense,취미,15000,미등록 카테고리
[exit=0]

$ python main.py import --file samples/broken_import.csv --mode strict
[오류] strict 모드: 오류 행 5건이 있어 아무것도 저장하지 않았습니다.
[힌트] 오류 행을 수정하거나 `--mode partial` 로 정상 행만 가져오세요.
[exit=2]
```

#### 4-7. `update` — 거래 수정 (저장 원자성 강화 포함)
- **구현**
  - 지정한 옵션만 교체: `date if date is not None else tx.date` 패턴 → 새 `Transaction` 생성 시 재검증
  - 순서: ① `read_all()` ② 메모리에서 대상 교체 ③ `write_all()`
  - `write_all()` = **임시 파일에 전체 기록 → `flush` + `os.fsync` → `os.replace()`** 로 원자적 교체
    - 어느 시점에 프로세스가 죽어도 "완전한 이전 파일" 또는 "완전한 새 파일" 만 존재
    - 임시 파일은 같은 디렉터리에 생성 (`os.replace` 는 같은 파일시스템에서만 원자적)
    - 실패 시 임시 파일 삭제 → 쓰레기 파일 없음 (테스트 `AtomicWriteTest` 로 검증)
  - 변경 항목이 하나도 없으면 `exit 1`
- **예시**
```
$ python main.py update 2 --amount 13500 --memo "점심 김치찌개(가격 인상)"
수정 전: #2 2026-10-02 지출 식비 12,000원 점심 김치찌개
수정 후: #2 2026-10-02 지출 식비 13,500원 점심 김치찌개(가격 인상)
```

#### 4-8. `delete` — 거래 삭제 (저장 원자성 강화 포함)
- **구현**
  - 대상을 제외한 나머지를 `write_all()` 로 원자적 재기록 (4-7 과 동일 경로)
  - 대상이 없으면 `NotFoundError` → `exit 3`
- **예시**
```
$ python main.py delete 3
삭제됨: #3 2026-10-02 지출 교통 1,550원 지하철

$ python main.py delete 999
[오류] 거래 ID 999 를 찾을 수 없습니다.
[힌트] `list` 로 ID 를 확인하세요.
[exit=3]
```

#### 4-9. `category add / list / remove` — 카테고리 관리
- **구현**
  - 첫 실행 시 `ensure_seed()` 가 기본 5개(식비·교통·주거·급여·기타) 를 `categories.jsonl` 에 생성
  - `add`: 중복 이름 거부 / `list`: 카테고리별 거래 수를 제너레이터로 계산
  - `remove` (사용 중인 카테고리 처리):
    - `--reassign` 없이 사용 중 → `CategoryInUseError` 로 거부 (안전 기본값)
    - `--reassign 기타` → 거래·반복규칙을 옮기고(없으면 생성), 해당 카테고리 예산은 삭제, 각 파일은 `write_all` 원자적 기록
    - 카테고리 자체 삭제는 **마지막** 단계 → 앞 단계가 실패해도 카테고리가 남아 재시도 가능
- **예시**
```
$ python main.py category remove 식비
[오류] 카테고리 '식비' 은(는) 거래 6건에서 사용 중이라 삭제할 수 없습니다.
[힌트] `category remove 식비 --reassign 기타` 처럼 옮길 카테고리를 지정하세요.
[exit=1]

$ python main.py category remove 교통 --reassign 기타
카테고리 삭제됨: 교통 (거래 2건·반복규칙 0건 → '기타' 로 이동, 예산 0건 삭제)

$ python main.py category list
카테고리 | 거래수 | 생성일
---------+--------+-----------
식비     |      3 | 2026-10-28
주거     |      1 | 2026-10-28
급여     |      1 | 2026-10-28
기타     |      2 | 2026-10-28
```

#### 4-10. `budget set / list` — 예산 설정
- **구현**
  - `Budget(month, category, amount)` 의 `(month, category)` 가 복합 키 → 같은 키로 다시 `set` 하면 덮어씀
  - `budgets.jsonl` 에 저장(원자적), `summary` 에서 사용률/초과 여부로 출력(4-4 참고)
- **예시**
```
$ python main.py budget set --month 2026-10 --category 식비 --amount 15000
예산 설정됨: 2026-10 식비 15,000원

$ python main.py budget list
월      | 카테고리 |    예산
--------+----------+--------
2026-10 | 식비     |  15,000
2026-10 | 주거     | 700,000
```

### 보너스 기능

#### 4-11. `backup create / list / restore` — 백업
- **구현**
  - `BackupManager.create()`: `backups/YYYYMMDD-HHMMSS[-label]/` 에 저장 파일 4개를 `shutil.copy2` 로 복사
  - `list()`: 최신순 (백업명, 생성시각, 파일 수)
  - `restore(name)`: 복원 **직전 상태를 `-pre-restore` 로 자동 백업** 한 뒤, 각 파일을 `atomic_write_text` 로 교체 → 잘못 복원해도 되돌릴 수 있음
- **예시**
```
$ python main.py backup create --label after-recurring
백업 생성됨: 20261028-040635-after-recurring (4개 파일)

$ python main.py delete 15        # 실수로 삭제했다고 가정
$ python main.py backup restore 20261028-040635-after-recurring
복원 완료: 20261028-040635-after-recurring → .../data  (복원 직전 상태는 '*-pre-restore' 백업으로 보관)

$ python main.py backup list
백업명                           | 생성시각            | 파일수
---------------------------------+---------------------+-------
20261028-040635-pre-restore      | 2026-10-28 04:06:35 |      4
20261028-040635-after-recurring  | 2026-10-28 04:06:35 |      4
20261028-040635-before-recurring | 2026-10-28 04:06:35 |      3
```

#### 4-12. `recurring add / list / apply / remove` — 반복 내역
- **구현**
  - `RecurringRule(day, type, category, amount, memo, applied_months)` 를 `recurring.jsonl` 에 저장
  - `apply --month YYYY-MM`: 규칙마다 거래 1건 생성, 31일 규칙이 2월이면 `calendar.monthrange` 로 말일 보정
  - **중복 생성 방지 2중 장치**
    1. `applied_months` 에 해당 월이 있으면 건너뜀
    2. 생성 거래 메모 끝에 `[반복#규칙ID]` 꼬리표를 붙이고, 같은 달에 그 꼬리표가 이미 있으면 건너뜀 (①을 기록하기 직전에 죽은 경우 대비)
- **예시**
```
$ python main.py recurring add --day 31 --type expense --category 기타 --amount 9900 --memo "음악 스트리밍"
반복 규칙 추가됨: #2 매월 31일 지출 기타 9,900원 음악 스트리밍

$ python main.py recurring apply --month 2027-02
2027-02 반복 거래 2건 생성:
ID | 날짜       | 유형 | 카테고리 |    금액 | 메모
---+------------+------+----------+---------+-----------------------
17 | 2027-02-25 | 지출 | 주거     | 650,000 | 월세 [반복#1]
18 | 2027-02-28 | 지출 | 기타     |   9,900 | 음악 스트리밍 [반복#2]   ← 31일 → 28일 보정

$ python main.py recurring apply --month 2027-02
2027-02 에 새로 생성할 반복 거래가 없습니다 (이미 적용됐거나 규칙 없음).
```

#### 4-13. 출력 포맷 테이블 정렬
- **구현**
  - 문제: 한글은 터미널에서 2칸을 차지 → `str.ljust` 로 맞추면 열이 어긋남 (`len("식비")==2` 지만 화면 폭 4)
  - 해결: `unicodedata.east_asian_width()` 로 글자별 폭(1/2) 합산 → **보이는 폭** 기준으로 패딩 (`formatters.display_width`)
  - 숫자 열은 오른쪽 정렬 + 천 단위 쉼표, 문자 열은 왼쪽 정렬, 긴 셀은 `…` 로 잘라 표 유지
  - `list / search / summary / category / budget / backup / recurring / import 리포트` 모든 표가 같은 함수 사용
  - `--format plain` 으로 표 없이 한 줄 출력도 가능 (스크립트 파이프용)
- **예시** — 위 모든 표 참고. 혼합 폭 정렬 테스트(`FormatterTest`)로 모든 행 폭이 동일함을 검증

---

## 5. 평가문항 대응 설명

### 항목 1 — 기능 동작

| 평가 요구 | 구현 위치 | 확인 방법 |
|---|---|---|
| add/list/search/summary/export/import/update/delete 동작 | `services.TransactionService`, `cli.cmd_*` | 4-1 ~ 4-8 예시 |
| 재실행 후 데이터 유지, 저장 파일 3개 이상 | `data/` 에 **4개** JSONL (transactions / categories / budgets / recurring) | `CrudTest.test_data_survives_new_app_instance` |
| category add/list/remove, 사용 중 카테고리 처리 | `CategoryService.remove(reassign_to)` | 4-9 예시, `CategoryTest` |
| budget set 저장, summary 에서 사용률/초과 | `BudgetService.set`, `TransactionService.summarize` → `BudgetUsage.status` | 4-4 예시 (110.0% 초과 / 92.9% 주의) |
| import/export CSV 스키마 (UTF-8, 헤더, 컬럼) | `csv_io.py` 상단 스키마 정의, `_check_header` | 4-5, 4-6 예시 |
| 오류 시 스택트레이스 없이 메시지 + 힌트 | `decorators.handle_errors`, `cli.FriendlyParser.error` | 아래 예시, `CliExitCodeTest` 에서 `"Traceback" not in stderr` 검증 |
| 오류 시 종료 코드 ≠ 0 | 예외 클래스의 `exit_code` 속성 → `main.py` 의 `sys.exit` | 7장 표 |

- **오류 출력 형식** (모든 오류가 동일한 2줄 패턴)
```
$ python main.py add --date 2026-10-01 --type expense --category 없는카테고리 --amount 1000
[오류] 존재하지 않는 카테고리입니다: 없는카테고리
[힌트] `category add 없는카테고리` 으로 먼저 등록하거나 `category list` 로 목록을 확인하세요.
[exit=3]

$ python main.py list          # transactions.jsonl 18번째 줄이 잘린 상태
[오류] transactions.jsonl 18번째 줄이 올바른 JSON 이 아닙니다.
[힌트] 해당 줄을 수정하거나 삭제한 뒤 다시 실행하세요. (원인: Unterminated string starting at)
[exit=2]
```
- 종료 코드 확인: Windows `echo %ERRORLEVEL%` (cmd) / `$LASTEXITCODE` (PowerShell), macOS/Linux `echo $?`

### 항목 2 — 모듈·클래스 책임 / 안전한 update·delete

#### 코드를 8개 모듈로 나눈 기준 — "어떻게"
- **변경 이유(reason to change)가 다른 것은 다른 파일에** 두었다
  - 저장 포맷을 JSONL → SQLite 로 바꾸고 싶다 → `storage.py` 만 교체 (서비스·CLI 는 그대로)
  - 출력을 표 대신 JSON 으로 바꾸고 싶다 → `cli.py` / `formatters.py` 만 수정
  - 예산 "주의" 기준을 80% → 90% 로 바꾸고 싶다 → `services.BudgetUsage.status` 한 줄
- **의존 방향을 한쪽으로만** 흐르게 했다: `cli → services → (storage, csv_io) → models → errors`
  - 아래 계층은 위 계층을 import 하지 않음 → 순환 참조 없음, 각 계층을 독립 테스트 가능
- **횡단 관심사**(오류 처리·로그·시간 측정) 는 `decorators.py` 로 뽑아 13개 핸들러에 동일하게 적용

#### 클래스 책임 경계 — "어떻게" 정했는가 (2개 이상)
| 클래스 | 소유하는 것 | 하지 않는 것 | 경계를 그은 이유 |
|---|---|---|---|
| `JsonlStore[T]` (storage) | 한 파일 ↔ 한 모델 리스트의 읽기/추가/원자적 교체 | 레코드 내용 해석, 업무 규칙 | 제네릭 1개로 파일 4개를 모두 처리 → 중복 제거 |
| `TransactionService` | 거래 CRUD·검색·집계·CSV 교환 | 콘솔 출력, 파일 포맷 | 출력을 모르므로 테스트가 print 를 가로챌 필요 없음 |
| `CategoryService` | 카테고리 CRUD, "사용 중" 판정, 재할당 삭제 | 거래 자체의 검증 | 삭제가 거래·예산·반복규칙 3개 파일을 건드리므로 그 조정 책임을 한 곳에 모음 |
| `BudgetService` / `RecurringService` | 각자의 파일과 규칙 | 서로의 데이터 | 반복 규칙 생성은 `TransactionService.add` 를 **호출** 해 거래 규칙을 재사용 |
| `LedgerApp` | 저장소·서비스 조립 | 업무 로직 | `data_dir` 하나만 바꾸면 테스트용 임시 가계부가 됨 |
| `BackupManager` | 스냅샷 생성·목록·복원 | 레코드 해석 | 파일 단위 복사만 하므로 모델이 바뀌어도 영향 없음 |

#### 파일 기반 update/delete 를 "어떻게" 안전하게 처리했는가
1. **전체 읽기 → 메모리 수정 → 전체 쓰기** 를 택했다 (파일 중간을 제자리 수정하지 않음)
   - JSONL 은 줄 길이가 가변이라 in-place 수정은 뒤쪽 줄을 모두 밀어야 하고, 그 중간에 죽으면 복구 불가
2. 전체 쓰기는 **`atomic_write_text`** 로만 수행
   - 같은 디렉터리에 `tempfile.mkstemp` → 내용 기록 → `flush` → `os.fsync` → **`os.replace`**
   - `os.replace` 는 POSIX/Windows 모두에서 원자적 rename → 독자는 항상 완전한 파일만 본다
   - 예외 발생 시 임시 파일을 삭제해 잔여물을 남기지 않음 (`AtomicWriteTest.test_no_temp_file_left_and_content_replaced`)
3. **검증을 쓰기 전에** 모두 끝낸다
   - `update` 는 새 `Transaction` 을 먼저 만들어(`__post_init__` 검증) 통과한 뒤에만 `write_all`
   - 잘못된 금액으로 update 하면 파일은 한 바이트도 바뀌지 않음
4. 다중 파일을 건드리는 `category remove` 는 **실패해도 재시도 가능한 순서** 로 기록 (거래 → 규칙 → 예산 → 카테고리 삭제는 마지막)
5. 대상이 없으면 쓰기 자체를 하지 않고 `NotFoundError(exit 3)`
6. 추가 안전망: `backup create` 로 수동 스냅샷, `restore` 시 자동 `pre-restore` 백업

### 항목 3 — 제너레이터 / 데코레이터 / 타입 힌트

#### list/search 를 제너레이터로 스트리밍 — "어떻게" 구현, "왜" 유리한가
- **구현 (3단 파이프라인, 모두 제너레이터)**
  ```python
  # storage.py
  def iter_lines(self):            # ① 파일에서 한 줄씩
      with self.path.open(...) as f:
          for lineno, raw in enumerate(f, 1): yield lineno, raw.strip()
  def iter_all(self):              # ② 한 줄 → 모델 1개
      for lineno, line in self.iter_lines(): yield self._from_dict(json.loads(line))
  # services.py
  def iter_filtered(self, month=None, ...):   # ③ 조건에 맞는 것만
      for tx in self._store.iter_all():
          if month and tx.month != month: continue
          yield tx
  ```
  - `cli._print_transactions` 가 `for tx in gen:` 으로 소비하다 `--limit` 에 도달하면 `break` → 상위 제너레이터들도 함께 멈추고 파일 핸들은 `with` 가 닫음
- **왜 유리한가 (실측, 10만 건 11.6 MB)**
  | 명령 | 시간 | 최대 메모리 |
  |---|---|---|
  | `list --limit 5` (스트리밍) | **0.5 ms** | **18 MB** (인터프리터 기본치 수준) |
  | `list --sort date --limit 5` (전체 materialize) | ~420 ms | **69 MB** |
  | `summary --month 2026-10` | 400 ms | 상수 (누적 변수만 유지) |
  - 리스트로 다 읽는 방식은 "5건만 보고 싶어도" 10만 건을 전부 객체로 만든다
  - 제너레이터는 **필요한 만큼만** 계산 → 응답 시간·메모리 모두 데이터 크기와 무관(limit 사용 시)
  - 같은 제너레이터를 `list / search / summary / export / usage_count` 가 공유 → 필터 로직 중복 없음
  - 트레이드오프: 정렬·전체 건수처럼 "모든 원소를 봐야 하는" 연산은 이점이 없으므로 `--sort` 를 명시적 옵션으로 두어 사용자가 선택하게 함

#### 데코레이터로 분리한 공통 기능 — 무엇이며 "왜" 필요했는가
| 데코레이터 | 하는 일 | 분리하지 않았다면 |
|---|---|---|
| `@handle_errors` | `LedgerError` → `[오류]/[힌트]` 2줄 + 종료 코드 반환, 예상 밖 예외는 `exit 2` (`LEDGER_DEBUG=1` 이면 트레이스백) | 13개 핸들러마다 같은 `try/except` 13벌, 메시지 형식이 조금씩 달라짐 |
| `@log_action(path)` | 명령명·시각·성공/실패코드를 `data/ledger.log` 에 기록 | 로그 한 줄 추가하려고 13곳 수정 |
| `@timed` | `LEDGER_TIMING=1` 일 때 실행 시간을 stderr 로 출력 | 성능 실험용 코드가 업무 로직에 섞임 |
- **적용 순서가 의미를 가진다**
  ```python
  @log_action(LOG_PATH)   # 바깥: handle_errors 가 돌려준 종료코드까지 기록 (실패도 남음)
  @handle_errors          # 중간: 예외를 종료코드로 변환
  @timed                  # 안쪽: 순수 실행 시간만 측정
  def cmd_add(app, a): ...
  ```
  - 처음엔 `handle_errors` 를 바깥에 두었더니 실패한 명령이 로그에 남지 않았다 → 순서를 바꿔 해결 (트러블슈팅)
- `functools.wraps` 로 원본 이름을 유지 → 로그에 `cmd_add` 가 정확히 찍히고 디버거에서도 혼동 없음

#### 타입 힌트의 이점 — 실제 코드로 "어떻게" 확인했고 "왜" 도움이 되는가
- **`Literal["income", "expense"]` (models.TxType)**: `"expens"` 같은 오타를 Pylance 가 즉시 빨간줄로 표시 — 실행 전에 잡힘
- **`JsonlStore[Transaction]` (Generic + TypeVar)**: `store.iter_all()` 의 반환을 IDE 가 `Iterator[Transaction]` 으로 추론 → `tx.` 입력 시 `amount, memo…` 자동완성, `Category` 저장소에 `Transaction` 을 넣으려 하면 경고
- **`ParamSpec` / `TypeVar` (decorators)**: 데코레이터를 씌워도 `cmd_add(app, a)` 의 인자·반환 타입이 그대로 유지 → 데코레이터가 "타입을 지우는" 문제 방지
- **`Protocol` (storage.Serializable)**: `to_dict()` 만 있으면 어떤 모델이든 저장소에 넣을 수 있다는 계약을 상속 없이 표현
- **`int | None` 옵션 인자**: `iter_filtered(min_amount=None)` 에서 `None` 체크를 빠뜨리면 `tx.amount < None` 비교에 대해 정적 검사기가 경고
- **실무적 이점**: `.vscode/settings.json` 의 `typeCheckingMode: basic` 으로 저장 시마다 검사 → 테스트를 돌리기 전에 인자 순서 실수(`add(type, date, …)`)를 잡았다

### 항목 4 — 포맷 비교 / 10만 건 병목 / 깨진 CSV

#### JSONL vs CSV — 3장 참조 (요약)
- 주 저장소는 **append O(1), 줄 단위 손상 격리, 타입·스키마 유연성, 스트리밍 친화** 때문에 JSONL
- CSV 는 엑셀 호환이라는 고유 장점이 있어 **버리지 않고 교환 포맷** 으로 역할 분리

#### 거래 10만 건 — 현재 구조의 병목과 개선안 (실측 기반)
| 연산 | 10만 건 실측 | 병목 원인 | 개선안 |
|---|---|---|---|
| `list --limit` | 0.5 ms | 없음 (지연 평가) | — |
| `search`, `summary` | ~400 ms | 전체 스캔 O(n): `json.loads` 10만 번 | ① 월별 파일 분할(`2026-10.jsonl`) → 월 조회는 1/12 만 읽음 ② 별도 인덱스 파일(월→오프셋) |
| `add` | ~450 ms | **`next_id()` 가 최대 ID 를 찾기 위해 전체 스캔** — append 자체는 O(1) | `meta.jsonl` 에 마지막 ID 를 캐시하거나 파일 끝에서 역방향으로 1줄만 읽기 → O(1) |
| `update` / `delete` | ~1.0~1.2 s | 전체 읽기 + 전체 재기록 O(n) 11.6 MB | ① 삭제 표시(tombstone) 줄 append + 주기적 compaction(append-only log 방식) ② 월별 분할로 재기록 범위 축소 |
| `category list` | 카테고리 수 × O(n) | 카테고리마다 전체 스캔 | 한 번 스캔으로 `Counter` 집계 |
| 그 이상 (100만 건~) | — | 파일 기반 한계 | **SQLite** 로 교체 — `storage.py` 만 바꾸면 됨 (인덱스·트랜잭션 내장) |

- 설계상 이미 확보한 것: 저장소가 `JsonlStore` 한 클래스에 캡슐화되어 있어 위 개선은 서비스·CLI 코드를 건드리지 않고 적용 가능

#### import CSV 에 깨진 행이 섞였을 때 — 사용자 신뢰를 지키는 처리
- **원칙: 조용히 버리지도, 전부 거부하지도 않는다 — 사용자가 결과를 정확히 알고 선택하게 한다**
- **부분 성공 (기본 `partial`)**
  - 정상 행은 저장, 깨진 행은 **줄 번호 + 원인 + 원본** 표로 리포트 → 사용자가 그 줄만 고쳐 다시 가져오면 됨
  - 저장은 `write_all` 1회(원자적) → "일부만 반영된 뒤 죽는" 상태 없음
  - 성공 0건이면 `exit 1` 로 실패 신호
- **롤백 (`--mode strict`)**
  - 오류가 1건이라도 있으면 파일을 **전혀 건드리지 않고** `exit 2` → 배치/자동화에서 "전부 아니면 무" 보장
- **리포트 설계**
  - 헤더 불일치는 행 단위가 아니라 파일 단위 오류이므로 즉시 중단 (스키마 혼동 방지)
  - 컬럼 수 초과·부족, 잘못된 날짜·유형·금액, 미등록 카테고리를 **각각 다른 문장** 으로 지목
  - CSV 의 `id` 는 무시하고 새로 발급 → 기존 거래 덮어쓰기 사고 차단
  - 인코딩이 UTF-8 이 아니면 Excel 저장 방법까지 힌트로 안내
- 4-6 예시의 7행 CSV 로 재현 가능 (`samples/broken_import.csv`), `CsvTest` 3개로 검증

---

## 6. 테스트

```powershell
python -m unittest -v                       # 31개
python -m unittest tests.test_ledger.CsvTest -v
```
| 테스트 클래스 | 검증 내용 |
|---|---|
| `ModelValidationTest` | 날짜/유형/금액 검증, 쉼표 허용·소수 거부 |
| `CrudTest` | JSONL 한 줄 저장, 재실행 후 유지, 부분 update, delete, 없는 ID/카테고리 |
| `GeneratorTest` | 지연 평가(next 1회), 월·키워드·금액 필터 |
| `CategoryTest` | 사용 중 삭제 거부, `--reassign` 시 거래·예산·규칙 정리 |
| `BudgetSummaryTest` | 주의/초과 상태, 순액, 같은 키 덮어쓰기 |
| `CsvTest` | export→import 왕복(쉼표 메모 포함), 줄 번호 리포트, strict 롤백, 헤더 검사 |
| `AtomicWriteTest` | 임시 파일 잔여물 없음, 손상 줄 번호 보고 |
| `BackupRecurringTest` | 백업/복원 + pre-restore, 월 1회 생성·말일 보정 |
| `FormatterTest` | 한글 폭 계산, 혼합 폭 정렬 |
| `CliExitCodeTest` | 종료 코드 0/1/2/3, 스택트레이스 부재 |

---

## 7. 종료 코드 규약

| 코드 | 의미 | 예 |
|---|---|---|
| 0 | 정상 | 모든 성공 명령 |
| 1 | 사용자 입력 오류 | 잘못된 날짜·금액, 인자 누락, 사용 중 카테고리 삭제, import 성공 0건 |
| 2 | 파일/저장소 오류 | JSONL 손상, CSV 없음·헤더 불일치, strict import 실패, 예상 밖 예외 |
| 3 | 대상 없음 | 없는 거래 ID, 없는 카테고리, 없는 백업명 |
| 130 | 사용자 중단 (Ctrl+C) | — |

- 개발 시 환경변수: `LEDGER_DEBUG=1` (예상 밖 예외의 트레이스백 표시), `LEDGER_TIMING=1` (명령 실행 시간 표시)
