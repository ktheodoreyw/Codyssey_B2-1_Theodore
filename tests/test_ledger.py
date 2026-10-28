"""
tests/test_ledger.py — 핵심 동작 단위 테스트 (표준 unittest, 외부 의존성 없음)

실행:
    python -m unittest -v            # 프로젝트 루트에서
    python -m unittest tests.test_ledger.AtomicWriteTest -v

각 테스트는 임시 디렉터리에 독립된 LedgerApp 을 만들어 실제 data/ 를 건드리지 않는다.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

# 프로젝트 루트를 import 경로에 추가 (tests/ 에서 직접 실행해도 되도록)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledger import cli                                  # noqa: E402
from ledger.csv_io import parse_csv                     # noqa: E402
from ledger.errors import (                             # noqa: E402
    CategoryInUseError, NotFoundError, StorageError, ValidationError,
)
from ledger.formatters import display_width, render_table  # noqa: E402
from ledger.models import Transaction                   # noqa: E402
from ledger.services import LedgerApp, TX_FILE          # noqa: E402
from ledger.storage import atomic_write_text            # noqa: E402


class _Base(unittest.TestCase):
    """임시 디렉터리 + LedgerApp 을 준비하는 공통 설정."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.app = LedgerApp(self.root / "data", self.root / "backups")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def add(self, date="2026-10-01", type="expense", category="식비", amount=1000, memo="") -> Transaction:
        return self.app.transactions.add(date, type, category, amount, memo)


class ModelValidationTest(unittest.TestCase):
    def test_invalid_date_rejected(self):
        with self.assertRaises(ValidationError):
            Transaction(id=1, date="2026-02-30", type="expense", category="식비", amount=100)

    def test_invalid_type_rejected(self):
        with self.assertRaises(ValidationError):
            Transaction(id=1, date="2026-02-01", type="spend", category="식비", amount=100)

    def test_amount_accepts_comma_and_rejects_float(self):
        tx = Transaction(id=1, date="2026-02-01", type="expense", category="식비", amount="12,000")
        self.assertEqual(tx.amount, 12000)
        with self.assertRaises(ValidationError):
            Transaction(id=1, date="2026-02-01", type="expense", category="식비", amount="12.5")

    def test_signed_amount(self):
        inc = Transaction(id=1, date="2026-02-01", type="income", category="급여", amount=10)
        exp = Transaction(id=2, date="2026-02-01", type="expense", category="식비", amount=4)
        self.assertEqual(inc.signed_amount + exp.signed_amount, 6)


class CrudTest(_Base):
    def test_add_persists_as_jsonl_line(self):
        tx = self.add(memo="점심")
        lines = (self.root / "data" / TX_FILE).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["memo"], "점심")
        self.assertEqual(tx.id, 1)

    def test_data_survives_new_app_instance(self):
        """프로그램 재실행 후에도 데이터 유지 — 같은 디렉터리로 새 인스턴스를 만들어 확인."""
        self.add(); self.add(amount=2000)
        self.app.budgets.set("2026-10", "식비", 5000)
        again = LedgerApp(self.root / "data", self.root / "backups")
        self.assertEqual(len(list(again.transactions.iter_filtered())), 2)
        self.assertEqual(len(again.budgets.list("2026-10")), 1)

    def test_update_changes_only_given_fields(self):
        tx = self.add(memo="원본")
        new = self.app.transactions.update(tx.id, amount=777)
        self.assertEqual((new.amount, new.memo, new.date), (777, "원본", "2026-10-01"))

    def test_update_without_fields_rejected(self):
        tx = self.add()
        with self.assertRaises(ValidationError):
            self.app.transactions.update(tx.id)

    def test_delete_keeps_others(self):
        a = self.add(); b = self.add(amount=2000)
        self.app.transactions.delete(a.id)
        ids = [t.id for t in self.app.transactions.iter_filtered()]
        self.assertEqual(ids, [b.id])

    def test_delete_missing_raises_not_found(self):
        with self.assertRaises(NotFoundError):
            self.app.transactions.delete(42)

    def test_add_unknown_category_rejected(self):
        with self.assertRaises(NotFoundError):
            self.add(category="없음")


class GeneratorTest(_Base):
    def test_iter_filtered_is_lazy(self):
        """제너레이터는 호출 즉시 아무것도 읽지 않고, next() 때 처음 한 건만 꺼낸다."""
        for i in range(5):
            self.add(amount=1000 + i)
        gen = self.app.transactions.iter_filtered()
        self.assertTrue(hasattr(gen, "__next__"))
        first = next(gen)
        self.assertEqual(first.amount, 1000)   # 나머지 4건은 아직 읽지 않음

    def test_filters(self):
        self.add(date="2026-09-30", memo="커피")
        self.add(date="2026-10-01", memo="커피 라떼", amount=5000)
        self.add(date="2026-10-02", type="income", category="급여", amount=100000)
        oct_ = list(self.app.transactions.iter_filtered(month="2026-10"))
        self.assertEqual(len(oct_), 2)
        kw = list(self.app.transactions.iter_filtered(keyword="커피", min_amount=2000))
        self.assertEqual([t.amount for t in kw], [5000])


class CategoryTest(_Base):
    def test_remove_in_use_without_reassign_fails(self):
        self.add(category="식비")
        with self.assertRaises(CategoryInUseError):
            self.app.categories.remove("식비")

    def test_remove_with_reassign_moves_everything(self):
        self.add(category="식비"); self.add(category="식비")
        self.app.budgets.set("2026-10", "식비", 10000)
        self.app.recurring.add(1, "expense", "식비", 100, "x")
        info = self.app.categories.remove("식비", reassign_to="기타")
        self.assertEqual(info, {"transactions": 2, "budgets": 1, "recurring": 1})
        self.assertFalse(self.app.categories.exists("식비"))
        self.assertTrue(all(t.category == "기타" for t in self.app.transactions.iter_filtered()))
        self.assertEqual(self.app.budgets.list(), [])


class BudgetSummaryTest(_Base):
    def test_summary_budget_status(self):
        self.app.budgets.set("2026-10", "식비", 10000)
        self.add(amount=8500)    # 85% → 주의
        s = self.app.transactions.summarize("2026-10", self.app.budgets.list("2026-10"))
        self.assertEqual(s.budget_rows[0].status, "주의")
        self.add(amount=2000)    # 105% → 초과
        s = self.app.transactions.summarize("2026-10", self.app.budgets.list("2026-10"))
        self.assertEqual(s.budget_rows[0].status, "초과")
        self.assertEqual(s.net, -10500)

    def test_budget_set_overwrites_same_key(self):
        self.app.budgets.set("2026-10", "식비", 1000)
        self.app.budgets.set("2026-10", "식비", 2000)
        self.assertEqual([b.amount for b in self.app.budgets.list()], [2000])


class CsvTest(_Base):
    def _write(self, text: str) -> Path:
        p = self.root / "in.csv"
        p.write_text(text, encoding="utf-8")
        return p

    def test_export_then_import_roundtrip(self):
        self.add(memo="쉼표, 포함")
        out = self.root / "out.csv"
        self.assertEqual(self.app.transactions.export(out), 1)
        self.assertTrue(out.read_text(encoding="utf-8").startswith("id,date,type,category,amount,memo"))
        r = self.app.transactions.import_csv(out)
        self.assertEqual((len(r.valid), len(r.errors)), (1, 0))
        self.assertEqual(len(list(self.app.transactions.iter_filtered())), 2)

    def test_partial_import_reports_broken_rows_with_line_numbers(self):
        p = self._write(
            "id,date,type,category,amount,memo\n"
            ",2026-10-01,expense,식비,100,ok\n"
            ",2026-13-01,expense,식비,100,bad date\n"
            ",2026-10-01,expense,식비,abc,bad amount\n"
            ",2026-10-01,expense,미등록,100,unknown cat\n"
        )
        r = self.app.transactions.import_csv(p, mode="partial")
        self.assertEqual(len(r.valid), 1)
        self.assertEqual([e.line_no for e in r.errors], [3, 4, 5])
        self.assertEqual(len(list(self.app.transactions.iter_filtered())), 1)

    def test_strict_import_writes_nothing_on_error(self):
        p = self._write("id,date,type,category,amount,memo\n,2026-10-01,expense,식비,100,ok\n,x,y,z,w,v\n")
        with self.assertRaises(StorageError):
            self.app.transactions.import_csv(p, mode="strict")
        self.assertEqual(len(list(self.app.transactions.iter_filtered())), 0)

    def test_wrong_header_rejected(self):
        p = self._write("date,amount\n2026-10-01,100\n")
        with self.assertRaises(StorageError):
            parse_csv(p, iter(range(1, 100)))


class AtomicWriteTest(unittest.TestCase):
    def test_no_temp_file_left_and_content_replaced(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "x.jsonl"
            atomic_write_text(target, "a\n")
            atomic_write_text(target, "b\n")
            self.assertEqual(target.read_text(), "b\n")
            self.assertEqual([p.name for p in Path(d).iterdir()], ["x.jsonl"])  # .tmp 잔여물 없음

    def test_corrupted_line_reports_line_number(self):
        with tempfile.TemporaryDirectory() as d:
            app = LedgerApp(Path(d) / "data")
            app.transactions.add("2026-10-01", "expense", "식비", 1)
            with (Path(d) / "data" / TX_FILE).open("a", encoding="utf-8") as f:
                f.write('{"id": 2, "date": ')   # 잘린 줄
            with self.assertRaises(StorageError) as ctx:
                list(app.transactions.iter_filtered())
            self.assertIn("2번째 줄", ctx.exception.message)


class BackupRecurringTest(_Base):
    def test_backup_and_restore(self):
        self.add(memo="keep")
        snap = self.app.backup.create("t")
        self.app.transactions.delete(1)
        self.assertEqual(len(list(self.app.transactions.iter_filtered())), 0)
        self.app.backup.restore(snap.name)
        self.assertEqual([t.memo for t in self.app.transactions.iter_filtered()], ["keep"])
        self.assertTrue(any("pre-restore" in n for n, _, _ in self.app.backup.list()))

    def test_recurring_apply_once_per_month_and_clamps_day(self):
        self.app.recurring.add(31, "expense", "주거", 500, "월세")
        created = self.app.recurring.apply("2026-02")
        self.assertEqual(created[0].date, "2026-02-28")
        self.assertEqual(self.app.recurring.apply("2026-02"), [])   # 중복 생성 없음
        self.assertEqual(len(self.app.recurring.apply("2026-03")), 1)


class FormatterTest(unittest.TestCase):
    def test_korean_width(self):
        self.assertEqual(display_width("식비"), 4)
        self.assertEqual(display_width("ab"), 2)

    def test_columns_align_with_mixed_width(self):
        table = render_table(("카테고리", "금액"), [("식비", 1000), ("transport", 25)], ("left", "right"))
        lines = table.splitlines()
        self.assertTrue(all(display_width(ln) == display_width(lines[0]) for ln in lines))
        self.assertIn("1,000", table)


class CliExitCodeTest(unittest.TestCase):
    """main() 이 반환하는 종료 코드와 스택트레이스 부재를 확인."""

    def _run(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["--data-dir", str(self.data), *argv])
        return code, out.getvalue(), err.getvalue()

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.data = Path(self._tmp.name) / "data"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_success_is_zero(self):
        code, out, _ = self._run("add", "--date", "2026-10-01", "--type", "expense",
                                 "--category", "식비", "--amount", "100")
        self.assertEqual(code, 0)
        self.assertIn("추가됨", out)

    def test_validation_error_is_one_without_traceback(self):
        code, _, err = self._run("add", "--date", "bad", "--type", "expense", "--category", "식비", "--amount", "1")
        self.assertEqual(code, 1)
        self.assertIn("[오류]", err)
        self.assertIn("[힌트]", err)
        self.assertNotIn("Traceback", err)

    def test_missing_file_is_two(self):
        code, _, err = self._run("import", "--file", "no.csv")
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", err)

    def test_not_found_is_three(self):
        code, _, _ = self._run("delete", "7")
        self.assertEqual(code, 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
