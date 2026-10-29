# budget_app — JSONL 기반 개인 가계부 CLI

> Python 표준 라이브러리만으로 구현한 콘솔 가계부.
> 기본 기능 10개 + 보너스 4개(백업 / 반복 내역 / 테이블 정렬 / 저장 원자성) 구현.
> 실행: `python -m budget_app <command> [options]`

---

## 목차

1. [실행 방법](#1-실행-방법)
2. [저장 파일 위치 / 형식](#2-저장-파일-위치--형식)
3. [저장 포맷 선택: JSONL (근거)](#3-저장-포맷-선택-jsonl-근거)
4. [주요 명령 예시 — 기능별 구현 방법과 실행 결과](#4-주요-명령-예시--기능별-구현-방법과-실행-결과)
5. [import/export CSV 스키마](#5-importexport-csv-스키마)
6. [프로젝트 구조](#6-프로젝트-구조)
7. [평가문항 대응 설명](#7-평가문항-대응-설명)
8. [테스트](#8-테스트)
9. [종료 코드 규약](#9-종료-코드-규약)

---

## 1. 실행 방법

### 요구 사항
- Python **3.10 이상** (3.13 에서 검증)
- 외부 패키지 **없음** — `requirements.txt` 는 비어 있음, `pip install` 불필요

### 실행
```powershell
cd budget-app                              # 프로젝트 루트 (budget_app/ 폴더가 보이는 위치)
python -m budget_app -help                 # 전체 명령 목록
python -m budget_app add -help             # 명령별 사용법 (모든 명령·하위 명령에 -help 제공)
python -m budget_app add                   # 대화형으로 거래 추가
python -m budget_app list -limit 5         # 최신순 5건
python -m budget_app summary -month 2026-10
```
- `python main.py <command>` 로도 동일하게 실행됨 (호환용 래퍼)
- 첫 실행 시 `data/` 폴더와 기본 카테고리(식비, 교통, 주거, 급여, 기타)를 자동 생성하고 안내 메시지를 출력 (명세 3-④ **안 A**)

### 입력 방식 (명세 4-①)
| 명령 | 방식 |
|---|---|
| `add` | **대화형** — 날짜 → 유형 → 카테고리 → 금액 → 메모 → 태그 순으로 `input()` 입력. 잘못 넣으면 그 항목만 재입력 |
| `update` | **옵션 기반(안 A) 로 고정** — `update -id <id> [-date] [-type] [-category] [-amount] [-memo] [-tags]` |
| `list` `search` `summary` `budget` `category` `delete` `import` `export` | 옵션 인자 |

### 옵션 표기
- 명세의 리눅스 표준 **단일 대시** (`-help`, `-limit`, `-from`, `-month`) 를 기본으로 사용
- 명세 예시에 섞여 있는 이중 대시 (`--id`, `--month`) 도 **모두 동일하게 동작** (두 표기를 함께 등록)
- `-data-dir <경로>` 로 저장 폴더 변경 가능 (기본 `./data`)

### VS Code → GitHub
```powershell
code .
python -m unittest -v                      # 39개 테스트 통과 확인
git init && git add . && git commit -m "feat: budget_app 가계부 CLI"
git branch -M main
git remote add origin https://github.com/<계정>/<저장소>.git
git push -u origin main
```
- `.gitignore` 가 개인 데이터(`data/*.jsonl`, `backups/*`)와 내보낸 CSV 를 제외
- `.vscode/launch.json` 에 `python -m budget_app` 디버그 구성 포함 (F5)

---

## 2. 저장 파일 위치 / 형식

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

## 3. 저장 포맷 선택: JSONL (근거)

### 결론
- **주 저장소 = JSONL**, **교환 포맷 = CSV** (export / import 전용)

### JSONL 을 선택한 이유
| 관점 | JSONL | CSV |
|---|---|---|
| `add` 비용 | 끝에 한 줄 append → **O(1)**, 전체 재기록 없음 | append 가능하지만 헤더 관리·따옴표 이스케이프 부담 |
| 손상 격리 | 한 줄 = 한 레코드 → 깨진 줄만 번호로 지목 가능 | 메모 안 줄바꿈/쉼표가 다음 행까지 오염시킬 수 있음 |
| 타입 | `int`, `list`(tags, applied_months) 그대로 보존 | 모든 값이 문자열 → 매번 형변환, 목록은 별도 규칙 필요 |
| 스키마 변경 | 필드 추가 시 기존 줄과 공존 (키 없으면 기본값) | 열 추가 시 모든 행·헤더 재작성 |
| 스트리밍 | `for line in f` → `json.loads` → yield 가 자연스러움 | 가능하지만 `csv` 모듈 상태 의존 |
| 사람이 읽기 | 키 이름이 보여 자기설명적 (`"amount": 12000`) | 헤더를 기억해야 함 |
| 엑셀 호환 | 직접 열기 불편 | **우수** → 이 장점은 export 로 확보 |

### 트레이드오프 인정
- 파일 크기: 키 이름이 반복되어 CSV 보다 약 2배 큼 (10만 건 ≈ 12.8 MB) → 개인 가계부 규모에서는 무시 가능
- 엑셀 편집: `export` → 엑셀 → `import` 흐름으로 해결
- 그래서 **CSV 는 버리지 않고 교환 포맷으로 남겼다** (두 포맷의 장점을 역할별로 분리)

---

## 4. 주요 명령 예시 — 기능별 구현 방법과 실행 결과

> 모든 예시는 실제 실행 결과를 붙여 넣은 것 (`[exit=n]` 은 종료 코드).

### 기본 기능 (명세 2장 순서)

#### 4-1. `add` — 거래 추가 (대화형)
- **구현**
  - `prompt.ask_transaction()` 이 `input()` 으로 6개 항목을 순서대로 묻는다. 날짜는 Enter 시 오늘, 유형은 `1/2`, `income/expense`, `수입/지출` 모두 허용, 카테고리는 번호 또는 이름
  - 각 항목의 검증은 `models.validate_*` 함수를 그대로 재사용 → 잘못된 값이면 `[오류]/[힌트]` 출력 후 **그 항목만 재입력** (5회 실패 시 중단)
  - 미등록 카테고리를 입력하면 등록 여부를 물어 바로 등록 가능 (명세 4-④ "안내 후 재입력/등록 유도")
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

#### 4-2. `list` — 거래 목록 (최신순, 스트리밍)
- **구현**
  - `TransactionService.iter_filtered()` **제너레이터**가 파일을 한 줄씩 읽어 조건(`-month`, `-type`, `-category`)에 맞는 것만 `yield`
  - `newest_first(stream, limit)` 가 `heapq.nlargest` 로 스트림을 한 번 훑으며 **상위 limit 건만 메모리에 유지** → 최신순(날짜↓, 같은 날이면 id↓)
  - `-limit` 기본 20, `-limit 0` 은 전체 (이때만 전부 모아 정렬)
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

#### 4-3. `search` — 거래 검색
- **구현**
  - `list` 와 같은 제너레이터에 `-from/-to`(기간), `-category`, `-type`, `-q`(메모 부분일치, 대소문자 무시), `-tag`(태그 정확히 일치) 조건을 추가
  - 날짜가 ISO 형식이므로 문자열 비교(`tx.date < date_from`)가 곧 시간 비교 → 파싱 비용 없음
  - 결과는 최신순, `-limit`(기본 전체) 지원. 조건이 하나도 없으면 안내 후 `exit 1`
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

#### 4-4. `summary` — 월별 요약 + TOP N + 예산 사용률
- **구현**
  - `summarize(month, budget)` 가 제너레이터를 **한 번만** 순회하며 총수입·총지출·건수·카테고리별 지출을 동시에 누적 → `Summary` 객체 반환
  - 잔액 = 총수입 − 총지출, `top_categories(n)` 로 TOP N (`-top`, 기본 5)
  - 거래가 0건이면 **"데이터 없음"** 을 명시 출력 (명세 8)
  - 예산이 있으면 사용률(%)·상태(정상 / 주의 ≥80% / 초과 >100%)·잔여 예산, 초과 시 경고 문구 (명세 9)
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

#### 4-5. `budget set / list` — 월 예산
- **구현**
  - `Budget(month, amount)` — `month` 가 유일 키, 같은 달로 다시 `set` 하면 덮어씀
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

#### 4-6. `category add / list / remove` — 카테고리 관리
- **구현**
  - 첫 실행 시 기본 5개 자동 생성(안 A). `add` 는 중복 거부, `list` 는 카테고리별 거래 수를 제너레이터로 계산
  - `remove` 는 사용 중이면 **삭제를 막고**, `-reassign <대체>` 를 주면 거래·반복규칙을 옮긴 뒤 삭제 (대체 카테고리가 없으면 자동 생성). 카테고리 자체 삭제는 마지막 단계 → 중간 실패 시 재시도 가능
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

#### 4-7. `update` — 거래 수정 (옵션 기반, 안 A 고정 / 저장 원자성 포함)
- **구현**
  - `update -id <id>` 에 바꿀 항목만 옵션으로 지정. 지정하지 않은 항목은 유지, 하나도 없으면 `exit 1`
  - 새 `Transaction` 을 먼저 만들어(`__post_init__` 검증) 통과한 뒤에만 저장 → 잘못된 값이면 파일은 한 바이트도 안 바뀜
  - 저장은 `write_all()` = **임시 파일에 전체 기록 → `flush` + `os.fsync` → `os.replace()`** 로 원자적 교체 (보너스 4). 어느 시점에 죽어도 "완전한 이전 파일" 또는 "완전한 새 파일" 만 존재
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

#### 4-8. `delete` — 거래 삭제 (저장 원자성 포함)
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

#### 4-9. `import` — CSV 가져오기 (깨진 행 처리 포함)
- **구현**
  - `import -from <csv>`. `csv_io.parse_csv()` 가 헤더에 필수 4열(date, type, category, amount)이 있는지 확인(순서 무관, 대소문자·BOM 무시, 추가 열 무시) → 없으면 `exit 2`
  - 행마다 독립 검증 → `ImportResult(valid=[(줄번호, Transaction)], errors=[(줄번호, 원인, 원본)])`. 컬럼 수 초과/부족도 행 단위 오류
  - 카테고리 존재 여부는 **업무 규칙**이므로 `services` 에서 2차 검사 (`-create-categories` 로 자동 등록 가능)
  - `-mode partial`(기본): 정상 행만 저장 + 실패 행 리포트 / `-mode strict`: 오류 1건이라도 있으면 저장 0건
  - 저장은 `write_all()` **한 번** → 절반만 들어가는 상태 없음. CSV 의 `id` 열은 무시하고 새로 발급
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

#### 4-10. `export` — CSV 내보내기
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

#### 4-11. `backup` — 백업 / 복원
- **구현**
  - `backup` (= `backup create [-label]`): `backups/YYYYMMDD-HHMMSS[-label]/` 에 저장 파일 4개를 `shutil.copy2` 로 복사 — **타임스탬프 포함** 백업
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

#### 4-12. `recurring add / list / apply / remove` — 반복 내역
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
  - 문제: 한글은 터미널에서 2칸을 차지 → `str.ljust` 로 맞추면 열이 어긋남 (`len("식비")==2` 지만 화면 폭 4)
  - 해결: `unicodedata.east_asian_width()` 로 글자별 폭(1/2) 합산 → **보이는 폭** 기준으로 패딩 (`formatters.display_width`)
  - 숫자 열은 오른쪽 정렬 + 천 단위 쉼표, 문자 열은 왼쪽 정렬, 긴 셀은 `…` 로 잘라 표 유지. 외부 라이브러리 없음
  - `list / search / summary / category / budget / backup / recurring / import 리포트` 모든 표가 같은 `render_table()` 사용. `-format plain` 으로 표 없이 한 줄 출력도 가능
- **예시** — 위 모든 표 참고. `FormatterTest` 가 한글·영문 혼합 행의 폭이 모두 같음을 검증

#### 4-14. 저장 원자성 강화 — 4-7 / 4-8 / 4-9 / 4-11 에 포함
- `storage.atomic_write_text()`: 같은 폴더에 임시 파일 → 전체 기록 → `fsync` → `os.replace()` (rename) 로 교체. 실패 시 임시 파일 삭제. `AtomicWriteTest` 로 검증

---

## 5. import/export CSV 스키마

| column | required | 설명 |
|---|---|---|
| `date` | Y | `YYYY-MM-DD` (실제 존재하는 날짜) |
| `type` | Y | `income` / `expense` |
| `category` | Y | 등록된 카테고리 (미등록이면 행 오류, `-create-categories` 로 자동 등록 가능) |
| `amount` | Y | 양수 정수 (`12,000` 처럼 쉼표 포함 시 `"..."` 로 감싸야 함) |
| `memo` | N | 문자열 |
| `tags` | N | 쉼표(,) 구분 문자열 → 쉼표가 있으므로 `"a,b"` 처럼 따옴표로 감쌈 (csv 모듈이 자동 처리) |

- 공통: **UTF-8** (BOM 없음 권장, 있으면 제거해서 읽음), **헤더 포함**, 구분자 쉼표, 줄바꿈 LF/CRLF 모두 허용
- export 는 위 6열을 이 순서로 기록 (`Transaction.CSV_COLUMNS` 가 단일 출처)
- import 는 필수 4열이 헤더에 있으면 허용 — 순서 무관, 대소문자 무시, 스키마 밖의 열(예: `id`, `비고`)은 무시
- UTF-8 이 아닌 파일은 "Excel: 다른 이름으로 저장 > CSV UTF-8" 힌트와 함께 `exit 2`
- 샘플: `samples/sample_import.csv`(정상), `samples/broken_import.csv`(깨진 행 5종)

---

## 6. 프로젝트 구조

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

### 모듈 간 책임 (의존 방향: cli → prompt / services → storage / csv_io → models → errors)
| 모듈 | 아는 것 | 모르는 것 |
|---|---|---|
| `models.py` | 필드 구조, 값 하나로 판단하는 검증 규칙 | 파일, 콘솔, 다른 데이터와의 관계 |
| `storage.py` | 파일 읽기/쓰기/백업 | 레코드의 의미, 업무 규칙 |
| `csv_io.py` | CSV 스키마, 행 단위 형식 검증 | 카테고리 존재 여부 (업무 규칙) |
| `services.py` | 가계부 규칙, 서비스 조합 | print, input, argparse |
| `prompt.py` | 사용자에게 묻고 재입력 받기 | 저장, 업무 규칙 |
| `cli.py` | 명령 해석, 출력 | 파일 포맷 |
| `decorators.py` | 예외→메시지, 로그, 시간 | 명령 내용 |
| `formatters.py` | 화면 폭, 정렬 | 데이터 의미 |

---

## 7. 평가문항 대응 설명

### 항목 1 — 기능 동작

| 평가 요구 | 구현 위치 | 확인 방법 |
|---|---|---|
| add/list/search/summary/export/import/update/delete 동작 | `services.TransactionService`, `cli.cmd_*`, `prompt` | 4-1 ~ 4-10 예시 |
| 재실행 후 데이터 유지, 저장 파일 3개 이상 | `data/` 에 **4개** JSONL | `CrudTest.test_data_survives_new_app_instance` |
| category add/list/remove, 사용 중 카테고리 처리 | `CategoryService.remove(reassign_to)` | 4-6 예시, `CategoryTest` |
| budget set 저장, summary 에서 사용률/초과 | `BudgetService.set`, `Summary.budget_ratio / budget_status` | 4-4 예시 (111.3% 초과 경고) |
| import/export CSV 스키마 (UTF-8, 헤더, 컬럼) | 5장, `csv_io.py` | 4-9, 4-10 예시, `CsvTest` |
| 오류 시 스택트레이스 없이 메시지 + 힌트 | `decorators.handle_errors`, `cli.FriendlyParser.error`, `prompt` | `CliExitCodeTest` 에서 `"Traceback" not in stderr` 검증 |
| 오류 시 종료 코드 ≠ 0 | 예외 클래스의 `exit_code` → `__main__.py` 의 `sys.exit` | 9장 표 |

- 종료 코드 확인: Windows `echo %ERRORLEVEL%` (cmd) / `$LASTEXITCODE` (PowerShell), macOS/Linux `echo $?`

### 항목 2 — 모듈·클래스 책임 / 안전한 update·delete

#### 코드를 9개 모듈로 나눈 기준 — "어떻게"
- **변경 이유가 다른 것은 다른 파일에** 두었다
  - 저장 포맷을 JSONL → SQLite 로 바꾸고 싶다 → `storage.py` 만 교체
  - 대화형 질문 순서를 바꾸고 싶다 → `prompt.py` 만 수정
  - 예산 "주의" 기준을 80% → 90% 로 바꾸고 싶다 → `services.Summary.budget_status` 한 줄
- **의존 방향을 한쪽으로만** 흐르게 했다: `cli → prompt/services → (storage, csv_io) → models → errors`. 아래 계층은 위 계층을 import 하지 않음 → 순환 참조 없음, 각 계층을 독립 테스트 가능
- **횡단 관심사**(오류 처리·로그·시간 측정) 는 `decorators.py` 로 뽑아 12개 핸들러에 동일하게 적용

#### 클래스 책임 경계 — "어떻게" 정했는가 (2개 이상)
| 클래스 | 소유하는 것 | 하지 않는 것 | 경계를 그은 이유 |
|---|---|---|---|
| `JsonlStore[T]` (storage) | 한 파일 ↔ 한 모델 리스트의 읽기/추가/원자적 교체 | 레코드 내용 해석, 업무 규칙 | 제네릭 1개로 파일 4개를 모두 처리 → 중복 제거 |
| `TransactionService` | 거래 CRUD·검색·최신순 정렬·집계·CSV 교환 | 콘솔 입출력, 파일 포맷 | 출력을 모르므로 테스트가 print 를 가로챌 필요 없음 |
| `CategoryService` | 카테고리 CRUD, "사용 중" 판정, 재할당 삭제 | 거래 자체의 검증 | 삭제가 거래·반복규칙 파일을 함께 건드리므로 그 조정 책임을 한 곳에 모음 |
| `BudgetService` / `RecurringService` | 각자의 파일과 규칙 | 서로의 데이터 | 반복 규칙 생성은 `TransactionService.add` 를 **호출** 해 거래 규칙을 재사용 |
| `LedgerApp` | 저장소·서비스 조립, 초기화 여부 | 업무 로직 | `data_dir` 하나만 바꾸면 테스트용 임시 가계부가 됨 |
| `BackupManager` | 스냅샷 생성·목록·복원 | 레코드 해석 | 파일 단위 복사만 하므로 모델이 바뀌어도 영향 없음 |

#### 파일 기반 update/delete 를 "어떻게" 안전하게 처리했는가
1. **전체 읽기 → 메모리 수정 → 전체 쓰기** 를 택했다 (파일 중간을 제자리 수정하지 않음). JSONL 은 줄 길이가 가변이라 in-place 수정은 뒤쪽 줄을 모두 밀어야 하고, 그 중간에 죽으면 복구 불가
2. 전체 쓰기는 **`atomic_write_text`** 로만 수행: 같은 디렉터리에 `tempfile.mkstemp` → 내용 기록 → `flush` → `os.fsync` → **`os.replace`**. `os.replace` 는 POSIX/Windows 모두에서 원자적 rename → 독자는 항상 완전한 파일만 본다. 예외 시 임시 파일 삭제 (`AtomicWriteTest`)
3. **검증을 쓰기 전에** 모두 끝낸다: `update` 는 새 `Transaction` 을 먼저 만들어(`__post_init__` 검증) 통과한 뒤에만 `write_all`
4. 다중 파일을 건드리는 `category remove` 는 **실패해도 재시도 가능한 순서** 로 기록 (거래 → 규칙 → 카테고리 삭제는 마지막). `import -create-categories` 도 거래 저장 **후** 카테고리 등록
5. 대상이 없으면 쓰기 자체를 하지 않고 `NotFoundError(exit 3)`
6. 추가 안전망: `backup` 수동 스냅샷, `restore` 시 자동 `pre-restore` 백업

### 항목 3 — 제너레이터 / 데코레이터 / 타입 힌트

#### list/search 를 제너레이터로 스트리밍 — "어떻게" 구현, "왜" 유리한가
- **구현 (3단 파이프라인 + 고정 크기 힙)**
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
  def newest_first(txs, limit):    # ④ 상위 limit 건만 유지하며 최신순
      return heapq.nlargest(limit, txs, key=lambda t: t.sort_key)
  ```
  - 명세의 "최신순" 은 모든 레코드를 봐야 결정되므로 읽기를 건너뛸 수는 없다. 대신 `heapq.nlargest` 가 스트림을 한 번 훑으며 **크기 limit 의 힙만** 유지하므로 메모리가 파일 크기와 무관하다
- **왜 유리한가 (실측, 10만 건 12.8 MB)**
  | 명령 | 시간 | 최대 메모리 |
  |---|---|---|
  | `list -limit 20` (스트리밍 + 힙) | 479 ms | **18 MB** (인터프리터 기본치 수준) |
  | `list -limit 0` (전체 materialize + 정렬 + 10만 행 표) | 2,910 ms | **127 MB** |
  | `summary -month 2026-10` | 433 ms | 상수 (누적 변수만 유지) |
  - 리스트로 다 읽는 방식은 "20건만 보고 싶어도" 10만 건을 전부 객체로 들고 있어야 한다
  - 같은 제너레이터를 `list / search / summary / export / usage_count / recurring apply` 가 공유 → 필터 로직 중복 없음
  - 트레이드오프: 전체 정렬이 필요한 `-limit 0` 은 이점이 없으므로 사용자가 명시적으로 선택하게 두었다

#### 데코레이터로 분리한 공통 기능 — 무엇이며 "왜" 필요했는가
| 데코레이터 | 하는 일 | 분리하지 않았다면 |
|---|---|---|
| `@handle_errors` | `LedgerError` → `[오류]/[힌트]` 2줄 + 종료 코드 반환, 예상 밖 예외는 `exit 2` (`LEDGER_DEBUG=1` 이면 트레이스백) | 12개 핸들러마다 같은 `try/except` 12벌, 메시지 형식이 조금씩 달라짐 |
| `@log_action(path)` | 명령명·시각·성공/실패코드를 `data/ledger.log` 에 기록 | 로그 한 줄 추가하려고 12곳 수정 |
| `@timed` | `LEDGER_TIMING=1` 일 때 실행 시간을 stderr 로 출력 | 성능 실험용 코드가 업무 로직에 섞임 |
- **적용 순서가 의미를 가진다**
  ```python
  @log_action(LOG_PATH)   # 바깥: handle_errors 가 돌려준 종료코드까지 기록 (실패도 남음)
  @handle_errors          # 중간: 예외를 종료코드로 변환
  @timed                  # 안쪽: 순수 실행 시간만 측정
  def cmd_add(app, a): ...
  ```
  - 처음엔 `handle_errors` 를 바깥에 두었더니 실패한 명령이 로그에 남지 않았다 → 순서를 바꿔 해결 (트러블슈팅)
- `functools.wraps` 로 원본 이름을 유지 → 로그에 `cmd_add` 가 정확히 찍힘

#### 타입 힌트의 이점 — 실제 코드로 "어떻게" 확인했고 "왜" 도움이 되는가
- **정적 검사 결과**: `pyright budget_app tests` → 0 errors, `mypy budget_app tests` → Success. 실행 없이 11개 파일의 입출력 계약이 맞는지 확인됨
- **`Literal["income", "expense"]` (models.TxType)**: `"expens"` 같은 오타를 Pylance 가 즉시 빨간줄로 표시
- **`JsonlStore[Transaction]` (Generic + TypeVar)**: `store.iter_all()` 의 반환을 IDE 가 `Iterator[Transaction]` 으로 추론 → `tx.` 입력 시 `amount, tags…` 자동완성
- **`ParamSpec` / `TypeVar` (decorators)**: 데코레이터를 씌워도 `cmd_add(app, a)` 의 인자·반환 타입이 그대로 유지
- **`Protocol` (storage.Serializable)**: `to_dict()` 만 있으면 어떤 모델이든 저장소에 넣을 수 있다는 계약을 상속 없이 표현
- **트러블슈팅 사례 — `Sequence` vs `list`**: `csv_io._check_header(fieldnames: list[str] | None, ...)` 에 `csv.DictReader.fieldnames` 를 넘기자 pyright 가 `"Sequence[str] | None" is not assignable to "list[str] | None"` 오류를 냈다. 표준 타입 정의(typeshed)가 `fieldnames` 를 `Sequence[str] | None` 으로 선언하기 때문이다. 함수는 순회만 하므로 매개변수를 `Sequence[str] | None` 으로 넓혀 해결 — "함수는 필요한 최소 능력만 요구하는 넓은 타입으로 받는다" 는 원칙의 예. 실행에는 문제가 없었지만 타입 검사가 **계약의 불일치**를 먼저 드러냈다
- **`Budget | None` 반환**: `budgets.get(month)` 가 `None` 일 수 있음을 타입이 강제해, `summary` 에서 예산 없는 달 처리를 빠뜨릴 수 없게 했다

### 항목 4 — 포맷 비교 / 10만 건 병목 / 깨진 CSV

#### JSONL vs CSV — 3장 참조 (요약)
- 주 저장소는 **append O(1), 줄 단위 손상 격리, 타입(list 포함)·스키마 유연성, 스트리밍 친화** 때문에 JSONL
- CSV 는 엑셀 호환이라는 고유 장점이 있어 **버리지 않고 교환 포맷** 으로 역할 분리

#### 거래 10만 건 — 현재 구조의 병목과 개선안 (실측 기반)
| 연산 | 10만 건 실측 | 병목 원인 | 개선안 |
|---|---|---|---|
| `list -limit 20` | 479 ms / 18 MB | 전체 스캔 O(n): `json.loads` 10만 번 (메모리는 상수) | ① 월별 파일 분할(`2026-10.jsonl`) ② 파일을 뒤에서부터 읽는 역방향 제너레이터(최근 추가분이 곧 최신인 경우) |
| `search`, `summary` | ~430~470 ms | 전체 스캔 O(n) | 월별 분할 → 월 조회는 1/12 만 읽음, 또는 월→오프셋 인덱스 파일 |
| `add` | ~450 ms | **`next_id()` 가 최대 ID 를 찾기 위해 전체 스캔** — append 자체는 O(1) | `meta.jsonl` 에 마지막 ID 캐시 또는 파일 끝 1줄만 역방향으로 읽기 → O(1) |
| `update` / `delete` | ~1.1~1.3 s | 전체 읽기 + 전체 재기록 O(n) 12.8 MB | ① 삭제 표시(tombstone) 줄 append + 주기적 compaction ② 월별 분할로 재기록 범위 축소 |
| `category list` | 카테고리 수 × O(n) | 카테고리마다 전체 스캔 | 한 번 스캔으로 `Counter` 집계 |
| 그 이상 (100만 건~) | — | 파일 기반 한계 | **SQLite** 로 교체 — `storage.py` 만 바꾸면 됨 (인덱스·트랜잭션 내장) |

- 설계상 이미 확보한 것: 저장소가 `JsonlStore` 한 클래스에 캡슐화되어 있어 위 개선은 서비스·CLI 코드를 건드리지 않고 적용 가능

#### import CSV 에 깨진 행이 섞였을 때 — 사용자 신뢰를 지키는 처리
- **원칙: 조용히 버리지도, 전부 거부하지도 않는다 — 사용자가 결과를 정확히 알고 선택하게 한다**
- **부분 성공 (기본 `partial`)**: 정상 행은 저장, 깨진 행은 **줄 번호 + 원인 + 원본** 표로 리포트 → 그 줄만 고쳐 다시 가져오면 됨. 저장은 `write_all` 1회(원자적) → "일부만 반영된 뒤 죽는" 상태 없음. 성공 0건이면 `exit 1`
- **롤백 (`-mode strict`)**: 오류가 1건이라도 있으면 파일을 **전혀 건드리지 않고** `exit 2` → 배치/자동화에서 "전부 아니면 무" 보장
- **리포트 설계**: 헤더에 필수 열이 없으면 파일 단위 오류로 즉시 중단 / 컬럼 수 초과·부족, 잘못된 날짜·유형·금액, 미등록 카테고리를 **각각 다른 문장** 으로 지목 / CSV 의 `id` 는 무시하고 새로 발급 → 기존 거래 덮어쓰기 사고 차단 / 인코딩이 UTF-8 이 아니면 Excel 저장 방법까지 안내
- 4-9 예시의 7행 CSV 로 재현 가능 (`samples/broken_import.csv`), `CsvTest` 4개로 검증

---

## 8. 테스트

```powershell
python -m unittest -v                                   # 39개
python -m unittest tests.test_budget_app.InteractiveAddTest -v
```
| 테스트 클래스 | 검증 내용 |
|---|---|
| `ModelValidationTest` (5) | 날짜/유형(별칭 포함)/금액 검증, 태그 파싱, CSV 열 순서 |
| `CrudTest` (7) | 첫 실행 초기화, JSONL 한 줄 저장(tags 포함), 재실행 후 유지, 부분 update·태그 제거, delete, 없는 ID/카테고리 |
| `StreamingTest` (3) | 지연 평가(next 1회), 월·키워드·태그 필터, 최신순 + limit(힙) |
| `CategoryTest` (2) | 사용 중 삭제 거부, `-reassign` 시 거래·규칙 이동 |
| `BudgetSummaryTest` (2) | 총수입/총지출/잔액/TOP N, 주의·초과 상태, 데이터 없는 달, 예산 덮어쓰기 |
| `CsvTest` (4) | export 조건 필수 + 왕복(쉼표·태그 포함), 줄 번호 리포트, strict 롤백, 최소 스키마 헤더(대문자·추가 열·id 무시) |
| `AtomicWriteTest` (2) | 임시 파일 잔여물 없음, 손상 줄 번호 보고 |
| `BackupRecurringTest` (2) | 백업/복원 + pre-restore, 월 1회 생성·말일 보정·반복 태그 |
| `FormatterTest` (2) | 한글 폭 계산, 혼합 폭 정렬 |
| `InteractiveAddTest` (4) | 대화형 순서·id 출력, 잘못된 값 재입력, 미등록 카테고리 등록 제안, 입력 없음(EOF) 처리 |
| `CliExitCodeTest` (6) | `-`/`--` 동일 동작, 모든 계층의 `-help`, 종료 코드 0/1/2/3, 스택트레이스 부재, 데이터 없음 메시지 |

- 대화형 입력 테스트는 `unittest.mock.patch("builtins.input", ...)` 으로 답을 순서대로 주입하고, 답이 떨어지면 `EOFError` 를 내어 실제 stdin 종료와 같게 만든다
- 정적 검사: `pyright budget_app tests` → 0 errors / `mypy budget_app tests` → Success

---

## 9. 종료 코드 규약

| 코드 | 의미 | 예 |
|---|---|---|
| 0 | 정상 | 모든 성공 명령, `-help` |
| 1 | 사용자 입력 오류 | 잘못된 날짜·금액, 옵션 누락, export 조건 없음, 사용 중 카테고리 삭제, 대화형 입력 중단, import 성공 0건 |
| 2 | 파일/저장소 오류 | JSONL 손상, CSV 없음·필수 열 누락·인코딩, strict import 실패, 예상 밖 예외 |
| 3 | 대상 없음 | 없는 거래 ID, 없는 카테고리, 없는 백업명 |
| 130 | 사용자 중단 (Ctrl+C) | 대화형 입력 중 취소 |

- 개발 시 환경변수: `LEDGER_DEBUG=1` (예상 밖 예외의 트레이스백 표시), `LEDGER_TIMING=1` (명령 실행 시간 표시)
