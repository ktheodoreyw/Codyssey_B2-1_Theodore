# B2-1 나만의 용돈 기입장 프로그램 만들기

> Python 표준 라이브러리만으로 구현한 파일 입출력 기반의 가계부 콘솔 프로그램

---

## 목차

1. [프로젝트 개요]
2. [프로그램 구조]
3. [저장 포맷 선택: JSONL (근거)]
4. [구현 기능 13개 — 구현 방법과 실행 예시]
5. [테스트]
6. [종료 코드 규약]

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
ledger-cli/
├── main.py                 # 프로그램 시작 및 종료
├── ledger/                 # 패키지
│   ├── errors.py           # 오류 유형 및 종료 코드 정의
│   ├── models.py           # 데이터(거래, 카테고리, 예산, 반복 규칙) 형태 규정 및 검증 규칙
│   ├── storage.py          # JSONL 저장 및 가져오기
│   ├── csv_io.py           # CSV 저장 및 가져오기
│   ├── formatters.py       # 출력 포맷 테이블 정렬
│   ├── decorators.py       # 공통 기능에 대한 데코레이터 모음(3종)
│   ├── services.py         # 담당 대상(거래, 카테고리, 예산, 반복 내역, 조립)별 업무 규칙
│   └── cli.py              # 명령(입력) 해석 및 기능 호출을 통한 결과 출력
├── tests/test_ledger.py    # 기능 테스트 모듈(총 31개)
├── samples/                # 테스트 샘플 저장소
│   ├── sample_import.csv   # 정상 CSV 샘플
│   └── broken_import.csv   # 비정상 CSV 샘플(데이터 일부(행)가 깨져 있는 CSV)
├── data/                   # 파일 저장소
│   ├── transactions.jsonl  # 거래
│   ├── categories.jsonl    # 카테고리
│   ├── budgets.jsonl       # 예산
│   ├── recurring.jsonl     # 반복 규칙
│   └── ledger.log          # 명령 실행 로그
├── backups/                # 백업 결과
├── .vscode/                # 디버그 및 테스트 설정
├── .gitignore
└── requirements.txt
```

### 모듈별 역할
| 모듈 | 역할 |
|---|---|
| `models.py` | 필드 구조, 유효성 규칙 |
| `storage.py` | JSONL 읽기/쓰기/백업 |
| `csv_io.py` | CSV 읽기/쓰기 |
| `services.py` | 가계부 규칙, 서비스 조합 |
| `cli.py` | 명령 해석, 출력 |
| `decorators.py` | 예외 처리, 로그 기록, 실행 시간 측정 |
| `formatters.py` | 화면 폭, 정렬 |

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

---

## 4. 구현 기능

### 기본 기능

#### 4-1. `add`: 거래 추가
- **구현**
  - `TransactionService.add()`로 거래 추가 시 검사를 통과한 거래만 존재할 수 있게 구현
  - 카테고리는 `CategoryService.require()` 로 존재 확인
  - 저장은 `JsonlStore.append()` 
  - 금액은 `3,000,000` 처럼 쉼표 허용, 소수, 0, 음수 거부
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

#### 4-2. `list`: 거래 목록
- **구현**
  - `TransactionService.iter_filtered()` **제너레이터** 가 파일을 한 줄씩 읽으며 조건(월/유형/카테고리)에 맞는 것만 `yield`
  - `--limit N` 이면 N건을 받는 즉시 순회를 멈춰 나머지 파일은 읽지 않음
  - `--sort date|amount` 를 주면 그때만 전체를 메모리에 올려 정렬
  - 출력은 `formatters.render_table()`
- **예시**
```
$ python main.py list --month 2026-10 --type expense --limit 2
ID | 날짜       | 유형 | 카테고리 |   금액 | 메모
---+------------+------+----------+--------+--------------
 2 | 2026-10-02 | 지출 | 식비     | 12,000 | 점심 김치찌개
 3 | 2026-10-02 | 지출 | 교통     |  1,550 | 지하철
(2건 표시)
```

#### 4-3. `search`: 거래 검색
- **구현**
  - `list` 와 같은 제너레이터를 재사용하되 키워드(카테고리 부분일치, 대소문자 무시), 기간(`--from/--to`), 금액 범위(`--min/--max`) 조건을 추가
  - 날짜가 ISO 형식이므로 문자열 비교(`tx.date < date_from`)는 시간 비교 의미
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

#### 4-4. `summary`: 월별/전체 요약 및 예산 사용률
- **구현**
  - `TransactionService.summarize()` 가 제너레이터를 한 번만 순회하며 수입, 지출, 건수, 카테고리별 지출을 동시에 누적
  - 예산은 `BudgetService.list(month)` 결과와 조인해 `BudgetUsage(limit, used)` 생성
  - `ratio`, `status`(정상 / 주의 ≥80% / 초과 >100%) 계산
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

#### 4-5. `export`: CSV 내보내기
- **구현**
  - 스키마 고정: **UTF-8**, 헤더 `id, date, type, category, amount, memo`
  - `csv.DictWriter` + `newline=""` → 쉼표, 줄바꿈이 포함된 메모는 자동으로 `"..."` 처리
  - 제너레이터를 그대로 넘겨 **스트리밍(데이터를 생성하는 대로 실시간으로 조금씩 전송) 기록**
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

#### 4-6. `import`: CSV 가져오기
- **구현**
  - `csv_io.parse_csv()` 가 헤더를 스키마와 정확히 대조(순서, 개수, BOM 제거) → 다르면 `exit 2`
  - 행마다 독립 검증 → `ImportResult(valid=[(줄번호, Transaction)], errors=[(줄번호, 원인, 원본)])`
  - 컬럼 수 초과/부족도 행 단위 오류로 분류 (`DictReader` 의 `None` 키/값 감지)
  - 카테고리 존재 여부는 **업무 규칙** 이므로 `services` 에서 2차 검사
  - 모드: `partial`(기본, 정상 행만 저장 + 리포트) / `strict`(오류 1건이라도 있으면 저장 X)
  - 저장은 `write_all()` **한 번** → 프로그램이 멈춰도 일부 행만 들어간 상태가 생기지 않음
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

#### 4-7. `update`: 거래 수정
- **구현**
  - 지정한 옵션만 교체: `date if date is not None else tx.date` 패턴 → 새 `Transaction` 생성 시 재검증
  - 순서: ① `read_all()` ② 메모리에서 대상 교체 ③ `write_all()`
  - 변경 항목이 하나도 없으면 `exit 1`
- **예시**
```
$ python main.py update 2 --amount 13500 --memo "점심 김치찌개(가격 인상)"
수정 전: #2 2026-10-02 지출 식비 12,000원 점심 김치찌개
수정 후: #2 2026-10-02 지출 식비 13,500원 점심 김치찌개(가격 인상)
```

#### 4-8. `delete`: 거래 삭제
- **구현**
  - 대상을 제외한 나머지를 `write_all()` 로 재기록
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

#### 4-9. `category add / list / remove`: 카테고리 관리
- **구현**
  - 첫 실행 시 `ensure_seed()`가 기본 카테고리 5개(식비, 교통, 주거, 급여, 기타)를 `categories.jsonl`에 생성
  - `add`: 중복 이름 거부 / `list`: 카테고리별 거래 수를 제너레이터로 계산
  - `remove`(사용 중인 카테고리 처리):
    - `--reassign` 없이 사용 중 → `CategoryInUseError` 로 거부(안전 기본값)
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

#### 4-10. `budget set / list`: 예산 설정
- **구현**
  - `Budget(month, category, amount)` 의 `(month, category)` 가 복합 키 → 같은 키로 다시 `set` 하면 덮어씀
  - `budgets.jsonl` 에 저장, `summary` 에서 사용률/초과 여부로 출력
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

#### 4-11. `backup create / list / restore`: 백업
- **구현**
  - `BackupManager.create()`: `backups/YYYYMMDD-HHMMSS[-label]/`에 저장 파일을 `shutil.copy2` 로 복사
  - `list()`: 최신순(백업명, 생성시각, 파일 수)
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

#### 4-12. `recurring add / list / apply / remove`: 반복 내역
- **구현**
  - `RecurringRule(day, type, category, amount, memo, applied_months)`를 `recurring.jsonl`에 저장
  - `apply --month YYYY-MM`: 규칙마다 거래 1건 생성, 31일 규칙이 2월이면 `calendar.monthrange` 로 말일 보정
  - **중복 생성 방지 장치**
    1. `applied_months` 에 해당 월이 있으면 건너뜀
    2. 생성 거래 메모 끝에 `[반복#규칙ID]` 꼬리표를 붙이고, 같은 달에 그 꼬리표가 이미 있으면 건너뜀
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
  - 문제: 한글은 터미널에서 2칸을 차지 → `str.ljust`로 맞추면 열이 어긋남 (`len("식비")==2` 지만 화면 폭 4 차지)
  - 해결: `unicodedata.east_asian_width()`로 글자별 폭(1/2) 합산 → **보이는 폭** 기준으로 패딩(`formatters.display_width`)
  - 숫자 열은 오른쪽 정렬 + 천 단위 쉼표, 문자 열은 왼쪽 정렬, 긴 셀은 `…` 로 잘라 표 유지
  - `list / search / summary / category / budget / backup / recurring / import 리포트` 모든 표가 같은 함수 사용
  - `--format plain` 으로 표 없이 한 줄 출력도 가능
- **예시** — 위 모든 표 참고. 혼합 폭 정렬 테스트(`FormatterTest`)로 모든 행 폭이 동일함을 검증

---

## 5. 테스트

```powershell
python -m unittest -v                      
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

## 6. 종료 코드 규약

| 코드 | 의미 | 예 |
|---|---|---|
| 0 | 정상 | 모든 성공 명령 |
| 1 | 사용자 입력 오류 | 잘못된 날짜·금액, 인자 누락, 사용 중 카테고리 삭제, import 성공 0건 |
| 2 | 파일/저장소 오류 | JSONL 손상, CSV 없음·헤더 불일치, strict import 실패, 예상 밖 예외 |
| 3 | 대상 없음 | 없는 거래 ID, 없는 카테고리, 없는 백업명 |
| 130 | 사용자 중단 (Ctrl+C) | — |

- 개발 시 환경변수: `LEDGER_DEBUG=1`(예상 밖 예외의 트레이스백 표시), `LEDGER_TIMING=1`(명령 실행 시간 표시)
