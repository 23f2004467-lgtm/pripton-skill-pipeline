"""CLI argparse-correctness smoke tests.

These verify that each subcommand's argparse wiring accepts the documented
arguments and that help text renders. The underlying pipeline/stats/cache
functions are mocked at the cli module boundary — these are parser-correctness
tests, not behavior tests. Behavior is covered by the stage/pipeline test
modules and the live Step 21 runs.
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from skillpipeline.cli import main


def run_cli(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> int:
    """Invoke main() with a patched sys.argv (program name prepended)."""
    monkeypatch.setattr("sys.argv", ["skillpipeline", *argv])
    return main()


def assert_help_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    expected: str,
) -> None:
    """`--help` should print usage containing `expected` and exit with code 0."""
    monkeypatch.setattr("sys.argv", ["skillpipeline", *argv])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    assert expected in capsys.readouterr().out


def test_no_command_prints_help(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Bare invocation prints top-level help and exits 0 without error."""
    assert run_cli(monkeypatch, []) == 0
    out = capsys.readouterr().out
    assert "Pripton Skill Pipeline" in out
    for sub in ("run", "review", "resume", "stats", "cache"):
        assert sub in out


def test_top_level_help(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    assert_help_exits_zero(monkeypatch, capsys, ["--help"], "Pripton Skill Pipeline")


def test_run_subcommand(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    with patch("skillpipeline.cli.pipeline_run", return_value="runs/run_x/report.html") as mock_run:
        assert run_cli(monkeypatch, ["run", "samples/clean_roadmap.md"]) == 0
    mock_run.assert_called_once_with(
        "samples/clean_roadmap.md", always_review=False, no_cache=False
    )
    assert_help_exits_zero(monkeypatch, capsys, ["run", "--help"], "Path to input markdown file")


def test_run_flags_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    """--always-review and --no-cache parse and pass through to the orchestrator."""
    with patch("skillpipeline.cli.pipeline_run", return_value="runs/run_x/report.html") as mock_run:
        assert run_cli(monkeypatch, ["run", "doc.md", "--always-review", "--no-cache"]) == 0
    mock_run.assert_called_once_with("doc.md", always_review=True, no_cache=True)


def test_review_subcommand(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    with patch("skillpipeline.cli.review", return_value="opened") as mock_review:
        assert run_cli(monkeypatch, ["review", "run_abc"]) == 0
    mock_review.assert_called_once_with("run_abc")
    assert_help_exits_zero(monkeypatch, capsys, ["review", "--help"], "Thread ID to review")


def test_resume_subcommand(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    with patch("skillpipeline.cli.resume", return_value="resumed") as mock_resume:
        assert run_cli(monkeypatch, ["resume", "run_abc"]) == 0
    mock_resume.assert_called_once_with("run_abc")
    assert_help_exits_zero(monkeypatch, capsys, ["resume", "--help"], "Thread ID to resume")


def test_stats_subcommand(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    with patch("skillpipeline.cli.stats") as mock_stats:
        assert run_cli(monkeypatch, ["stats"]) == 0
        assert run_cli(monkeypatch, ["stats", "--json"]) == 0
    assert mock_stats.call_args_list[0].kwargs == {"json_output": False}
    assert mock_stats.call_args_list[1].kwargs == {"json_output": True}
    assert_help_exits_zero(monkeypatch, capsys, ["stats", "--help"], "Output JSON instead of Rich table")


def _fake_cache() -> Mock:
    cache = Mock()
    cache.list_entries.return_value = []
    return cache


def test_cache_list_subcommand(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    cache = _fake_cache()
    with patch("skillpipeline.cli.get_cache", return_value=cache):
        assert run_cli(monkeypatch, ["cache", "list"]) == 0
    cache.list_entries.assert_called_once()
    assert_help_exits_zero(monkeypatch, capsys, ["cache", "--help"], "list")


def test_cache_clear_subcommand(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = _fake_cache()
    with patch("skillpipeline.cli.get_cache", return_value=cache):
        assert run_cli(monkeypatch, ["cache", "clear"]) == 0
    cache.clear.assert_called_once()
