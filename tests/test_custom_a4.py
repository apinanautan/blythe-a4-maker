import importlib.machinery
import json
import importlib.util
import sys
import tempfile
import unittest
import unittest.mock
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
    def test_compact_numbers_keeps_order_and_pieces_together(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            for name in ("50.png", "52.1.png", "52.2.png", "55.psd", "55.png", "69.png", "notes.txt"):
                (folder / name).write_text(name)
            mapping = _app.compact_design_numbers(folder)
            self.assertEqual(mapping, {"50": "1", "52.1": "2.1", "52.2": "2.2", "55": "3", "69": "4"})
            self.assertEqual(sorted(path.name for path in folder.iterdir()), [
                "1.png", "2.1.png", "2.2.png", "3.png", "3.psd", "4.png", "notes.txt",
            ])
            self.assertEqual((folder / "4.png").read_text(), "69.png")
            self.assertEqual(_app.compact_design_numbers(folder), {})

    def test_old_folders_are_copied_into_the_library_once(self):
        with tempfile.TemporaryDirectory() as temp:
            old = Path(temp) / "dropbox"
            new = Path(temp) / "library"
            old.mkdir()
            (old / "1.png").write_text("one")
            (old / "readme.txt").write_text("skip")
            self.assertEqual(_app.copy_into_library([(old, new)]), 1)
            self.assertEqual(_app.copy_into_library([(old, new)]), 0)
            self.assertEqual((new / "1.png").read_text(), "one")
            self.assertTrue((old / "1.png").exists())

    def test_set_two_is_permanent_and_set_three_is_local_only(self):
        from types import SimpleNamespace

        source = Path("/data/ขายเเบบ1")
        fake = SimpleNamespace(
            source_var=SimpleNamespace(get=lambda: str(source)),
            source_4x6_var=SimpleNamespace(get=lambda: "/data/ไฟล์ตา"),
        )
        fake._extra_sets = lambda: _app.BlytheA4App._extra_sets(fake)
        settings = {"set2_enabled": "0", "set3_enabled": "1", "set3_folder": "/local/mine", "set3_name": "ของฉัน"}
        with unittest.mock.patch.object(_app, "load_user_settings", return_value=settings):
            self.assertEqual(
                _app.BlytheA4App._extra_sets(fake),
                [(2, "แบบที่สอง", source.parent / "ขายเเบบ2"), (3, "ของฉัน", Path("/local/mine"))],
            )
            self.assertEqual(set(_app.BlytheA4App._data_sync_folders(fake)), {"a4_set1", "a4_set2", "sheets_4x6"})
        with unittest.mock.patch.object(_app, "load_user_settings", return_value={"set3_folder": "/local/mine"}):
            self.assertEqual([group for group, _title, _folder in _app.BlytheA4App._extra_sets(fake)], [2])

    def test_trash_older_than_seven_days_is_removed(self):
        from datetime import datetime, timedelta

        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "set"
            trash = Path(temp) / "trash"
            folder.mkdir()
            (folder / "1.png").write_text("old")
            (folder / "2.png").write_text("new")
            _app.move_design_to_trash(folder, "1", trash)
            _app.move_design_to_trash(folder, "2", trash)
            later = datetime.now() + timedelta(days=7, hours=1)
            old_entry = next(item for item in _app.list_trash(trash) if item["stem"] == "1")
            meta = trash / old_entry["id"] / "meta.json"
            data = json.loads(meta.read_text(encoding="utf-8"))
            data["deleted_at"] = (datetime.now() - timedelta(days=8)).isoformat(timespec="seconds")
            meta.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(_app.purge_old_trash(trash_dir=trash), 1)
            self.assertEqual([item["stem"] for item in _app.list_trash(trash)], ["2"])
            self.assertEqual(_app.purge_old_trash(trash_dir=trash, now=later), 1)

    def test_transparent_and_fake_transparent_backgrounds(self):
        eye = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
        ImageDraw.Draw(eye).ellipse((50, 50, 149, 149), fill=(30, 120, 60, 255))
        self.assertEqual(_app.background_kind(eye), "transparent")
        left, _right = _app.make_custom_a4_pair_as_is(eye, 100)
        # The eye is cut to its own edge, so it fills the whole size like other designs.
        self.assertEqual(left.getpixel((50, 2))[3], 255)

        checker = Image.new("RGB", (200, 200), "white")
        draw = ImageDraw.Draw(checker)
        for y in range(0, 200, 10):
            for x in range(0, 200, 10):
                if (x // 10 + y // 10) % 2:
                    draw.rectangle((x, y, x + 9, y + 9), fill=(204, 204, 204))
        draw.ellipse((50, 50, 149, 149), fill=(30, 120, 60))
        self.assertEqual(_app.background_kind(checker), "checker")
        cleaned = _app.remove_checker_background(checker)
        self.assertEqual(cleaned.getpixel((5, 5))[3], 0)
        self.assertEqual(cleaned.getpixel((100, 100))[3], 255)
        self.assertEqual(_app.background_kind(Image.new("RGB", (100, 100), "white")), "solid")

    def test_orders_are_folders_with_their_items(self):
        from datetime import datetime

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = _app.create_order("Nina", root, now=datetime(2026, 10, 5, 9, 0))
            second = _app.create_order("Nina", root, now=datetime(2026, 10, 5, 10, 0))
            self.assertEqual((first.name, second.name), ("2026-10-05_Nina", "2026-10-05_Nina_2"))
            data = _app.load_order(second)
            data["a4"] = ["set1:12", "set1:12"]
            _app.save_order(second, data)
            self.assertEqual(_app.list_orders(root), [second, first])
            self.assertEqual(_app.load_order(second)["a4"], ["set1:12", "set1:12"])

    def test_trash_restore_and_renumber(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "set1"
            trash = Path(temp) / "trash"
            folder.mkdir()
            for name in ("64.png", "65.png", "65.psd", "66.png"):
                (folder / name).write_text(name)

            entry = _app.move_design_to_trash(folder, "65", trash)
            self.assertEqual(sorted(path.name for path in folder.iterdir()), ["64.png", "66.png"])
            self.assertFalse(_app.design_files(folder, "65"))
            self.assertEqual([item["stem"] for item in _app.list_trash(trash)], ["65"])

            self.assertEqual(_app.restore_from_trash(entry, trash), "65")
            self.assertEqual((folder / "65.psd").read_text(), "65.psd")
            self.assertEqual(_app.list_trash(trash), [])

            _app.renumber_design(folder, "64", "66", swap=True)
            self.assertEqual((folder / "66.png").read_text(), "64.png")
            self.assertEqual((folder / "64.png").read_text(), "66.png")
            with self.assertRaises(FileExistsError):
                _app.renumber_design(folder, "64", "65")

            _app.move_design_to_trash(folder, "66", trash)
            _app.purge_trash(trash_dir=trash)
            self.assertEqual(_app.list_trash(trash), [])

    def test_design_file_can_be_placed_on_4x6_page(self):
        with tempfile.TemporaryDirectory() as temp:
            pair = Path(temp) / "64.png"
            sheet = Image.new("RGB", (400, 200), "white")
            ImageDraw.Draw(sheet).ellipse((0, 0, 199, 199), fill="red")
            ImageDraw.Draw(sheet).ellipse((200, 0, 399, 199), fill="blue")
            sheet.save(pair)
            page = _app.render_4x6_page({"data::64::1": (pair, 0)}, ["data::64::1"])
            self.assertEqual(page.size, (_app.SIX_BY_FOUR_WIDTH, _app.SIX_BY_FOUR_HEIGHT))
            first = (_app.SIX_BY_FOUR_SOURCE_X_CENTERS[0], _app.SIX_BY_FOUR_SOURCE_Y_CENTERS[0])
            second = (_app.SIX_BY_FOUR_SOURCE_X_CENTERS[1], _app.SIX_BY_FOUR_SOURCE_Y_CENTERS[0])
            self.assertEqual(page.getpixel(first), (255, 0, 0))
            self.assertEqual(page.getpixel(second), (0, 0, 255))

    def test_ai_image_is_added_as_next_number(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            for number in (1, 2, 3, 5):
                Image.new("RGB", (40, 20), "white").save(folder / f"{number}.png")
            self.assertEqual(_app.save_image_into_set(Image.new("RGBA", (40, 20), "red"), folder), "4")
            self.assertTrue((folder / "4.png").is_file())
            self.assertFalse(any(path.name.startswith(".") for path in folder.iterdir()))

    def test_saved_custom_pair_becomes_next_number_in_set_one(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            for number in range(1, 64):
                Image.new("RGB", (40, 20), "white").save(folder / f"{number}.png")
            Image.new("RGB", (20, 20), "white").save(folder / "7.1.png")
            red = Image.new("RGBA", (20, 20), "red")
            blue = Image.new("RGBA", (20, 20), "blue")
            self.assertEqual(_app.save_pair_into_set((red, blue), folder), "64")
            left, right = _app.split_or_duplicate_pair(folder / "64.png")
            self.assertEqual(left.getpixel((10, 10))[:3], (255, 0, 0))
            self.assertEqual(right.getpixel((10, 10))[:3], (0, 0, 255))

            library = folder / _app.CUSTOM_A4_DIR_NAME
            library.mkdir()
            red.save(library / "custom_001_1.png")
            blue.save(library / "custom_001_2.png")
            self.assertEqual(_app.migrate_custom_library(folder), ["65"])
            self.assertEqual(list(library.iterdir()), [])

    def test_deleting_custom_pair_renumbers_the_rest_without_gaps(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            items = OrderedDict()
            for number in (1, 2, 3):
                paths = tuple(folder / f"custom_{number:03d}_{index}.png" for index in (1, 2))
                for index, path in enumerate(paths, start=1):
                    path.write_text(f"{number}-{index}")
                items[f"custom:{number:03d}"] = (paths[0], paths)

            renamed, id_map = _app.delete_and_renumber_custom_a4(items, "custom:002")

            self.assertEqual(list(renamed), ["custom:001", "custom:002"])
            self.assertEqual(id_map, {"custom:001": "custom:001", "custom:003": "custom:002"})
            self.assertEqual(sorted(path.name for path in folder.iterdir()), [
                "custom_001_1.png", "custom_001_2.png", "custom_002_1.png", "custom_002_2.png",
            ])
            self.assertEqual((folder / "custom_002_2.png").read_text(), "3-2")
            self.assertEqual(renamed["custom:002"][0], folder / "custom_002_1.png")
            self.assertEqual(_app.display_design_id("custom:002"), "คัส 02")

    def test_version_tuple_compares_numerically(self):
        self.assertGreater(_app.version_tuple("v1.1.10"), _app.version_tuple("1.1.9"))
        self.assertEqual(_app.version_tuple("v1.1.3"), _app.version_tuple("1.1.3"))

    def test_relaunch_environment_drops_pyinstaller_state(self):
        fake_env = {
            "PATH": "C:\\Windows",
            "_PYI_APPLICATION_HOME_DIR": "C:\\Temp\\_MEI123",
            "_PYI_PARENT_PROCESS_LEVEL": "1",
            "_MEIPASS2": "C:\\Temp\\_MEI123",
            "TCL_LIBRARY": "C:\\Temp\\_MEI123\\_tcl_data",
            "TK_LIBRARY": "C:\\Temp\\_MEI123\\_tk_data",
        }
        with unittest.mock.patch.dict(_app.os.environ, fake_env, clear=True):
            env = _app.relaunch_environment()
        self.assertEqual(env, {"PATH": "C:\\Windows", "PYINSTALLER_RESET_ENVIRONMENT": "1"})

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
