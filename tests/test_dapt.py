from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dapt.py"


@unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb is required")
class DaptCliTests(unittest.TestCase):
    def run_dapt(self, workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(SCRIPT), *args],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
        )

    def assert_ok(self, completed: subprocess.CompletedProcess[str]) -> None:
        if completed.returncode != 0:
            self.fail(
                "command failed\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )

    def test_release_uses_product_component(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            repo_root = workspace / "repo"
            products_dir = workspace / "products"

            self.assert_ok(
                self.run_dapt(
                    workspace,
                    "init-repo",
                    "--repo-root",
                    str(repo_root),
                    "--components",
                    "main",
                    "staging",
                    "--architectures",
                    "amd64",
                    "all",
                )
            )
            self.assert_ok(
                self.run_dapt(
                    workspace,
                    "new-product",
                    "climate-hourly",
                    "--products-dir",
                    str(products_dir),
                    "--component",
                    "staging",
                    "--maintainer",
                    "Data Team <data@example.com>",
                    "--summary",
                    "Climate snapshots",
                    "--description",
                    "Hourly climate snapshots.",
                )
            )

            payload_dir = products_dir / "climate-hourly" / "payload"
            (payload_dir / "snapshot.txt").write_text("example\n", encoding="utf-8")

            self.assert_ok(
                self.run_dapt(
                    workspace,
                    "release",
                    "climate-hourly",
                    "2026.05.30",
                    "--products-dir",
                    str(products_dir),
                    "--repo-root",
                    str(repo_root),
                )
            )

            package_name = "dapt-climate-hourly_2026.05.30_all.deb"
            self.assertTrue((repo_root / "pool" / "staging" / package_name).exists())
            self.assertFalse((repo_root / "pool" / "main" / package_name).exists())

            release_text = (repo_root / "dists" / "stable" / "Release").read_text(encoding="utf-8")
            self.assertIn("Components: main staging", release_text)

            staging_packages = (
                repo_root / "dists" / "stable" / "staging" / "binary-all" / "Packages"
            ).read_text(encoding="utf-8")
            self.assertIn("Package: dapt-climate-hourly", staging_packages)

    def test_release_defaults_legacy_manifests_to_main(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            repo_root = workspace / "repo"
            products_dir = workspace / "products"

            self.assert_ok(
                self.run_dapt(
                    workspace,
                    "init-repo",
                    "--repo-root",
                    str(repo_root),
                    "--components",
                    "main",
                    "staging",
                )
            )
            self.assert_ok(
                self.run_dapt(
                    workspace,
                    "new-product",
                    "climate-daily",
                    "--products-dir",
                    str(products_dir),
                )
            )

            manifest_path = products_dir / "climate-daily" / "product.toml"
            manifest_text = manifest_path.read_text(encoding="utf-8")
            manifest_path.write_text(
                "\n".join(
                    line for line in manifest_text.splitlines() if not line.startswith("component = ")
                )
                + "\n",
                encoding="utf-8",
            )

            payload_dir = products_dir / "climate-daily" / "payload"
            (payload_dir / "snapshot.txt").write_text("example\n", encoding="utf-8")

            self.assert_ok(
                self.run_dapt(
                    workspace,
                    "release",
                    "climate-daily",
                    "2026.05.30",
                    "--products-dir",
                    str(products_dir),
                    "--repo-root",
                    str(repo_root),
                )
            )

            package_name = "dapt-climate-daily_2026.05.30_all.deb"
            self.assertTrue((repo_root / "pool" / "main" / package_name).exists())

    def test_refresh_repo_allows_same_package_version_in_multiple_components(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            repo_root = workspace / "repo"
            products_dir = workspace / "products"

            self.assert_ok(
                self.run_dapt(
                    workspace,
                    "init-repo",
                    "--repo-root",
                    str(repo_root),
                    "--components",
                    "main",
                    "staging",
                )
            )
            self.assert_ok(
                self.run_dapt(
                    workspace,
                    "new-product",
                    "climate-weekly",
                    "--products-dir",
                    str(products_dir),
                )
            )

            payload_dir = products_dir / "climate-weekly" / "payload"
            (payload_dir / "snapshot.txt").write_text("example\n", encoding="utf-8")

            self.assert_ok(
                self.run_dapt(
                    workspace,
                    "release",
                    "climate-weekly",
                    "2026.05.30",
                    "--products-dir",
                    str(products_dir),
                    "--repo-root",
                    str(repo_root),
                )
            )

            package_name = "dapt-climate-weekly_2026.05.30_all.deb"
            shutil.copy2(
                repo_root / "pool" / "main" / package_name,
                repo_root / "pool" / "staging" / package_name,
            )

            self.assert_ok(
                self.run_dapt(
                    workspace,
                    "refresh-repo",
                    "--repo-root",
                    str(repo_root),
                )
            )

            staging_packages = (
                repo_root / "dists" / "stable" / "staging" / "binary-all" / "Packages"
            ).read_text(encoding="utf-8")
            self.assertIn("Package: dapt-climate-weekly", staging_packages)


if __name__ == "__main__":
    unittest.main()
