from pathlib import Path

from mia_san_miete.cli import main
from mia_san_miete.privacy import load_terms, scan_repo, scan_text

ROOT = Path(__file__).resolve().parent.parent


def test_generic_patterns_flag_real_looking_data_but_not_placeholders():
    # Samples are assembled at runtime so this file itself stays clean under the scanner.
    at = "@"
    text = "\n".join(
        [
            f"mail me at someone{at}gmail.com",
            f"or someone{at}example.test",
            "call +49 170 " + "0" * 7,
            "or 01" + "71 " + "1234567",
            "IBAN DE89 " + "3704 0044 0532 0130 00",
        ]
    )
    kinds = [f.kind for f in scan_text("f.txt", text, [])]
    assert kinds == ["email address", "mobile number", "IBAN"]


def test_private_terms_are_matched_case_insensitively_without_echoing_them():
    findings = scan_text("f.txt", "I work at ACME Corp", ["acme"])
    assert [(f.line, f.kind) for f in findings] == [(1, "private term")]
    assert "acme" not in repr(findings).lower()


def test_terms_file_ignores_comments_and_blanks(tmp_path):
    f = tmp_path / ".private-terms"
    f.write_text("# my terms\n\nAcme\n", encoding="utf-8")
    assert load_terms(f) == ["acme"]
    assert load_terms(tmp_path / "missing") == []


def test_repository_contains_no_generic_private_data():
    # Generic patterns only: the personal terms file is local and may not exist in CI.
    assert scan_repo(ROOT, terms_path=ROOT / "does-not-exist") == []


def test_scan_repo_uses_terms_file(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "a.txt").write_text("hello Acme\n", encoding="utf-8")
    (tmp_path / ".private-terms").write_text("acme\n", encoding="utf-8")
    assert [f.path for f in scan_repo(tmp_path)] == ["a.txt"]
    assert main(["check-private", "--root", str(tmp_path)]) == 1
    (tmp_path / "a.txt").write_text("hello\n", encoding="utf-8")
    assert main(["check-private", "--root", str(tmp_path)]) == 0
