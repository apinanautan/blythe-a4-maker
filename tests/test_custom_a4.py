import importlib.machinery
import importlib.util
import sys
import tempfile
import unittest
import zipfile
from collections import OrderedDict
from pathlib import Path

from PIL import Image, ImageDraw


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))
_loader = importlib.machinery.SourceFileLoader("blythe_a4_maker_test", str(APP_DIR / "blythe_a4_maker.pyw"))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
_app = importlib.util.module_from_spec(_spec)
_loader.exec_module(_app)


class CustomA4Tests(unittest.TestCase):
    def test_white_background_is_detected_for_automatic_transparency(self):
        self.assertTrue(_app._has_white_background(Image.new("RGB", (32, 32), "white")))
        self.assertFalse(_app._has_white_background(Image.new("RGB", (32, 32), "#335577")))

    def test_update_archive_extracts_repository_and_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            archive = folder / "source.zip"
            with zipfile.ZipFile(archive, "w") as source:
                source.writestr("blythe-a4-maker-main/app/blythe_a4_maker.pyw", "app")
            extracted = _app.extract_update_archive(archive, folder / "valid")
            self.assertEqual((extracted / "app" / "blythe_a4_maker.pyw").read_text(), "app")

            legacy_archive = folder / "legacy.zip"
            with zipfile.ZipFile(legacy_archive, "w") as source:
                source.writestr("blythe-a4-maker-main/blythe_a4_maker.pyw", "legacy")
            legacy = _app.extract_update_archive(legacy_archive, folder / "legacy")
            self.assertEqual((legacy / "blythe_a4_maker.pyw").read_text(), "legacy")

            unsafe_archive = folder / "unsafe.zip"
            with zipfile.ZipFile(unsafe_archive, "w") as source:
                source.writestr("blythe-a4-maker-main/../outside.txt", "unsafe")
            with self.assertRaises(ValueError):
                _app.extract_update_archive(unsafe_archive, folder / "unsafe")
            self.assertFalse((folder / "outside.txt").exists())

    def test_first_run_asset_zip_extracts_only_cover_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            archive = folder / "assets.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("cover_assets/doll_cover_base.png", b"base")
                bundle.writestr("cover_assets/doll_cover_overlay.png", b"overlay")
                bundle.writestr("cover_assets/templates_gpt_blank/manifest.json", b"[]")
            destination = folder / "staged"
            _app.extract_cover_asset_archive(archive, destination)
            self.assertEqual((destination / "cover_assets" / "templates_gpt_blank" / "manifest.json").read_bytes(), b"[]")

            unsafe = folder / "unsafe_assets.zip"
            with zipfile.ZipFile(unsafe, "w") as bundle:
                bundle.writestr("cover_assets/../../outside.txt", b"unsafe")
            with self.assertRaises(ValueError):
                _app.extract_cover_asset_archive(unsafe, folder / "unsafe")
            self.assertFalse((folder / "outside.txt").exists())

    def test_saved_custom_pairs_are_loaded_into_the_a4_library(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            left = folder / "custom_004_1.png"
            right = folder / "custom_004_2.png"
            Image.new("RGBA", (16, 16), "white").save(left)
            Image.new("RGBA", (16, 16), "black").save(right)
            Image.new("RGBA", (16, 16), "red").save(folder / "custom_005_1.png")

            library = _app.discover_custom_a4_items(folder)

        self.assertEqual(list(library), ["custom:004"])
        self.assertEqual(library["custom:004"][1], (left, right))

    def test_background_cut_preserves_enclosed_background_color(self):
        image = Image.new("RGBA", (240, 240), "white")
        draw = ImageDraw.Draw(image)
        draw.ellipse((30, 30, 210, 210), fill="black")
        draw.ellipse((85, 85, 155, 155), fill="white")

        result = _app.remove_outer_background(image)

        self.assertEqual(result.getpixel((0, 0))[3], 0)
        self.assertEqual(result.getpixel((120, 120))[3], 255)

    def test_custom_pair_is_equal_circles_and_zoom_changes_scale(self):
        image = Image.new("RGBA", (240, 240), "white")
        ImageDraw.Draw(image).ellipse((30, 30, 210, 210), fill="black")
        small = _app.make_custom_a4_pair(image, 171, zoom=0.6, remove_background=True)
        large = _app.make_custom_a4_pair(image, 171, zoom=1.6, remove_background=True)

        self.assertEqual([eye.size for eye in small], [(171, 171), (171, 171)])
        self.assertGreater(large[0].getchannel("A").getbbox()[2], small[0].getchannel("A").getbbox()[2])

        portrait = _app.make_custom_a4_pair(Image.new("RGBA", (120, 240), "#336699"), 171)[0]
        left, _top, right, _bottom = portrait.getchannel("A").getbbox()
        self.assertLess(abs((left + right) / 2 - 85.5), 2)

    def test_complete_artwork_can_be_sized_without_cropping(self):
        source = Image.new("RGBA", (20, 40), "red")
        pair = _app.make_custom_a4_pair_as_is(source, 100)

        self.assertEqual([eye.size for eye in pair], [(100, 100), (100, 100)])
        self.assertEqual(pair[0].getpixel((5, 50)), (255, 255, 255, 255))
        self.assertEqual(pair[0].getpixel((25, 50)), (255, 0, 0, 255))
        self.assertEqual(pair[0].getpixel((74, 50)), (255, 0, 0, 255))
        self.assertEqual(pair[0].getpixel((95, 50)), (255, 255, 255, 255))

    def test_crop_preview_pans_without_losing_the_crop_boundary(self):
        image = Image.new("RGBA", (100, 100), "#335577")
        ImageDraw.Draw(image).rectangle((30, 42, 40, 52), fill="#FFD700")
        left = _app.make_custom_a4_crop_preview(image, 100, zoom=2, pan_x=-1)
        right = _app.make_custom_a4_crop_preview(image, 100, zoom=2, pan_x=1)

        left_pixels = left.load()
        right_pixels = right.load()
        left_x = [x for y in range(100) for x in range(100) if left_pixels[x, y][0] > 220 and left_pixels[x, y][1] > 180]
        right_x = [x for y in range(100) for x in range(100) if right_pixels[x, y][0] > 220 and right_pixels[x, y][1] > 180]

        self.assertFalse(left_x)
        self.assertTrue(right_x)
        self.assertGreater(min(right_x), 50)

    def test_crop_guide_is_centered_and_shades_outside_the_circle(self):
        guide = _app.make_custom_a4_crop_guide(101)
        alpha = guide.getchannel("A")

        self.assertEqual(alpha.getpixel((50, 50)), 0)
        self.assertGreater(alpha.getpixel((0, 0)), 0)
        self.assertEqual(alpha.getpixel((50, 1)), alpha.getpixel((50, 99)))
        self.assertEqual(alpha.getpixel((1, 50)), alpha.getpixel((99, 50)))

    def test_crop_source_centers_visible_art_inside_asymmetric_empty_margins(self):
        source = Image.new("RGBA", (180, 120), (0, 0, 0, 0))
        ImageDraw.Draw(source).ellipse((60, 10, 160, 110), fill="#486078")

        centered = _app.trim_custom_a4_transparent_margin(source)

        self.assertEqual(centered.size, (101, 101))

    def test_crop_detects_and_centers_iris_on_nonwhite_flat_background(self):
        source = Image.new("RGBA", (200, 160), "#9AA39E")
        ImageDraw.Draw(source).ellipse((72, 22, 172, 122), fill="#334455")

        self.assertTrue(_app._has_uniform_edge_background(source))
        cutout = _app.remove_outer_background(source)
        centered = _app.trim_custom_a4_transparent_margin(cutout)
        preview = _app.make_custom_a4_crop_preview(centered, 100, zoom=1)
        bounds = preview.getchannel("A").getbbox()

        self.assertEqual(centered.size, (101, 101))
        self.assertEqual(bounds, (0, 0, 100, 100))

    def test_custom_pair_fits_standard_a4_slots(self):
        pair = _app.make_custom_a4_pair(Image.new("RGBA", (240, 240), "#336699"), 171)
        with tempfile.TemporaryDirectory() as temp:
            paths = []
            for index, eye in enumerate(pair):
                path = Path(temp) / f"{index}.png"
                eye.save(path)
                paths.append(path)
            slots, *_ = _app.prepare_a4_layout(
                OrderedDict([("custom:001", paths[0])]),
                OrderedDict([("custom:001", 1)]),
                prepared_assets=OrderedDict([("custom:001", tuple(paths))]),
            )

        self.assertEqual(len(slots), 2)
        self.assertEqual(slots[0].size, (_app.diameter_to_pixels(_app.DEFAULT_DIAMETER_MM),) * 2)


if __name__ == "__main__":
    unittest.main()
