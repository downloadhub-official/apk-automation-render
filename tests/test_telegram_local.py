import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import config
from app.telegram_local import TelegramLocalFileError, copy_local_bot_api_file


class TelegramLocalFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "telegram-bot-api-data"
        self.root.mkdir()
        self.old_root = config.LOCAL_BOT_API_CONTAINER_DIR
        self.old_timeout = config.LOCAL_BOT_API_FILE_TIMEOUT_SECONDS
        config.LOCAL_BOT_API_CONTAINER_DIR = str(self.root)
        config.LOCAL_BOT_API_FILE_TIMEOUT_SECONDS = 2

    def tearDown(self):
        config.LOCAL_BOT_API_CONTAINER_DIR = self.old_root
        config.LOCAL_BOT_API_FILE_TIMEOUT_SECONDS = self.old_timeout
        self.tmp.cleanup()

    def test_absolute_local_path_is_resolved(self):
        source = self.root / "bot" / "documents" / "file.apk"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"A" * 1024)
        tg = SimpleNamespace(file_path=str(source), file_size=1024)
        destination = Path(self.tmp.name) / "downloads" / "app.apk"
        _, size = copy_local_bot_api_file(tg, destination)
        self.assertEqual(size, 1024)
        self.assertEqual(destination.read_bytes(), b"A" * 1024)

    def test_relative_path_is_resolved(self):
        source = self.root / "bot" / "documents" / "file.apk"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"XYZ")
        tg = SimpleNamespace(file_path="bot/documents/file.apk", file_size=3)
        destination = Path(self.tmp.name) / "x.apk"
        _, size = copy_local_bot_api_file(tg, destination)
        self.assertEqual(size, 3)

    def test_path_traversal_is_rejected(self):
        tg = SimpleNamespace(
            file_path=str(self.root / "bot" / "documents" / "../../outside.apk"),
            file_size=10,
        )
        with self.assertRaises(TelegramLocalFileError):
            copy_local_bot_api_file(tg, Path(self.tmp.name) / "x.apk")

    def test_missing_file_times_out(self):
        tg = SimpleNamespace(file_path="bot/documents/missing.apk", file_size=10)
        with self.assertRaisesRegex(TelegramLocalFileError, "Timed out"):
            copy_local_bot_api_file(tg, Path(self.tmp.name) / "x.apk")

    def test_size_mismatch_is_rejected(self):
        source = self.root / "bot" / "documents" / "file.apk"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"123")
        tg = SimpleNamespace(file_path=str(source), file_size=4)
        with self.assertRaisesRegex(TelegramLocalFileError, "size mismatch"):
            copy_local_bot_api_file(tg, Path(self.tmp.name) / "x.apk")

    def test_file_still_being_written_is_waited_for(self):
        source = self.root / "bot" / "documents" / "file.apk"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"A")
        tg = SimpleNamespace(file_path=str(source), file_size=4096)
        destination = Path(self.tmp.name) / "out.apk"

        def writer():
            time.sleep(0.4)
            source.write_bytes(b"A" * 4096)

        import threading
        thread = threading.Thread(target=writer)
        thread.start()
        _, size = copy_local_bot_api_file(tg, destination)
        thread.join()
        self.assertEqual(size, 4096)


if __name__ == "__main__":
    unittest.main()
