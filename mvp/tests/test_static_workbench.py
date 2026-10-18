from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from rkd_mvp.api_server import create_server
from rkd_mvp.api_service import ApiService
from rkd_mvp.engine import MVPApp
from rkd_mvp.sqlite_store import SQLiteStore


class StaticWorkbenchTests(unittest.TestCase):
    def test_single_server_serves_built_workbench_and_blocks_traversal(self) -> None:
        root = Path(__file__).resolve().parents[2]
        static_dir = root / "web" / "dist"
        self.assertTrue((static_dir / "index.html").is_file(), "run npm run build first")
        asset = next(static_dir.glob("assets/*.js"), None)
        self.assertIsNotNone(asset, "run npm run build first")
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteStore(Path(directory) / "app.sqlite3")
            server = create_server(ApiService(MVPApp(store)), port=0, static_dir=static_dir)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(f"{base_url}/", timeout=2) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn("RKD AI", response.read().decode("utf-8"))
                with urlopen(f"{base_url}/assets/{asset.name}", timeout=2) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn(response.headers.get("Content-Type", ""), {"text/javascript", "application/javascript"})
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(f"{base_url}/%2e%2e/app.sqlite3"), timeout=2)
                self.assertEqual(error.exception.code, 404)
            finally:
                server.shutdown()
                server.server_close()
                store.close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
