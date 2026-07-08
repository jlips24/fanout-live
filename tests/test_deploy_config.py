from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DeployConfigTests(unittest.TestCase):
    def test_nginx_rtmp_uses_single_worker(self) -> None:
        config = (ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")

        self.assertIn("worker_processes 1;", config)
        self.assertNotIn("worker_processes auto;", config)

    def test_deploy_writes_runtime_logs_to_logs_directory(self) -> None:
        nginx_config = (ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")
        entrypoint = (ROOT / "deploy" / "entrypoint.sh").read_text(encoding="utf-8")

        self.assertIn("/config/logs/nginx-error.log", nginx_config)
        self.assertIn("/config/logs/nginx-rtmp-access.log", nginx_config)
        self.assertIn("mkdir -p /config/logs", entrypoint)
        self.assertNotIn("/config/relay", nginx_config)
        self.assertNotIn("/config/relay", entrypoint)


if __name__ == "__main__":
    unittest.main()
