# B2-1 나만의 용돈 기입장 프로그램 만들기

> Python 표준 라이브러리만으로 구현한 파일 입출력 기반의 가계부 콘솔 프로그램

---

## 1. 프로젝트 개요

### 미션 소개
- Python으로 파일 입출력 기반의 가계부 콘솔 프로그램을 구현
- 수입과 지출 내역 저장, 수정/삭제, 검색, 월별 요약, 카테고리 관리, 예산 초과 경고까지 포함한 "작은 서비스" 구현
- 저장 파일을 한 번에 모두 읽지 않고 제너레이터로 스트리밍 처리
- 데코레이터로 공통 기능(예외 처리, 실행 로그, 실행 시간 측정 등)을 분리
- 타입 힌트를 적용해 함수와 데이터 구조의 계약을 명확히 하고, 모듈 분리로 유지보수 가능한 구조를 설계

### 과제 목표
- 파일 기반 저장(JSONL/CSV)으로 데이터를 영구 저장하고, CRUD/검색/요약/입출력을 구현
- 콘솔 프로그램을 클래스/모듈로 구조화하고, 각 계층(모델/저장소/서비스/CLI)의 책임을 설명
- yield 기반 제너레이터로 대용량 파일도 스트리밍 처리하는 이유와 동작 방식을 설명
- 데코레이터로 공통 관심사(로그/예외/시간 측정) 를 분리한 구조와 이유를 설명
- 타입 힌트를 통해 입출력 계약을 명확히 했을 때 얻는 이점을 실제 코드 예로 설명

---

## 2. 프로그램 구조
### 레포지토리 구조
```
budget-app/
├── main.py                 # 호환용 래퍼 (python main.py ...)
├── budget_app/             # 패키지 — python -m budget_app
│   ├── __main__.py         # 진입점: cli.main() 의 종료 코드를 sys.exit 에 전달
│   ├── errors.py           # 예외 계층 + 종료 코드 (LedgerError 와 4개 하위 클래스)
│   ├── models.py           # 데이터 모델 4개 + 값 검증 규칙 (Transaction/Category/Budget/RecurringRule)
│   ├── storage.py          # JSONL 저장소(제너레이터 읽기, 원자적 쓰기), BackupManager
│   ├── csv_io.py           # CSV 내보내기/가져오기, 깨진 행 리포트
│   ├── formatters.py       # 한글 폭 보정 테이블 정렬, 금액 표기
│   ├── decorators.py       # handle_errors / log_action / timed
│   ├── prompt.py           # 대화형 입력(input) 헬퍼 — add 의 재입력 흐름
│   ├── services.py         # 업무 규칙: Transaction/Category/Budget/Recurring Service + LedgerApp
│   └── cli.py              # argparse 명령 정의(-/-- 동시 등록, -help), 출력
├── tests/test_budget_app.py # unittest 39개 (대화형 입력은 input 을 모킹)
├── samples/                # sample_import.csv, broken_import.csv
├── data/                   # 저장 파일 4개 + 로그 (실행 시 자동 생성, git 제외)
├── backups/                # 백업 스냅샷 (git 제외)
├── .vscode/                # 디버그·테스트 설정
├── .gitignore
└── requirements.txt        # 비어 있음 (표준 라이브러리만)
```

### 모듈별 역할
| 모듈 | 역할 |
|---|---|
| `cli.py` | 명령 해석, 출력 |
| `csv_io.py` | CSV 읽기/쓰기 |
| `decorators.py` | 예외 처리, 로그 기록, 실행 시간 측정 |
| `formatters.py` | 화면 폭, 정렬 |
| `models.py` | 필드 구조, 유효성 규칙 |
| `prompt.py` | 사용자에게 묻고 재입력 받기 |
| `storage.py` | JSONL 읽기/쓰기/백업 |
| `services.py` | 가계부 규칙, 서비스 조합 |

---

## 3. 저장 정책

### 정책 개요
- **저장 포맷 = JSONL**
- **교환 포맷 = CSV**(export / import 전용)

### JSONL을 저장 포맷으로 선택한 경쟁우위
| 관점 | JSONL | CSV |
|---|---|---|
| 손상 | 한 줄 = 한 레코드 처리로 깨진 줄만 번호로 지목 가능해 손상 격리 | 메모 안 줄 바꿈/쉼표가 다음 행까지 손상 오염 |
| 타입 | `int`, `list` 타입 그대로 보존 | 모든 값이 문자열로 전환되어 매번 형 변환 및 검증 필요 |
| 스키마 변경 | 필드 추가 시 새로운 row 추가하여 유연성, 비용, 속도 우위 | 필드 추가 시 모든 행 및 헤더 재작성 |
| 가독성 | 키 이름이 보여 직관적 (`"amount": 12000`) | 헤더를 기억해야 해 다량의 데이터 확인 시 불편 |
| 스프레드 시트 호환 | 직접 열기 불편 | 호환성 우수 |

### 경쟁열위 및 대안 
- 파일 크기: JSONL 은 키 이름이 반복되어 CSV 보다 약 2배 크지만 본 프로그램 규모에서는 무시 가능
- 스프레드 시트 편집: 사용자는 `export` → 엑셀 → `import` 흐름으로 해결
- 종합: **CSV 방식을 폐기하지 않고 교환 포맷으로 활용**

## 저장 파일 위치 / 형식

| 파일 | 내용 | 한 줄 예시 |
|---|---|---|
| `data/transactions.jsonl` | 거래 | `{"id": 1, "date": "2026-10-29", "type": "expense", "category": "식비", "amount": 12000, "memo": "점심", "tags": ["회사"]}` |
| `data/categories.jsonl` | 카테고리 | `{"name": "식비", "created_at": "2026-10-29"}` |
| `data/budgets.jsonl` | 월 예산 | `{"month": "2026-10", "amount": 700000}` |
| `data/recurring.jsonl` | 반복 규칙(보너스) | `{"id": 1, "day": 25, "type": "expense", "category": "주거", "amount": 650000, "memo": "월세", "tags": ["고정비"], "applied_months": ["2026-11"]}` |
| `data/ledger.log` | 명령 실행 로그 | `2026-10-29 11:33:39 \| cmd_add \| ok` |
| `backups/YYYYMMDD-HHMMSS[-label]/` | 백업 스냅샷 (위 jsonl 4개 복사본) | — |

- 형식: **JSONL (JSON Lines)** — 한 줄 = 레코드 1건, UTF-8, 한글 그대로 저장(`ensure_ascii=False`)
- 명세 "3개 이상 파일 분리" → 4개 파일 사용
- 위치 변경: `python -m budget_app -data-dir D:\gagebu list`

---

## 4. 구현 기능 및 실행 결과

### 기본 기능

#### 4-1. `add`: 거래 추가
- **구현**
  - `prompt.ask_transaction()` 이 `input()` 으로 6개 항목을 순서대로 물음 
  - 날짜는 Enter 시 오늘, 유형은 `1/2`, `income/expense`, `수입/지출` 모두 허용, 카테고리는 번호 또는 이름
  - 각 항목의 검증은 `models.validate_*` 함수를 그대로 재사용 → 잘못된 값이면 `[오류]/[힌트]` 출력 후 **그 항목만 재입력**(단, 5회 실패 시 중단)
  - 미등록 카테고리를 입력하면 등록 여부를 물어 바로 등록 가능(명세 4-④ "안내 후 재입력/등록 유도")
  - 검증을 통과한 값으로 `TransactionService.add()` → `Transaction(...)` 생성(`__post_init__` 재검증) → `JsonlStore.append()` 한 줄 기록
  - 저장 후 **생성된 id** 출력
- **예시**
```
$ python -m budget_app add
[안내] 저장 폴더를 초기화했습니다: .../data  (기본 카테고리 자동 생성: 식비, 교통, 주거, 급여, 기타)
── 거래 추가 (Ctrl+C 로 취소) ──
날짜 (YYYY-MM-DD) [기본: 2026-10-29]: 2026-02-30
[오류] 존재하지 않는 날짜입니다: 2026-02-30
[힌트] 월(01~12)과 일(01~31) 범위를 확인하세요.
날짜 (YYYY-MM-DD) [기본: 2026-10-29]: 2026-10-01
유형 (1=수입 income / 2=지출 expense): income
카테고리 목록: 1) 식비  2) 교통  3) 주거  4) 급여  5) 기타
카테고리 (번호 또는 이름): 4
금액 (원, 정수): 3,000,000
메모 [Enter = 생략]: 10월 급여
태그 (쉼표로 구분) [Enter = 생략]: 월급
저장 완료: 거래 id=1  (#1 2026-10-01 수입 급여 3,000,000원 10월 급여 [월급])
[exit=0]
```
- 입력이 없는 환경(파이프 등)에서는 스택트레이스 없이 `[오류] 대화형 입력이 중단되었습니다` + `exit 1`

#### 4-2. `list`: 거래 목록(최신순)
- **구현**
  - `TransactionService.iter_filtered()` **제너레이터**가 파일을 한 줄씩 읽어 조건(`-month`, `-type`, `-category`)에 맞는 것만 `yield`
  - `newest_first(stream, limit)` 가 `heapq.nlargest` 로 스트림을 한 번 훑으며 **상위 limit 건만 메모리에 유지** → 최신순(날짜↓, 같은 날이면 id↓)
  - `-limit` 기본 20, `-limit 0` 은 전체
- **예시**
```
$ python -m budget_app list -limit 3
ID | 날짜       | 유형 | 카테고리 |    금액 | 메모            | 태그
---+------------+------+----------+---------+-----------------+----------
 1 | 2026-10-29 | 지출 | 식비     |  12,000 | 점심 김치찌개   | 점심,회사
 5 | 2026-10-10 | 지출 | 주거     | 650,000 | 월세            |
 4 | 2026-10-05 | 지출 | 식비     |   4,500 | 아메리카노 커피 | 카페
(최신순 3건 표시, -limit 3)
```

#### 4-3. `search`: 거래 검색
- **구현**
  - `list` 와 같은 제너레이터에 `-from/-to`(기간), `-category`, `-type`, `-q`(메모 부분일치, 대소문자 무시), `-tag`(태그 정확히 일치) 조건을 추가
  - 날짜가 ISO 형식이므로 문자열 비교(`tx.date < date_from`)가 곧 시간 비교
  - 결과는 최신순, `-limit`(기본 전체) 지원
  - 조건이 하나도 없으면 안내 후 `exit 1`
- **예시**
```
$ python -m budget_app search -q 커피
ID | 날짜       | 유형 | 카테고리 |  금액 | 메모            | 태그
---+------------+------+----------+-------+-----------------+-----
 4 | 2026-10-05 | 지출 | 식비     | 4,500 | 아메리카노 커피 | 카페
(1건 일치, 최신순)

$ python -m budget_app search -from 2026-10-01 -to 2026-10-31 -category 식비
 1 | 2026-10-29 | 지출 | 식비     | 12,000 | 점심 김치찌개   | 점심,회사
 4 | 2026-10-05 | 지출 | 식비     |  4,500 | 아메리카노 커피 | 카페
(2건 일치, 최신순)

$ python -m budget_app search -tag 회식
 6 | 2026-09-28 | 지출 | 식비     | 38,000 | 회식 | 회식
```

#### 4-4. `summary`: 월별 요약 + TOP N + 예산 사용률
- **구현**
  - `summarize(month, budget)` 가 제너레이터를 **한 번만** 순회하며 총수입·총지출·건수·카테고리별 지출을 동시에 누적 → `Summary` 객체 반환
  - 잔액 = 총 수입 − 총 지출, `top_categories(n)` 로 TOP N (`-top`, 기본 설정 N: 5)
  - 거래가 0건이면 **"데이터 없음"** 을 명시 출력 (명세 8)
  - 예산이 있으면 사용률(%)·상태(정상 / 주의 ≥80% / 초과 >100%)·잔여 예산, 초과 시 경고 문구
- **예시**
```
$ python -m budget_app summary -month 2026-10 -top 2
== 2026-10 월별 요약 ==
거래 건수 : 5건
총 수입   :      3,000,000원
총 지출   :        668,050원
잔액      :     +2,331,950원

[카테고리별 지출 TOP 2]
순위 | 카테고리 |    지출 |   비중
-----+----------+---------+-------
   1 | 주거     | 650,000 |  97.3%
   2 | 식비     |  16,500 |   2.5%

[예산 사용 현황]
월 예산   :        600,000원
사용률    :         111.3%  (초과)
잔여 예산 :        -68,050원
※ 경고: 예산을 68,050원 초과했습니다!

$ python -m budget_app summary -month 2026-12
== 2026-12 월별 요약 ==
2026-12: 데이터 없음 (거래가 한 건도 없습니다)
```

#### 4-5. `budget set / list`: 월 예산
- **구현**
  - `Budget(month, amount)`에서 `month` 가 유일 키, 같은 월로 다시 `set` 하면 덮어씀
  - `budgets.jsonl` 에 `write_all`(원자적) 저장 → 영구 보존, `summary` 가 읽어 사용률 계산
- **예시**
```
$ python -m budget_app budget set -month 2026-10 -amount 700000
예산 저장 완료: 2026-10 월 예산 700,000원

$ python -m budget_app budget list
월      |    예산
--------+--------
2026-10 | 700,000
```

#### 4-6. `category add / list / remove`: 카테고리 관리
- **구현**
  - 첫 실행 시 기본 5개 자동 생성
  - `add` 는 중복 거부, `list` 는 카테고리별 거래 수를 제너레이터로 계산
  - `remove` 는 사용 중이면 **삭제를 막고**, `-reassign <대체>` 를 주면 거래, 반복규칙을 옮긴 뒤 삭제(대체 카테고리가 없으면 자동 생성). 카테고리 자체 삭제는 마지막 단계 → 중간 실패 시 재시도 가능
- **예시**
```
$ python -m budget_app category remove 식비
[오류] 카테고리 '식비' 은(는) 거래 7건에서 사용 중이라 삭제할 수 없습니다.
[힌트] `category remove 식비 -reassign 기타` 처럼 옮길 카테고리를 지정하세요.
[exit=1]

$ python -m budget_app category remove 취미 -reassign 기타
카테고리 삭제됨: 취미 (거래 1건·반복규칙 0건 → '기타' 로 이동)

$ python -m budget_app category list
카테고리 | 거래수 | 생성일
---------+--------+-----------
식비     |      3 | 2026-10-29
교통     |      1 | 2026-10-29
...
```

#### 4-7. `update`: 거래 수정 
- **구현**
  - `update -id <id>` 에 바꿀 항목만 옵션으로 지정. 지정하지 않은 항목은 유지, 하나도 없으면 `exit 1`
  - 새 `Transaction` 을 먼저 만들어(`__post_init__` 검증) 통과한 뒤에만 저장 → 잘못된 값이면 파일은 한 바이트도 안 바뀜
  - 저장은 `write_all()` = **임시 파일에 전체 기록 → `flush` + `os.fsync` → `os.replace()`** 로 원자적 교체
  - 어느 시점에 코드가 중단되어도 "완전한 이전 파일" 또는 "완전한 새 파일" 만 존재
- **예시**
```
$ python -m budget_app update -id 2 -category 급여 -tags 월급
수정 완료 (id=2)
  수정 전: #2 2026-10-01 수입 취미 3,000,000원 10월 급여
  수정 후: #2 2026-10-01 수입 급여 3,000,000원 10월 급여 [월급]

$ python -m budget_app update --id 999 --amount 1
[오류] 거래 ID 999 를 찾을 수 없습니다.
[힌트] `list` 명령으로 존재하는 ID 를 확인하세요.
[exit=3]
```

#### 4-8. `delete`: 거래 삭제
- **구현**: 대상을 제외한 나머지를 `write_all()` 로 원자적 재기록. 없는 id 는 `NotFoundError` → `exit 3`
- **예시**
```
$ python -m budget_app delete -id 3
삭제 완료: #3 2026-10-02 지출 교통 1,550원 지하철 [출근]

$ python -m budget_app delete --id 999
[오류] 거래 ID 999 를 찾을 수 없습니다.
[힌트] `list` 로 ID 를 확인하세요.
[exit=3]
```

#### 4-9. `import`: CSV 가져오기
- **구현**
  - `import -from <csv>`. `csv_io.parse_csv()` 가 헤더에 필수 열(date, type, category, amount)이 있는지 확인(순서 무관, 대소문자, BOM 무시, 추가 열 무시) → 없으면 `exit 2`
  - 행마다 독립 검증 → `ImportResult(valid=[(줄번호, Transaction)], errors=[(줄번호, 원인, 원본)])`. 컬럼 수 초과/부족도 행 단위 오류
  - 카테고리 존재 여부는 **업무 규칙**이므로 `services` 에서 2차 검사 (`-create-categories` 로 자동 등록 가능)
  - `-mode partial`(기본): 정상 행만 저장 + 실패 행 리포트 / `-mode strict`: 오류 1건이라도 있으면 저장 0건
  - 저장은 `write_all()` **한 번** → 일부만 저장하는 상태 없음
- **예시**
```
$ python -m budget_app import -from samples/sample_import.csv
가져오기 결과: 총 4행 중 성공 4건, 실패 0건 (mode=partial)

$ python -m budget_app import -from samples/broken_import.csv
가져오기 결과: 총 7행 중 성공 2건, 실패 5건 (mode=partial)

[실패한 행 — 수정 후 다시 가져오면 됩니다]
줄 | 원인                                                                             | 원본
---+----------------------------------------------------------------------------------+------------------------------------------------
 3 | 존재하지 않는 날짜입니다: 2026-13-03                                             | 2026-13-03,expense,식비,8500,월이 13 (잘못된 날짜),
 4 | 거래 유형이 올바르지 않습니다: 'expens'                                          | 2026-10-04,expens,식비,8500,유형 오타,
 5 | 금액은 정수여야 합니다: 'abc'                                                    | 2026-10-04,expense,식비,abc,금액이 문자,
 6 | 컬럼 개수가 헤더보다 많습니다 (쉼표가 들어간 메모·태그는 "..." 로 감싸야 합니다) | 2026-10-04,expense,식비,8500,컬럼이,하나,더,많음
 7 | 미등록 카테고리: 여행 (-create-categories 로 자동 등록 가능)                     | 2026-10-04,expense,여행,15000,미등록 카테고리,

$ python -m budget_app import --from samples/broken_import.csv -mode strict
[오류] strict 모드: 오류 행 5건이 있어 아무것도 저장하지 않았습니다.
[힌트] 오류 행을 수정하거나 `-mode partial` 로 정상 행만 가져오세요.
[exit=2]
```

#### 4-10. `export`: CSV 내보내기
- **구현**
  - `export -out <csv>` + 조건 **필수**: `-month YYYY-MM` 또는 `-from/-to` (명세 11). 조건이 없으면 `exit 1`
  - `csv.DictWriter` + `newline=""` → 쉼표가 든 메모·태그는 자동으로 `"..."` 처리, Windows 빈 줄 문제 방지
  - 최신순으로 기록, 처리 건수 출력
- **예시**
```
$ python -m budget_app export -out oct.csv -month 2026-10
내보내기 완료: 4건 → oct.csv  (조건: -month 2026-10, UTF-8, 헤더: date,type,category,amount,memo,tags)

$ cat oct.csv
date,type,category,amount,memo,tags
2026-10-29,expense,식비,12000,점심 김치찌개,"점심,회사"
2026-10-10,expense,주거,650000,월세,
2026-10-05,expense,식비,4500,아메리카노 커피,카페
2026-10-01,income,급여,3000000,10월 급여,월급

$ python -m budget_app export -out x.csv
[오류] export 에는 조건이 필요합니다.
[힌트] -month YYYY-MM 또는 -from YYYY-MM-DD / -to YYYY-MM-DD 중 하나 이상을 지정하세요.
[exit=1]
```

### 보너스 기능

#### 4-11. `backup`: 백업 / 복원
- **구현**
  - `backup` (= `backup create [-label]`): `backups/YYYYMMDD-HHMMSS[-label]/` 에 저장 파일 `shutil.copy2` 로 복사 — **타임스탬프 포함** 백업
  - `backup list`: 최신순 (백업명, 생성시각, 파일 수)
  - `backup restore -name <백업명>`: 복원 **직전 상태를 `-pre-restore` 로 자동 백업** 한 뒤 각 파일을 `atomic_write_text` 로 교체 → 잘못 복원해도 되돌릴 수 있음
- **예시**
```
$ python -m budget_app backup
백업 생성됨: .../backups/20261029-113339  (3개 파일)

$ python -m budget_app delete -id 19        # 실수로 삭제했다고 가정
$ python -m budget_app backup restore -name 20261029-113339-after-recurring
복원 완료: 20261029-113339-after-recurring → .../data  (복원 직전 상태는 '*-pre-restore' 백업으로 보관)

$ python -m budget_app backup list
백업명                          | 생성시각            | 파일수
--------------------------------+---------------------+-------
20261029-113339-pre-restore     | 2026-10-29 11:33:40 |      4
20261029-113339-after-recurring | 2026-10-29 11:33:39 |      4
20261029-113339                 | 2026-10-29 11:33:39 |      3
```

#### 4-12. `recurring add / list / apply / remove`: 반복 내역
- **구현**
  - `RecurringRule(day, type, category, amount, memo, tags, applied_months)` 를 `recurring.jsonl` 에 저장
  - `apply -month YYYY-MM`: 규칙마다 거래 1건 생성(내부적으로 `TransactionService.add` 재사용), 31일 규칙이 2월이면 `calendar.monthrange` 로 말일 보정
  - **중복 생성 방지 2중 장치**: ① `applied_months` 에 해당 월이 있으면 건너뜀 ② 생성 거래에 `반복#<규칙ID>` 태그를 붙이고 같은 달에 그 태그가 이미 있으면 건너뜀 (①을 기록하기 직전에 죽은 경우 대비)
- **예시**
```
$ python -m budget_app recurring add -day 31 -type expense -category 기타 -amount 9900 -memo "음악 스트리밍"
반복 규칙 추가됨: #2 매월 31일 지출 기타 9,900원 음악 스트리밍

$ python -m budget_app recurring apply -month 2027-02
2027-02 반복 거래 2건 생성:
ID | 날짜       | 유형 | 카테고리 |    금액 | 메모          | 태그
---+------------+------+----------+---------+---------------+--------------
18 | 2027-02-25 | 지출 | 주거     | 650,000 | 월세          | 고정비,반복#1
19 | 2027-02-28 | 지출 | 기타     |   9,900 | 음악 스트리밍 | 반복#2          ← 31일 → 28일 보정

$ python -m budget_app recurring apply -month 2027-02
2027-02 에 새로 생성할 반복 거래가 없습니다 (이미 적용됐거나 규칙 없음).
```

#### 4-13. 출력 포맷 테이블 정렬
- **구현**
  - 문제: 한글은 터미널에서 2칸을 차지 → `str.ljust`로 맞추면 열이 어긋남 (`len("식비")==2` 지만 화면 폭 4 차지)
  - 해결: `unicodedata.east_asian_width()`로 글자별 폭(1/2) 합산 → **보이는 폭** 기준으로 패딩(`formatters.display_width`)
  - 숫자 열은 오른쪽 정렬 + 천 단위 쉼표, 문자 열은 왼쪽 정렬, 긴 셀은 `…` 로 잘라 표 유지
  - `list / search / summary / category / budget / backup / recurring / import 리포트` 모든 표가 같은 함수 사용
  - `--format plain` 으로 표 없이 한 줄 출력도 가능
- **예시** — 위 모든 표 참고. 혼합 폭 정렬 테스트(`FormatterTest`)로 모든 행 폭이 동일함을 검증

#### 4-14. 저장 원자성 강화
- `storage.atomic_write_text()`: 같은 폴더에 임시 파일 → 전체 기록 → `fsync` → `os.replace()` (rename) 로 교체. 실패 시 임시 파일 삭제. `AtomicWriteTest` 로 검증

---

## 5. 테스트

```powershell
python -m unittest -v                                  
python -m unittest tests.test_budget_app.InteractiveAddTest -v
```
| 테스트 클래스 | 검증 내용 |
|---|---|
| `ModelValidationTest` (5) | 날짜/유형(별칭 포함)/금액 검증, 태그 파싱, CSV 열 순서 |
| `CrudTest` (7) | 첫 실행 초기화, JSONL 한 줄 저장(tags 포함), 재실행 후 유지, 부분 update·태그 제거, delete, 없는 ID/카테고리 |
| `StreamingTest` (3) | 지연 평가(next 1회), 월, 키워드, 태그 필터, 최신순 + limit(힙) |
| `CategoryTest` (2) | 사용 중 삭제 거부, `-reassign` 시 거래, 규칙 이동 |
| `BudgetSummaryTest` (2) | 총수입/총지출/잔액/TOP N, 주의·초과 상태, 데이터 없는 달, 예산 덮어쓰기 |
| `CsvTest` (4) | export 조건 필수 + 왕복(쉼표, 태그 포함), 줄 번호 리포트, strict 롤백, 최소 스키마 헤더(대문자·추가 열·id 무시) |
| `AtomicWriteTest` (2) | 임시 파일 잔여물 없음, 손상 줄 번호 보고 |
| `BackupRecurringTest` (2) | 백업/복원 + pre-restore, 월 1회 생성·말일 보정·반복 태그 |
| `FormatterTest` (2) | 한글 폭 계산, 혼합 폭 정렬 |
| `InteractiveAddTest` (4) | 대화형 순서, id 출력, 잘못된 값 재입력, 미등록 카테고리 등록 제안, 입력 없음(EOF) 처리 |
| `CliExitCodeTest` (6) | `-`/`--` 동일 동작, 모든 계층의 `-help`, 종료 코드 0/1/2/3, 스택트레이스 부재, 데이터 없음 메시지 |

- 대화형 입력 테스트는 `unittest.mock.patch("builtins.input", ...)` 으로 답을 순서대로 주입하고, 답이 떨어지면 `EOFError` 를 내어 실제 stdin 종료와 같게 만든다
- 정적 검사: `pyright budget_app tests` → 0 errors / `mypy budget_app tests` → Success

---

## 6. 종료 코드 규약

| 코드 | 의미 | 예 |
|---|---|---|
| 0 | 정상 | 모든 성공 명령 |
| 1 | 사용자 입력 오류 | 잘못된 날짜·금액, 인자 누락, 사용 중 카테고리 삭제, import 성공 0건 |
| 2 | 파일/저장소 오류 | JSONL 손상, CSV 없음·헤더 불일치, strict import 실패, 예상 밖 예외 |
| 3 | 대상 없음 | 없는 거래 ID, 없는 카테고리, 없는 백업명 |
| 130 | 사용자 중단 (Ctrl+C) | — |

- 개발 시 환경변수: `LEDGER_DEBUG=1`(예상 밖 예외의 트레이스백 표시), `LEDGER_TIMING=1`(명령 실행 시간 표시)
