"""Failure signature normalization.

A signature is ``exception type + normalized message + top in-app frames``.
Normalization strips the parts of a message that change between otherwise
identical failures (ids, timings, addresses, line numbers) so they group.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from ci_triage.models import TestResult

# Order matters: specific patterns first, generic numbers last.
_NORMALIZERS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<UUID>"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"), "<TS>"),
    (re.compile(r"\b\d{2}:\d{2}:\d{2}(?:\.\d+)?\b"), "<TIME>"),
    (re.compile(r"\b0x[0-9a-f]+\b", re.I), "<HEX>"),
    (re.compile(r"@[0-9a-f]{6,}\b", re.I), "@<HEX>"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), "<IP>"),
    (re.compile(r"(?:/tmp|/var/folders|/private/var)/[\w./-]+"), "<TMP>"),
    (re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{12,}\b", re.I), "<ID>"),
    (re.compile(r"(?<!\w)-?\d+(?:\.\d+)?(?:ms|s)?\b"), "<N>"),
]

_JAVA_FRAME = re.compile(r"^\s*at (?:[\w.]+/)?([\w$.<>]+)\(([^)]*)\)", re.M)
_PY_FRAME = re.compile(r"^(\S+\.py):\d+: in (\S+)", re.M)

_JAVA_FRAMEWORK = (
    "java.",
    "javax.",
    "jdk.",
    "sun.",
    "org.junit.",
    "org.opentest4j.",
    "org.apache.maven.",
    "org.gradle.",
    "org.mockito.",
    "org.assertj.",
)
_PY_FRAMEWORK = ("site-packages/", "/_pytest/", "/pluggy/", "/lib/python3")


@dataclass(frozen=True)
class Signature:
    exc_type: str
    normalized_message: str
    frames: tuple[str, ...]

    @property
    def id(self) -> str:
        raw = "|".join([self.exc_type, self.normalized_message, *self.frames])
        return hashlib.sha1(raw.encode()).hexdigest()[:10]


def normalize_message(message: str, max_len: int = 200) -> str:
    """Return the first line of ``message`` with volatile tokens replaced."""
    first = message.strip().splitlines()[0] if message.strip() else ""
    for pattern, repl in _NORMALIZERS:
        first = pattern.sub(repl, first)
    return re.sub(r"\s+", " ", first).strip()[:max_len]


def extract_frames(details: str, language: str) -> list[str]:
    """In-app frames, innermost (closest to the throw) first, without line numbers."""
    if language == "java":
        frames = []
        for method, _location in _JAVA_FRAME.findall(details):
            if method.startswith(_JAVA_FRAMEWORK):
                continue
            frames.append(re.sub(r"\$\d+", "", method))  # lambda$foo$0 -> lambda$foo
        return frames
    frames = [
        f"{path}::{func}"
        for path, func in _PY_FRAME.findall(details)
        if not any(marker in path for marker in _PY_FRAMEWORK)
    ]
    return list(reversed(frames))  # Python tracebacks are outermost first


def signature_for(result: TestResult, frame_depth: int = 1) -> Signature:
    frames = extract_frames(result.details, result.language)[:frame_depth]
    return Signature(
        exc_type=result.exc_type or "UnknownFailure",
        normalized_message=normalize_message(result.message),
        frames=tuple(frames),
    )


def is_test_code_frame(frame: str) -> bool:
    if "::" in frame:  # python
        path = frame.split("::")[0]
        name = path.rsplit("/", 1)[-1]
        return (
            path.startswith("tests/")
            or "/tests/" in path
            or name.startswith("test_")
            or name == "conftest.py"
        )
    cls = frame.rsplit(".", 1)[0]
    simple = cls.rsplit(".", 1)[-1]
    return simple.endswith(("Test", "Tests", "IT")) or ".test." in cls


def code_area(frame_or_classname: str) -> str:
    """Rough owner area from a frame or classname, e.g. ``orders/pricing`` or ``api/checkout``."""
    if "::" in frame_or_classname or frame_or_classname.startswith("tests."):
        path = frame_or_classname.split("::")[0].replace(".py", "").replace(".", "/")
        parts = [p.removeprefix("test_") for p in path.split("/") if p != "tests"]
        return "/".join(parts[:2]) or path
    parts = frame_or_classname.split(".")
    pkg = [p for p in parts if p and p[0].islower()]
    if len(pkg) > 2 and pkg[0] in ("com", "org", "io", "net"):
        pkg = pkg[2:]
    return "/".join(pkg[:2])
