from pathlib import Path

from spotigram.ziputil import make_zip_parts


def test_single_small_zip(tmp_path: Path):
    f = tmp_path / "a.txt"
    f.write_text("hello")
    parts = make_zip_parts([f], tmp_path / "out", "mix", max_bytes=10_000)
    assert len(parts) == 1
    assert parts[0].name == "mix.zip"


def test_splits_when_over_max(tmp_path: Path):
    files = []
    for i in range(3):
        p = tmp_path / f"f{i}.bin"
        p.write_bytes(b"x" * 400)
        files.append(p)
    parts = make_zip_parts(files, tmp_path / "out", "mix", max_bytes=500)
    assert len(parts) >= 2
    for part in parts:
        assert part.exists()
        assert part.stat().st_size > 0
