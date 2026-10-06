import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_mobile_library  # noqa: E402


class MobileLibraryTests(unittest.TestCase):
    def test_library_has_desktop_sized_chips_sheets_and_covers(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / "data"
            (data / "a4_set1").mkdir(parents=True)
            (data / "sheets_4x6").mkdir()
            pair = Image.new("RGB", (400, 200), "white")
            ImageDraw.Draw(pair).ellipse((10, 10, 190, 190), fill="red")
            ImageDraw.Draw(pair).ellipse((210, 10, 390, 190), fill="blue")
            pair.save(data / "a4_set1" / "1.png")
            Image.new("RGB", (100, 100), "green").save(data / "a4_set1" / "2.1.png")
            Image.new("RGB", (1800, 1200), "white").save(data / "sheets_4x6" / "sheet.png")

            index = build_mobile_library.build(data, Path(temp) / "out")

            items = {item["id"]: item for item in index["sets"][0]["items"]}
            self.assertEqual(items["set1:1"]["pieces"], 2)
            self.assertEqual(items["set1:2.1"]["pieces"], 1)
            chip = index["layout"]["a4"]["chip"]
            with Image.open(Path(temp) / "out" / items["set1:1"]["file"]) as image:
                self.assertEqual(image.size, (chip * 2, chip))
                self.assertEqual(image.getpixel((chip // 2, chip // 2)), (255, 0, 0))
            self.assertEqual(len(index["sheets"]), 1)
            six = index["layout"]["six"]["chip"]
            with Image.open(Path(temp) / "out" / index["sheets"][0]["file"]) as grid:
                self.assertEqual(grid.size, (six * 8, six * 4))
            self.assertTrue(index["covers"])
            saved = json.loads((Path(temp) / "out" / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["layout"]["a4"]["width"], 2480)


if __name__ == "__main__":
    unittest.main()
