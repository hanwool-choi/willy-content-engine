import pytest

from willy.images import UnsupportedImageError, retag, sniff


def test_sniff_trusts_bytes_not_extension(tmp_path):
    """확장자가 거짓말을 해도 내용으로 판단한다."""
    path = tmp_path / "liar.jpg"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"body")

    assert sniff(path) == ("image/png", ".png")


def test_sniff_detects_jpeg(tmp_path):
    path = tmp_path / "a.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0body")

    assert sniff(path) == ("image/jpeg", ".jpg")


def test_sniff_detects_webp(tmp_path):
    path = tmp_path / "a.jpg"
    path.write_bytes(b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"body")

    assert sniff(path) == ("image/webp", ".webp")


def test_sniff_rejects_non_image(tmp_path):
    path = tmp_path / "a.jpg"
    path.write_bytes(b"<!DOCTYPE html><html>oops</html>")

    with pytest.raises(UnsupportedImageError):
        sniff(path)


def test_retag_renames_to_real_format(tmp_path):
    path = tmp_path / "shot.jpg"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"body")

    corrected = retag(path)

    assert corrected.suffix == ".png"
    assert corrected.exists()
    assert not path.exists()
