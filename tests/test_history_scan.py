import subprocess
from pathlib import Path

import pytest

from mia_san_miete.cli import main
from mia_san_miete.privacy import scan_history

EMAIL = "someone" + "@" + "gmail.com"          # assembled so this file itself stays clean
PHONE = "01" + "52 3456789"


def git(root: Path, *args: str, env=None) -> None:
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=t@users.noreply.github.com",
                    *args], check=True, capture_output=True, env=env)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "ok.txt").write_text("nothing private here\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "clean start\n\nCo-Authored-By: Claude <noreply@anthropic.com>")
    return tmp_path


def commit_file(root: Path, name: str, text: str, msg: str) -> None:
    (root / name).write_text(text)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", msg)


def test_a_deleted_file_is_still_found_in_history(repo):
    commit_file(repo, "notes.txt", f"call {PHONE} or write {EMAIL}\nsecret-employer lives here\n", "add notes")
    (repo / "notes.txt").unlink()
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "remove notes")
    (repo / ".private-terms").write_text("secret-employer\n")
    report = scan_history(repo)
    kinds = {(f.where, f.path, f.kind) for f in report.findings}
    assert ("blob", "notes.txt", "mobile number") in kinds
    assert ("blob", "notes.txt", "email address") in kinds
    assert ("blob", "notes.txt", "private term") in kinds
    assert {f.commit for f in report.findings if f.path == "notes.txt"} != {"?"}     # points at a commit
    assert (repo / "notes.txt").exists() is False                                      # clean at HEAD


def test_reports_never_contain_the_matched_text(repo, capsys):
    commit_file(repo, "x.txt", f"{EMAIL} and secret-employer\n", "add")
    (repo / ".private-terms").write_text("secret-employer\n")
    assert main(["check-history", "--root", str(repo)]) == 1
    out = capsys.readouterr()
    text = out.out + out.err
    assert EMAIL not in text and "secret-employer" not in text and "finding(s) in the history" in text


def test_commit_messages_authors_and_ref_names_are_scanned(repo):
    commit_file(repo, "a.txt", "fine\n", f"fix typo, reach me at {EMAIL}")
    git(repo, "branch", "feature-secret-employer")
    env = {"GIT_AUTHOR_NAME": "Real Person", "GIT_AUTHOR_EMAIL": EMAIL, "GIT_COMMITTER_NAME": "Real Person",
           "GIT_COMMITTER_EMAIL": EMAIL, "PATH": __import__("os").environ["PATH"], "HOME": str(repo)}
    (repo / "b.txt").write_text("fine\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "authored"], check=True, env=env)
    (repo / ".private-terms").write_text("secret-employer\nreal person\n")
    where = {f.where for f in scan_history(repo).findings}
    assert {"commit message", "ref name", "author"} <= where


def test_noreply_example_and_placeholder_values_are_not_findings(repo):
    commit_file(repo, "c.txt", "mail me@example.test, call +49 170 0000000\n", "docs")
    report = scan_history(repo)
    assert report.findings == [] and report.commits == 2 and report.refs >= 1


def test_binaries_are_listed_for_manual_review_and_terms_file_in_history_is_flagged(repo):
    (repo / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00binary")
    (repo / ".private-terms").write_text("anything\n")
    git(repo, "add", "-A", "-f")
    git(repo, "commit", "-q", "-m", "oops")
    report = scan_history(repo, terms_path=repo / "nonexistent")
    assert "pic.png" in report.binaries
    assert any(f.kind == "terms file committed" for f in report.findings)


def test_shallow_clone_does_not_pass(repo, tmp_path_factory, capsys):
    commit_file(repo, "d.txt", "x\n", "second")
    clone = tmp_path_factory.mktemp("shallow")
    subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{repo}", str(clone / "c")], check=True,
                   capture_output=True)
    assert scan_history(clone / "c").shallow is True
    assert main(["check-history", "--root", str(clone / "c")]) == 1
    assert "shallow" in capsys.readouterr().err


def test_this_repository_history_is_clean():
    """Generic patterns only (the personal terms file is local). Skipped on shallow checkouts."""
    root = Path(__file__).resolve().parent.parent
    report = scan_history(root, terms_path=root / "does-not-exist")
    if report.shallow:
        pytest.skip("shallow checkout")
    assert report.findings == [], [(f.commit, f.path, f.kind) for f in report.findings]
