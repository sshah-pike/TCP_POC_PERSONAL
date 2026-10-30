"""Prompt registry (S6 commit 1): files in prompts/, hash in the header, loader verifies, pins on each prompt."""
import os

import pytest

from tcp_planner.ai import call1
from tcp_planner.ai import prompt_registry as pr
from tcp_planner.config import settings
from tcp_planner.contracts import sha256_hex

# Version 1 of the call 1 prompts: no wording change from the nine recorded calls.
SYSTEM_V1 = "5e731eab10a7455ac1ace58f3f30520bc0fb0dc2d0aa4eb397cd1b57bed7266b"
USER_V1 = "81b8f01912963d536b1c1b14d702f0abd6bcc062f512522ad3729f49bcbef988"
COMBINED_V1 = "58a344b4f526c55c965b35f80d9c8d78d222932fdbda2e80b1f606ce2550ad6f"       # system NUL user, as pinned since STOP 2
GRANITE_REQUEST_V1 = "720ac0e1898533f5bfafd6623ec6c9e3797d2b5f5a0338fb85da84124fe48fc3"


def test_each_v1_prompt_hash_is_pinned():
    assert pr.load_prompt("call1_system", 1).sha256 == SYSTEM_V1
    assert pr.load_prompt("call1_user", 1).sha256 == USER_V1


def test_the_combined_hash_is_the_one_before_the_registry():
    s, u = call1.load_prompts()
    assert sha256_hex("\x00".join([s.text, u.text])) == COMBINED_V1
    assert call1.SYSTEM == s.text and call1.INSTRUCTIONS == u.text


def test_the_granite_request_prompt_hash_is_unchanged():
    import io
    from PIL import Image
    from tcp_planner.imagery.prepare import resize_for_model
    buf = io.BytesIO(); Image.new("RGB", (1280, 1280), (90, 120, 60)).save(buf, "JPEG")      # the text depends on size and scale only
    sent, rec = resize_for_model(buf.getvalue(), 1280, 0.448139)                              # Granite P32: 1280 px, 0.448139 m/px
    req = call1.build_request(sent, rec)
    text = dict(req["parts"])["text"]
    assert sha256_hex("\x00".join([req["system"], text])) == GRANITE_REQUEST_V1


def test_every_file_in_the_registry_verifies():
    found = pr.list_prompts()
    assert ("call1_system", 1) in found and ("call1_user", 1) in found
    for pid, ver in found:
        p = pr.load_prompt(pid, ver)
        assert p.sha256 == sha256_hex(p.text) and p.id == pid and p.version == ver


def _write(tmp_path, name, header_hash, body, pid="x", ver=1):
    (tmp_path / name).write_text(f"id: {pid}\nversion: {ver}\nrole: system\nsha256: {header_hash}\n---\n{body}", encoding="utf-8", newline="\n")


def test_a_changed_text_is_refused(tmp_path):
    _write(tmp_path, "x.v1.txt", pr.text_sha256("old text"), "new text")
    with pytest.raises(pr.PromptError, match="does not match header"):
        pr.load_prompt("x", 1, directory=str(tmp_path))


def test_a_pinned_hash_that_differs_is_refused(tmp_path):
    _write(tmp_path, "x.v1.txt", pr.text_sha256("text"), "text")
    assert pr.load_prompt("x", 1, directory=str(tmp_path)).text == "text"
    with pytest.raises(pr.PromptError, match="pinned"):
        pr.load_prompt("x", 1, directory=str(tmp_path), expected_sha256="0" * 64)


def test_a_header_that_names_another_prompt_is_refused(tmp_path):
    _write(tmp_path, "x.v1.txt", pr.text_sha256("t"), "t", pid="y")
    with pytest.raises(pr.PromptError, match="header says"):
        pr.load_prompt("x", 1, directory=str(tmp_path))


def test_a_missing_version_or_bad_header_is_refused(tmp_path):
    with pytest.raises(pr.PromptError, match="not found"):
        pr.load_prompt("x", 2, directory=str(tmp_path))
    (tmp_path / "x.v1.txt").write_text("no header here", encoding="utf-8")
    with pytest.raises(pr.PromptError, match="separator|'---'"):
        pr.load_prompt("x", 1, directory=str(tmp_path))


def test_crlf_line_ends_do_not_change_the_hash(tmp_path):
    body = "line one\nline two"
    raw = f"id: x\nversion: 1\nrole: system\nsha256: {pr.text_sha256(body)}\n---\n{body}".replace("\n", "\r\n")
    (tmp_path / "x.v1.txt").write_bytes(raw.encode("utf-8"))
    assert pr.load_prompt("x", 1, directory=str(tmp_path)).text == body


def test_the_prompt_text_is_not_a_python_literal_in_call1_any_more():
    src = open(call1.__file__, encoding="utf-8").read()
    assert "You are an observation assistant" not in src and "Evidence: at most" not in src


def test_the_prompt_files_are_kept_with_lf_line_ends_by_git():
    attrs = open(os.path.join(settings.PROJECT_ROOT, ".gitattributes"), encoding="utf-8").read()
    assert "prompts/*.txt text eol=lf" in attrs
