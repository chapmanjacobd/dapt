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

    def test_new_remote_product_manifest_includes_rsync_and_store_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            products_dir = workspace / "products"

            self.assert_ok(
                self.run_dapt(
                    workspace,
                    "new-product",
                    "kiwix-en",
                    "--products-dir",
                    str(products_dir),
                    "--source-type",
                    "remote",
                    "--remote-url",
                    "https://example.invalid/archive/wikipedia_en.zim",
                    "--remote-rsync-url",
                    "rsync://mirror.example.internal/kiwix/wikipedia_en.zim",
                    "--remote-filename",
                    "wikipedia_en.zim",
                    "--remote-sha256",
                    "a" * 64,
                    "--remote-store-prefix",
                    "/srv/dapt-store",
                )
            )

            manifest_text = (products_dir / "kiwix-en" / "product.toml").read_text(encoding="utf-8")
            self.assertIn('remote_rsync_url = "rsync://mirror.example.internal/kiwix/wikipedia_en.zim"', manifest_text)
            self.assertIn('remote_store_prefix = "/srv/dapt-store"', manifest_text)

    def test_release_remote_product_builds_store_backed_installer_scripts(self) -> None:
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
                )
            )
            self.assert_ok(
                self.run_dapt(
                    workspace,
                    "new-product",
                    "kiwix-en",
                    "--products-dir",
                    str(products_dir),
                    "--source-type",
                    "remote",
                    "--remote-url",
                    "https://example.invalid/archive/wikipedia_en.zim",
                    "--remote-rsync-url",
                    "rsync://mirror.example.internal/kiwix/wikipedia_en.zim",
                    "--remote-filename",
                    "wikipedia_en.zim",
                    "--remote-sha256",
                    "a" * 64,
                )
            )

            self.assert_ok(
                self.run_dapt(
                    workspace,
                    "release",
                    "kiwix-en",
                    "2026.05.30",
                    "--products-dir",
                    str(products_dir),
                    "--repo-root",
                    str(repo_root),
                )
            )

            package_path = repo_root / "pool" / "main" / "dapt-kiwix-en_2026.05.30_all.deb"
            control_dir = workspace / "control"
            data_dir = workspace / "data"
            subprocess.run(["dpkg-deb", "-e", str(package_path), str(control_dir)], check=True)
            subprocess.run(["dpkg-deb", "-x", str(package_path), str(data_dir)], check=True)

            control_text = (control_dir / "control").read_text(encoding="utf-8")
            postinst_text = (control_dir / "postinst").read_text(encoding="utf-8")
            postrm_text = (control_dir / "postrm").read_text(encoding="utf-8")
            remote_manifest = (
                data_dir / "usr" / "share" / "dapt" / "products" / "kiwix-en" / "remote-source.toml"
            ).read_text(encoding="utf-8")

            self.assertIn("Depends: aria2, rsync", control_text)
            self.assertIn('rsync --archive --compare-dest="$old_store_dir"', postinst_text)
            self.assertIn('mv -Tf "$current_link.tmp" "$current_link"', postinst_text)
            self.assertIn('mv -Tf "$active_file_link.tmp" "$active_file_link"', postinst_text)
            self.assertIn('if ! rm -rf "$old_store_dir"; then', postinst_text)
            self.assertIn("failed-upgrade|abort-install|abort-upgrade)", postrm_text)
            self.assertIn('remote_rsync_url = "rsync://mirror.example.internal/kiwix/wikipedia_en.zim"', remote_manifest)
            self.assertIn('remote_store_prefix = "/var/lib/dapt/store"', remote_manifest)


if __name__ == "__main__":
    unittest.main()
