import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import blythe_ai


class ChromeExtensionTests(unittest.TestCase):
    def test_planning_generation_and_reference_edit_through_relay(self):
        plan_response = {
            "concept": "Night sky",
            "direction": "Stars",
            "style": "สมจริง",
            "design": "เส้นรัศมีธรรมชาติ",
            "pairs": [
                {"index": index, "primary": "น้ำเงิน", "secondary": "ทอง"}
                for index in range(1, 17)
            ],
        }
        picture = Image.new("RGBA", (80, 100))
        ImageDraw.Draw(picture).ellipse((10, 15, 65, 70), fill="#196b90")
        png = BytesIO()
        picture.save(png, "PNG")
        encoded = base64.b64encode(png.getvalue()).decode("ascii")
        calls = []

        class Relay(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append((self.path, body))
                if self.path.endswith("/chat/completions"):
                    reply = {"text": json.dumps(plan_response), "conversation_id": "plan-chat"}
                else:
                    reply = {"data": [{"b64_json": encoded}], "conversation_id": "image-chat"}
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(reply).encode())

        with TemporaryDirectory() as directory, ThreadingHTTPServer(("127.0.0.1", 0), Relay) as server:
            root = Path(directory)
            settings = root / "Tidmunz Studio" / "snapgen_data" / "chrome_relay.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(json.dumps({"port": server.server_port, "token": "test-token"}))
            worker = Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                with patch.dict("os.environ", {"LOCALAPPDATA": directory}):
                    plan, planning_chat = blythe_ai.design_collection_16()
                    self.assertEqual(planning_chat, {"conversation_id": "plan-chat"})
                    preset, paths, images = blythe_ai.create_eye_collection_16(plan, "", root, {})
                    cover = blythe_ai.create_cover_template(paths[0], root)
                    edit, _ = blythe_ai.create_eye(
                        "Lighter blue", root, reference_image=paths[0],
                        conversation_state={"conversation_id": "single-chat"},
                    )
            finally:
                server.shutdown()
                worker.join()

            self.assertEqual([path.name for path in paths], [f"{i:02d}.png" for i in range(1, 17)])
            self.assertTrue(all(image.width == image.height for image in images))
            self.assertTrue((preset / "collection.json").is_file())
            self.assertTrue(cover.is_file() and edit.is_file())
            self.assertEqual(calls[0][0], "/test-token/v1/chat/completions")
            self.assertEqual(calls[1][0], "/test-token/v1/images/generations")
            self.assertNotIn("conversation_id", calls[1][1])
            self.assertTrue(all(body["conversation_id"] == "image-chat" for _, body in calls[2:17]))
            self.assertEqual(calls[17][0], "/test-token/v1/images/edits")
            self.assertEqual(base64.b64decode(calls[17][1]["images"][0]), paths[0].read_bytes())
            self.assertNotIn("conversation_id", calls[17][1])
            self.assertEqual(calls[18][1]["conversation_id"], "single-chat")
