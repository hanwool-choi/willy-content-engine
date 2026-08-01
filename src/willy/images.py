"""이미지 포맷 판별. 확장자가 아니라 실제 바이트로 판단한다."""
from __future__ import annotations

from pathlib import Path

# Claude 비전이 받는 포맷만 지원한다.
_MAGIC: tuple[tuple[bytes, str, str], ...] = (
    (b"\xff\xd8", "image/jpeg", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"GIF87a", "image/gif", ".gif"),
    (b"GIF89a", "image/gif", ".gif"),
)


class UnsupportedImageError(ValueError):
    """Claude 비전이 받지 않는 포맷."""


def sniff(path: Path) -> tuple[str, str]:
    """(media_type, 권장 확장자). 파일 이름이 아니라 내용으로 판단한다."""
    head = path.read_bytes()[:16]
    for magic, media_type, suffix in _MAGIC:
        if head.startswith(magic):
            return media_type, suffix
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp", ".webp"
    raise UnsupportedImageError(f"지원하지 않는 이미지 형식입니다: {path.name}")


def retag(path: Path) -> Path:
    """실제 포맷에 맞게 확장자를 교정한다. 이미 맞으면 그대로 둔다."""
    _media_type, suffix = sniff(path)
    if path.suffix == suffix:
        return path
    corrected = path.with_suffix(suffix)
    path.rename(corrected)
    return corrected
