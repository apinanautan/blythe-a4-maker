import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import data_sync  # noqa: E402


class FakeGitHub:
    """In-memory stand-in for the data branch."""

    def __init__(self, files=None, token="token"):
        self.files = dict(files or {})
        self.token = token
        self.commits = 0

    def head_sha(self):
        return f"commit{self.commits}" if self.files or self.commits else None

    def remote_files(self, _commit):
        return {path: data_sync.git_blob_sha(data) for path, data in self.files.items()}

    def download(self, path, _commit):
        return self.files[path]

    def commit(self, _parent, uploads, deletions, _message):
        for path, local in uploads.items():
            self.files[path] = local.read_bytes()
        for path in deletions:
            self.files.pop(path, None)
        self.commits += 1
        return f"commit{self.commits}"


class DataSyncTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.state = self.root / "state" / "data_sync_state.json"

    def tearDown(self):
        self._temp.cleanup()

    def folders(self, name):
        base = self.root / name
        return {"a4_set1": base / "set1", "a4_set2": base / "set2", "sheets_4x6": base / "4x6"}

    def test_upload_then_fresh_machine_downloads_everything(self):
        github = FakeGitHub()
        first = self.folders("pc1")
        (first["a4_set1"] / "_custom_a4").mkdir(parents=True)
        (first["a4_set1"] / "_prepared_14.5mm").mkdir()
        (first["a4_set1"] / "1.png").write_bytes(b"one")
        (first["a4_set1"] / "_prepared_14.5mm" / "cache.png").write_bytes(b"cache")
        result = data_sync.sync(first, self.state, client=github)
        self.assertEqual(result.uploaded, ["a4_set1/1.png"])
        self.assertNotIn("a4_set1/_prepared_14.5mm/cache.png", github.files)

        fresh = self.folders("pc2")
        result = data_sync.sync(fresh, self.root / "pc2_state.json", client=github)
        self.assertEqual(result.downloaded, ["a4_set1/1.png"])
        self.assertEqual((fresh["a4_set1"] / "1.png").read_bytes(), b"one")

    def test_local_delete_is_pushed_and_remote_delete_is_pulled(self):
        github = FakeGitHub()
        folders = self.folders("pc")
        folders["a4_set1"].mkdir(parents=True)
        (folders["a4_set1"] / "1.png").write_bytes(b"one")
        (folders["a4_set1"] / "2.png").write_bytes(b"two")
        data_sync.sync(folders, self.state, client=github)

        (folders["a4_set1"] / "1.png").unlink()
        github.files.pop("a4_set1/2.png")
        github.commits += 1
        result = data_sync.sync(folders, self.state, client=github)
        self.assertEqual(result.deleted_remote, ["a4_set1/1.png"])
        self.assertEqual(result.deleted_local, ["a4_set1/2.png"])
        self.assertFalse((folders["a4_set1"] / "2.png").exists())
        self.assertEqual(github.files, {})

    def test_without_token_downloads_but_does_not_upload(self):
        github = FakeGitHub({"a4_set1/1.png": b"one"}, token="")
        folders = self.folders("pc")
        folders["a4_set1"].mkdir(parents=True)
        (folders["a4_set1"] / "5.png").write_bytes(b"five")
        result = data_sync.sync(folders, self.state, client=github)
        self.assertEqual(result.downloaded, ["a4_set1/1.png"])
        self.assertTrue(result.upload_needs_token)
        self.assertNotIn("a4_set1/5.png", github.files)


if __name__ == "__main__":
    unittest.main()
