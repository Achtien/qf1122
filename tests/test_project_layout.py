"""Relocated source checkout smoke tests; no credentials or production data."""
from pathlib import Path
from contextlib import closing
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from get_data import get_daily


class LayoutTests(unittest.TestCase):
    def test_history_start_is_stable_across_computers(self):
        args = get_daily.build_parser().parse_args([])
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(args.start_date, "20041122")
        self.assertEqual(args.db, root / "data/daily_data/daily_data.db")
        self.assertEqual(args.token_file, root / ".tushare_token")

    def test_relocated_checkout_runs_without_temporary_or_pythonpath(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="relocated project ") as directory:
            relocated = Path(directory).resolve()
            shutil.copytree(root / "src", relocated / "src",
                            ignore=shutil.ignore_patterns("temporary", "__pycache__", "*.egg-info"))
            wrapper = relocated / "data/daily_data/update.py"
            wrapper.parent.mkdir(parents=True)
            shutil.copy2(root / "data/daily_data/update.py", wrapper)
            env = dict(os.environ)
            env.pop("PYTHONPATH", None)
            env.pop("TUSHARE_TOKEN", None)
            def run(*args):
                result = subprocess.run([sys.executable, *map(str, args)], cwd=relocated.parent,
                                        env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result
            run(relocated / "src/get_data/get_daily.py", "--init-only")
            database = relocated / "data/daily_data/daily_data.db"
            self.assertTrue(database.is_file())
            with closing(sqlite3.connect(database)) as db:
                tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertTrue({'daily', 'stock_name_history', 'stock_suspensions', 'market_calendar', 'tradable_stock'} <= tables)
            for name in ('get_daily.py', 'add_tag.py', 'daily_tables.py', 'update.py'):
                run(relocated / 'src/get_data' / name, '--help')
            run(wrapper, '--help')
            run('-c', "import sys; from pathlib import Path; "
                f"sys.path.insert(0, {str(relocated / 'src')!r}); "
                "import get_data.stock_tags, backtest; "
                f"assert Path(get_data.stock_tags.__file__).is_relative_to({str(relocated)!r}); "
                f"assert Path(backtest.__file__).is_relative_to({str(relocated)!r})")


if __name__ == '__main__':
    unittest.main()
