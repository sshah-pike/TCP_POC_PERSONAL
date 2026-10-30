"""Prompt registry (S6): every AI prompt is one file in prompts/ named <id>.v<version>.txt.

File layout: four header lines (id, version, role, sha256), a line with three dashes, then the prompt text exactly as it is
sent. The sha256 is the hash of the text (UTF-8, LF line ends). The loader recomputes it and refuses a file whose text
does not match its header, so a prompt can only change together with its hash and its version.
"""
import hashlib
import os
from dataclasses import dataclass

from tcp_planner.config import settings

SEPARATOR = "---"
HEADER_KEYS = ("id", "version", "role", "sha256")


class PromptError(ValueError):
    pass


@dataclass(frozen=True)
class Prompt:
    id: str
    version: int
    role: str
    sha256: str
    text: str


def prompt_path(prompt_id, version, directory=None):
    return os.path.join(directory or settings.PROMPTS_DIR, f"{prompt_id}.v{int(version)}.txt")


def text_sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse(raw, path):
    raw = raw.replace("\r\n", "\n")          # a checkout with CRLF must not change the hash
    head, sep, body = raw.partition("\n" + SEPARATOR + "\n")
    if not sep:
        raise PromptError(f"{path}: no '{SEPARATOR}' line after the header")
    meta = {}
    for line in head.split("\n"):
        key, colon, value = line.partition(":")
        if not colon or key.strip() not in HEADER_KEYS or key.strip() in meta:
            raise PromptError(f"{path}: bad header line {line!r}")
        meta[key.strip()] = value.strip()
    if set(meta) != set(HEADER_KEYS):
        raise PromptError(f"{path}: header needs exactly {', '.join(HEADER_KEYS)}")
    return meta, body


def load_prompt(prompt_id, version, directory=None, expected_sha256=None):
    """Load one prompt version and verify its hash (and, when given, a pinned hash)."""
    path = prompt_path(prompt_id, version, directory)
    if not os.path.isfile(path):
        raise PromptError(f"prompt {prompt_id} version {version} not found: {path}")
    with open(path, "rb") as f:
        meta, body = _parse(f.read().decode("utf-8"), path)
    if meta["id"] != prompt_id or int(meta["version"]) != int(version):
        raise PromptError(f"{path}: header says {meta['id']} v{meta['version']}")
    actual = text_sha256(body)
    if actual != meta["sha256"]:
        raise PromptError(f"{path}: text hash {actual} does not match header {meta['sha256']}")
    if expected_sha256 is not None and actual != expected_sha256:
        raise PromptError(f"{path}: text hash {actual} does not match pinned {expected_sha256}")
    return Prompt(prompt_id, int(version), meta["role"], actual, body)


def list_prompts(directory=None):
    """(id, version) of every prompt file in the folder, sorted."""
    d = directory or settings.PROMPTS_DIR
    out = []
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if name.endswith(".txt") and ".v" in name:
            pid, _, ver = name[:-4].rpartition(".v")
            if ver.isdigit():
                out.append((pid, int(ver)))
    return out
