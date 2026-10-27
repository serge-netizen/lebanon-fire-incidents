import pytest

from crawler.cli import main


def test_dry_run_passes(capsys):
    assert main(["--dry-run"]) == 0
    assert "dry run complete" in capsys.readouterr().out


def test_backfill_needs_to_know_which_machine_runs_it():
    with pytest.raises(SystemExit):
        main(["backfill"])
