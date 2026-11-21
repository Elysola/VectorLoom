import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from vectorloom.core import alpha_segments, files_equal, png_rgba


def png(width: int, height: int, pixels: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data))
        )

    rows = b"".join(
        b"\x00" + pixels[y * width * 4 : (y + 1) * width * 4] for y in range(height)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


class CoreTests(unittest.TestCase):
    def test_png_decoder_and_alpha_segments(self) -> None:
        pixels = bytes(
            channel for alpha in (0, 255, 255, 0) for channel in (10, 20, 30, alpha)
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.png"
            path.write_bytes(png(1, 4, pixels))
            width, height, rgba = png_rgba(path)
        self.assertEqual((width, height), (1, 4))
        self.assertEqual(alpha_segments(rgba[3::4], width, "y", 0, 0, 3, 128), [[1, 2]])

    def test_tree_comparison_is_byte_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            left, right = root / "left", root / "right"
            left.mkdir()
            right.mkdir()
            (left / "asset").write_bytes(b"same")
            (right / "asset").write_bytes(b"same")
            self.assertTrue(files_equal(left, right))
            (right / "asset").write_bytes(b"different")
            self.assertFalse(files_equal(left, right))


if __name__ == "__main__":
    unittest.main()
