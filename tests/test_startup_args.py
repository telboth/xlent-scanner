from xlent_scanner.app import _startup_file_from_argv


def test_startup_file_from_argv_ignores_macos_psn_argument(tmp_path):
    doc = tmp_path / "test.pdf"
    doc.write_text("x", encoding="utf-8")

    assert _startup_file_from_argv(["XLENTScanner", "-psn_0_12345", str(doc)]) == str(doc)


def test_startup_file_from_argv_ignores_options_and_missing_paths(tmp_path):
    doc = tmp_path / "test.docx"
    doc.write_text("x", encoding="utf-8")

    argv = ["XLENTScanner", "--some-option", "not-a-file.pdf", "-x", str(doc)]

    assert _startup_file_from_argv(argv) == str(doc)


def test_startup_file_from_argv_returns_none_without_existing_file():
    assert _startup_file_from_argv(["XLENTScanner", "-psn_0_12345", "missing.pdf"]) is None


def test_startup_file_from_argv_accepts_macos_file_url(tmp_path):
    doc = tmp_path / "space name.pdf"
    doc.write_text("x", encoding="utf-8")

    assert _startup_file_from_argv(["XLENTScanner", doc.as_uri()]) == str(doc)
