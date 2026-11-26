"""Preparation must finish before build opens a strategy's frozen inputs."""

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from textwrap import dedent
from unittest.mock import patch

from backtest import cli


class PreparationTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.market = self.root / "market.db"
        self.market.write_text("frozen inputs")
        self.strategy = self.root / "strategy.py"
        self.result = self.root / "results" / "run.db"
        self.snapshot = self.enterContext(patch.object(cli, "snapshot", return_value=self.market))
        self.run = self.enterContext(patch.object(
            cli, "run", return_value=(self.result, self.result.with_suffix(".pdf"))
        ))
        self.enterContext(patch("builtins.print"))
        self.enterContext(patch.dict(sys.modules))

    def test_missing_inputs_are_prepared_before_build(self):
        self.strategy.write_text(dedent('''
            from pathlib import Path
            INPUTS = Path(__file__).with_name("inputs.txt")

            def prepare(snapshot_path):
                INPUTS.write_text(Path(snapshot_path).read_text())

            def build():
                return INPUTS.read_text(), "config"
        '''))
        for explicit_snapshot in (False, True):
            with self.subTest(explicit_snapshot=explicit_snapshot):
                self.strategy.with_name("inputs.txt").unlink(missing_ok=True)
                self.snapshot.reset_mock()
                self.run.reset_mock()
                argv = ["run", str(self.strategy)]
                if explicit_snapshot:
                    argv.extend(["--snapshot", str(self.market)])
                cli.main(argv)
                self.run.assert_called_once_with(
                    "frozen inputs", "config", self.market, self.root / "results", resume=None
                )
                self.assertEqual(self.snapshot.call_count, 0 if explicit_snapshot else 1)

    def test_resume_preserves_original_inputs_without_preparation(self):
        self.strategy.with_name("inputs.txt").write_text("original inputs")
        self.strategy.write_text(dedent('''
            from pathlib import Path

            def prepare(snapshot_path):
                raise AssertionError("resume must not refresh inputs")

            def build():
                return Path(__file__).with_name("inputs.txt").read_text(), "config"
        '''))
        cli.main([
            "run", str(self.strategy), "--snapshot", str(self.market), "--resume", str(self.result)
        ])
        self.run.assert_called_once_with(
            "original inputs", "config", self.market, self.root / "results", resume=self.result
        )

    def test_strategy_without_preparation_remains_supported(self):
        self.strategy.write_text('def build():\n    return "strategy", "config"\n')
        cli.main(["run", str(self.strategy), "--snapshot", str(self.market)])
        self.run.assert_called_once_with(
            "strategy", "config", self.market, self.root / "results", resume=None
        )

    def test_failed_preparation_stops_before_build_and_run(self):
        self.strategy.write_text(dedent('''
            def prepare(snapshot_path):
                raise RuntimeError("input download interrupted")

            def build():
                raise AssertionError("build must wait for complete inputs")
        '''))
        with self.assertRaisesRegex(RuntimeError, "input download interrupted"):
            cli.main(["run", str(self.strategy), "--snapshot", str(self.market)])
        self.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
