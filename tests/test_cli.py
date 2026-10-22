from crawler.cli import main


def test_dry_run_passes(capsys):
    assert main(["--dry-run"]) == 0
    assert "dry run complete" in capsys.readouterr().out


def test_unbuilt_command_says_so():
    assert main(["backfill"]) == 2
