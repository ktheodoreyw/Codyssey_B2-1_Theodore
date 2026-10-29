"""
budget_app — JSONL 기반 개인 가계부 CLI 패키지

실행: python -m budget_app <command> [options]

모듈 구성 (의존 방향: cli → prompt/services → storage/csv_io → models → errors)
  errors.py      : 예외 계층 + 종료 코드
  models.py      : 데이터 모델 + 값 검증 규칙
  storage.py     : JSONL 저장소(제너레이터 읽기, 원자적 쓰기), 백업
  csv_io.py      : CSV 내보내기/가져오기(깨진 행 리포트)
  formatters.py  : 테이블 정렬 출력
  decorators.py  : 오류 처리/로그/시간 측정 데코레이터
  prompt.py      : 대화형 입력(input) 헬퍼
  services.py    : 업무 규칙(거래·카테고리·예산·반복)
  cli.py         : argparse 명령 정의 + 출력
"""

__version__ = "2.0.0"
