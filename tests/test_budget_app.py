"""
tests/test_budget_app.py — 핵심 동작 단위 테스트 (표준 unittest, 외부 의존성 없음)

실행:
    python -m unittest -v                     # 프로젝트 루트에서
    python -m unittest tests.test_budget_app.InteractiveAddTest -v

- 각 테스트는 임시 디렉터리에 독립된 LedgerApp 을 만들어 실제 data/ 를 건드리지 않는다.
- 대화형 입력은 builtins.input 을 가짜 함수로 바꿔 끼워(mock) 사람이 없어도 검증한다.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from budget_app import cli                                  # noqa: E402
from budget_app.csv_io import parse_csv                     # noqa: E402
from budget_app.errors import (                             # noqa: E402
    CategoryInUseError, LedgerError, NotFoundError, StorageError, ValidationError,
)
from budget_app.formatters import display_width, render_table  # noqa: E402
from budget_app.models import Transaction, parse_tags, validate_amount  # noqa: E402
from budget_app.services import LedgerApp, TX_FILE          # noqa: E402
from budget_app.storage import atomic_write_text            # noqa: E402


class _Base(unittest.TestCase):
    """임시 디렉터리 + LedgerApp 을 준비하는 공통 설정."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.app = LedgerApp(self.root / "data", self.root / "backups")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def add(self, date="2026-10-01", type="expense", category="식비", amount=1000, memo="", tags=None):
        return self.app.transactions.add(date, type, category, amount, memo, tags)


# ---------------------------------------------------------------------------
class ModelValidationTest(unittest.TestCase):
    def test_invalid_date_rejected(self):
        with self.assertRaises(ValidationError):
            Transaction(id=1, date="2026-02-30", type="expense", category="식비", amount=100)

    def test_invalid_type_rejected_and_aliases_accepted(self):
        with self.assertRaises(ValidationError):
            Transaction(id=1, date="2026-02-01", type="spend", category="식비", amount=100)
        for alias in ("1", "수입", "i", "INCOME"):
            self.assertEqual(Transaction(id=1, date="2026-02-01", type=alias, category="식비", amount=1).type, "income")

    def test_amount_accepts_comma_and_rejects_float_zero(self):
        # 모델의 amount 는 int 로 선언돼 있으므로, 문자열 입력 변환은 validate_amount 로 검사한다
        self.assertEqual(validate_amount("12,000"), 12000)
        for bad in ("12.5", 0, -5, "abc"):
            with self.assertRaises(ValidationError):
                validate_amount(bad)

    def test_tags_parse(self):
        self.assertEqual(parse_tags(" a, b ,,a "), ["a", "b"])
        self.assertEqual(parse_tags(["x", "y"]), ["x", "y"])
        self.assertEqual(parse_tags(None), [])
        with self.assertRaises(ValidationError):
            parse_tags("x" * 21)

    def test_csv_row_has_spec_columns(self):
        tx = Transaction(id=1, date="2026-02-01", type="expense", category="식비", amount=1, tags=["a", "b"])
        self.assertEqual(list(tx.to_csv_row()), ["date", "type", "category", "amount", "memo", "tags"])
        self.assertEqual(tx.to_csv_row()["tags"], "a,b")


# ---------------------------------------------------------------------------
class CrudTest(_Base):
    def test_first_run_initializes_categories(self):
        self.assertTrue(self.app.initialized)
        self.assertIn("식비", self.app.categories.names())
        again = LedgerApp(self.root / "data", self.root / "backups")
        self.assertFalse(again.initialized)   # 두 번째 실행부터는 안내 없음

    def test_add_persists_as_jsonl_line_with_tags(self):
        tx = self.add(memo="점심", tags="회사,점심")
        lines = (self.root / "data" / TX_FILE).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["tags"], ["회사", "점심"])
        self.assertEqual(tx.id, 1)

    def test_data_survives_new_app_instance(self):
        self.add(); self.add(amount=2000)
        self.app.budgets.set("2026-10", 5000)
        again = LedgerApp(self.root / "data", self.root / "backups")
        self.assertEqual(len(list(again.transactions.iter_filtered())), 2)
        budget = again.budgets.get("2026-10")
        self.assertIsNotNone(budget)
        assert budget is not None   # 정적 검사기용 좁히기
        self.assertEqual(budget.amount, 5000)

    def test_update_changes_only_given_fields(self):
        tx = self.add(memo="원본", tags="a")
        new = self.app.transactions.update(tx.id, amount=777)
        self.assertEqual((new.amount, new.memo, new.date, new.tags), (777, "원본", "2026-10-01", ["a"]))
        cleared = self.app.transactions.update(tx.id, tags="")
        self.assertEqual(cleared.tags, [])

    def test_update_without_fields_rejected(self):
        tx = self.add()
        with self.assertRaises(ValidationError):
            self.app.transactions.update(tx.id)

    def test_delete_keeps_others_and_missing_raises(self):
        a = self.add(); b = self.add(amount=2000)
        self.app.transactions.delete(a.id)
        self.assertEqual([t.id for t in self.app.transactions.iter_filtered()], [b.id])
        with self.assertRaises(NotFoundError):
            self.app.transactions.delete(42)

    def test_add_unknown_category_rejected(self):
        with self.assertRaises(NotFoundError):
            self.add(category="없음")


# ---------------------------------------------------------------------------
class StreamingTest(_Base):
    def test_iter_filtered_is_lazy(self):
        for i in range(5):
            self.add(amount=1000 + i)
        gen = self.app.transactions.iter_filtered()
        self.assertTrue(hasattr(gen, "__next__"))
        self.assertEqual(next(gen).amount, 1000)   # 나머지 4건은 아직 읽지 않음

    def test_filters_including_tag(self):
        self.add(date="2026-09-30", memo="커피", tags="카페")
        self.add(date="2026-10-01", memo="커피 라떼", amount=5000)
        self.add(date="2026-10-02", type="income", category="급여", amount=100000, tags="월급")
        self.assertEqual(len(list(self.app.transactions.iter_filtered(month="2026-10"))), 2)
        self.assertEqual([t.amount for t in self.app.transactions.iter_filtered(keyword="커피")], [1000, 5000])
        self.assertEqual([t.amount for t in self.app.transactions.iter_filtered(tag="월급")], [100000])

    def test_newest_first_with_limit(self):
        self.add(date="2026-10-01"); self.add(date="2026-10-03"); self.add(date="2026-10-02"); self.add(date="2026-10-03")
        top2 = self.app.transactions.newest_first(self.app.transactions.iter_filtered(), limit=2)
        self.assertEqual([(t.date, t.id) for t in top2], [("2026-10-03", 4), ("2026-10-03", 2)])
        all_ = self.app.transactions.newest_first(self.app.transactions.iter_filtered(), limit=0)
        self.assertEqual([t.id for t in all_], [4, 2, 3, 1])


# ---------------------------------------------------------------------------
class CategoryTest(_Base):
    def test_remove_in_use_without_reassign_fails(self):
        self.add(category="식비")
        with self.assertRaises(CategoryInUseError):
            self.app.categories.remove("식비")

    def test_remove_with_reassign_moves_everything(self):
        self.add(category="식비"); self.add(category="식비")
        self.app.recurring.add(1, "expense", "식비", 100, "x")
        info = self.app.categories.remove("식비", reassign_to="기타")
        self.assertEqual(info, {"transactions": 2, "recurring": 1})
        self.assertFalse(self.app.categories.exists("식비"))
        self.assertTrue(all(t.category == "기타" for t in self.app.transactions.iter_filtered()))


# ---------------------------------------------------------------------------
class BudgetSummaryTest(_Base):
    def test_summary_values_top_and_budget_status(self):
        self.app.budgets.set("2026-10", 10000)
        self.add(amount=8500, category="식비"); self.add(amount=500, category="교통")
        self.add(type="income", category="급여", amount=20000)
        s = self.app.transactions.summarize("2026-10", self.app.budgets.get("2026-10"))
        self.assertEqual((s.income, s.expense, s.balance, s.count), (20000, 9000, 11000, 3))
        self.assertEqual(s.top_categories(1), [("식비", 8500)])
        self.assertEqual(s.budget_status, "주의")          # 90%
        self.add(amount=2000)
        s = self.app.transactions.summarize("2026-10", self.app.budgets.get("2026-10"))
        self.assertEqual(s.budget_status, "초과")

    def test_empty_month_and_budget_overwrite(self):
        s = self.app.transactions.summarize("2026-12", None)
        self.assertEqual(s.count, 0)
        self.app.budgets.set("2026-10", 1000); self.app.budgets.set("2026-10", 2000)
        self.assertEqual([b.amount for b in self.app.budgets.list()], [2000])


# ---------------------------------------------------------------------------
class CsvTest(_Base):
    def _write(self, text: str) -> Path:
        p = self.root / "in.csv"
        p.write_text(text, encoding="utf-8")
        return p

    def test_export_requires_condition_and_roundtrips(self):
        self.add(memo="쉼표, 포함", tags="a,b")
        out = self.root / "out.csv"
        with self.assertRaises(ValidationError):
            self.app.transactions.export(out)
        self.assertEqual(self.app.transactions.export(out, month="2026-10"), 1)
        self.assertTrue(out.read_text(encoding="utf-8").startswith("date,type,category,amount,memo,tags"))
        r = self.app.transactions.import_csv(out)
        self.assertEqual((len(r.valid), len(r.errors)), (1, 0))
        txs = list(self.app.transactions.iter_filtered())
        self.assertEqual(len(txs), 2)
        self.assertEqual(txs[1].tags, ["a", "b"])

    def test_partial_import_reports_broken_rows_with_line_numbers(self):
        p = self._write(
            "date,type,category,amount,memo,tags\n"
            "2026-10-01,expense,식비,100,ok,\n"
            "2026-13-01,expense,식비,100,bad date,\n"
            "2026-10-01,expense,식비,abc,bad amount,\n"
            "2026-10-01,expense,미등록,100,unknown cat,\n"
        )
        r = self.app.transactions.import_csv(p, mode="partial")
        self.assertEqual(len(r.valid), 1)
        self.assertEqual([e.line_no for e in r.errors], [3, 4, 5])
        self.assertEqual(len(list(self.app.transactions.iter_filtered())), 1)

    def test_strict_import_writes_nothing_on_error(self):
        p = self._write("date,type,category,amount,memo,tags\n2026-10-01,expense,식비,100,ok,\nx,y,z,w,v,\n")
        with self.assertRaises(StorageError):
            self.app.transactions.import_csv(p, mode="strict")
        self.assertEqual(len(list(self.app.transactions.iter_filtered())), 0)

    def test_header_minimum_schema(self):
        with self.assertRaises(StorageError):          # 필수 열 누락
            parse_csv(self._write("date,amount\n2026-10-01,100\n"), iter(range(1, 100)))
        # 필수 4열만 있고 대문자/추가 열이 있어도 통과
        r = parse_csv(self._write("ID,Date,Type,Category,Amount,비고\n9,2026-10-01,expense,식비,100,x\n"),
                      iter(range(1, 100)))
        self.assertEqual(len(r.valid), 1)
        self.assertEqual(r.valid[0][1].id, 1)          # CSV 의 id 9 는 무시


# ---------------------------------------------------------------------------
class AtomicWriteTest(unittest.TestCase):
    def test_no_temp_file_left_and_content_replaced(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "x.jsonl"
            atomic_write_text(target, "a\n"); atomic_write_text(target, "b\n")
            self.assertEqual(target.read_text(), "b\n")
            self.assertEqual([p.name for p in Path(d).iterdir()], ["x.jsonl"])

    def test_corrupted_line_reports_line_number(self):
        with tempfile.TemporaryDirectory() as d:
            app = LedgerApp(Path(d) / "data")
            app.transactions.add("2026-10-01", "expense", "식비", 1)
            with (Path(d) / "data" / TX_FILE).open("a", encoding="utf-8") as f:
                f.write('{"id": 2, "date": ')
            with self.assertRaises(StorageError) as ctx:
                list(app.transactions.iter_filtered())
            self.assertIn("2번째 줄", ctx.exception.message)


# ---------------------------------------------------------------------------
class BackupRecurringTest(_Base):
    def test_backup_and_restore(self):
        self.add(memo="keep")
        snap = self.app.backup.create("t")
        self.app.transactions.delete(1)
        self.app.backup.restore(snap.name)
        self.assertEqual([t.memo for t in self.app.transactions.iter_filtered()], ["keep"])
        self.assertTrue(any("pre-restore" in n for n, _, _ in self.app.backup.list()))

    def test_recurring_apply_once_per_month_and_clamps_day(self):
        self.app.recurring.add(31, "expense", "주거", 500, "월세", "고정비")
        created = self.app.recurring.apply("2026-02")
        self.assertEqual(created[0].date, "2026-02-28")
        self.assertEqual(created[0].tags, ["고정비", "반복#1"])
        self.assertEqual(self.app.recurring.apply("2026-02"), [])
        self.assertEqual(len(self.app.recurring.apply("2026-03")), 1)


# ---------------------------------------------------------------------------
class FormatterTest(unittest.TestCase):
    def test_korean_width(self):
        self.assertEqual(display_width("식비"), 4)
        self.assertEqual(display_width("ab"), 2)

    def test_columns_align_with_mixed_width(self):
        table = render_table(("카테고리", "금액"), [("식비", 1000), ("transport", 25)], ("left", "right"))
        lines = table.splitlines()
        self.assertTrue(all(display_width(ln) == display_width(lines[0]) for ln in lines))
        self.assertIn("1,000", table)


# ---------------------------------------------------------------------------
class _CliBase(unittest.TestCase):
    """cli.main() 을 직접 호출해 종료 코드·출력·스택트레이스 부재를 확인."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.data = Path(self._tmp.name) / "data"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_cli(self, *argv: str, inputs: list[str] | None = None) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        answers = iter(inputs or [])

        def fake_input(_prompt: str = "") -> str:
            try:
                return next(answers)
            except StopIteration:
                raise EOFError from None   # 준비한 답이 떨어지면 실제 stdin 종료(EOF)처럼 동작

        with redirect_stdout(out), redirect_stderr(err), patch("builtins.input", fake_input):
            code = cli.main(["-data-dir", str(self.data), *argv])
        return code, out.getvalue(), err.getvalue()


class InteractiveAddTest(_CliBase):
    def test_add_prompts_in_order_and_prints_id(self):
        # 날짜(Enter=오늘), 유형, 카테고리 번호, 금액, 메모, 태그
        code, out, _ = self.run_cli("add", inputs=["", "2", "1", "12,000", "점심", "회사,점심"])
        self.assertEqual(code, 0)
        self.assertIn("저장 완료: 거래 id=1", out)
        self.assertIn("[회사, 점심]", out)

    def test_add_reprompts_on_invalid_value(self):
        code, out, err = self.run_cli("add", inputs=["2026-02-30", "2026-10-01", "income", "급여", "abc", "100", "", ""])
        self.assertEqual(code, 0)
        self.assertIn("존재하지 않는 날짜", err)
        self.assertIn("금액은 정수여야", err)
        self.assertIn("거래 id=1", out)

    def test_add_offers_to_register_unknown_category(self):
        code, out, _ = self.run_cli("add", inputs=["2026-10-01", "2", "여행", "y", "100", "", ""])
        self.assertEqual(code, 0)
        self.assertIn("여행", out)
        code, out, _ = self.run_cli("category", "list")
        self.assertIn("여행", out)

    def test_add_without_input_fails_cleanly(self):
        code, _, err = self.run_cli("add", inputs=[])   # 입력이 없으면 EOF
        self.assertEqual(code, 1)
        self.assertIn("대화형 입력이 중단", err)
        self.assertNotIn("Traceback", err)


class CliExitCodeTest(_CliBase):
    def test_success_is_zero_and_single_double_dash_both_work(self):
        self.run_cli("add", inputs=["2026-10-01", "2", "1", "100", "", ""])
        c1, out1, _ = self.run_cli("list", "-limit", "1")
        c2, out2, _ = self.run_cli("list", "--limit", "1")
        self.assertEqual((c1, c2), (0, 0))
        self.assertEqual(out1, out2)

    def test_help_option_on_every_level(self):
        for argv in (["-help"], ["summary", "-help"], ["budget", "set", "--help"]):
            with self.assertRaises(SystemExit) as ctx:
                self.run_cli(*argv)
            self.assertEqual(ctx.exception.code, 0)

    def test_validation_error_is_one_without_traceback(self):
        code, _, err = self.run_cli("export", "-out", "x.csv")
        self.assertEqual(code, 1)
        self.assertIn("[오류]", err); self.assertIn("[힌트]", err); self.assertNotIn("Traceback", err)

    def test_missing_file_is_two(self):
        code, _, err = self.run_cli("import", "-from", "no.csv")
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", err)

    def test_not_found_is_three(self):
        self.assertEqual(self.run_cli("delete", "-id", "7")[0], 3)
        self.assertEqual(self.run_cli("update", "--id", "7", "-amount", "1")[0], 3)

    def test_summary_empty_month_message(self):
        code, out, _ = self.run_cli("summary", "-month", "2026-12")
        self.assertEqual(code, 0)
        self.assertIn("데이터 없음", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
