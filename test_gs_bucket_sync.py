# pylint: disable=missing-module-docstring,missing-class-docstring,missing-function-docstring

import subprocess
import unittest
import unittest.mock
from pathlib import Path

from gs_bucket_sync import GCPBucketBackup


GENERIC_ARGS = {
    "src_bucket": "gs://src-bucket/dir/",
    "backup_bucket": "gs://backup-bucket/dir",
    "encrypt_key": "124124213123",
    "filename": "siteapp.tar.gz",
    "gsutil_path": "/usr/local/bin/gsutil",
}


class TestBucketSync(unittest.TestCase):

    # We can disable this because this is a test class, and test classes are always weird
    # pylint: disable=attribute-defined-outside-init
    def setUp(self):
        self.gen_backup_obj = GCPBucketBackup(**GENERIC_ARGS)

    def test_rsync_cmd_cli_str(self):
        """Throw different options against rsync function to determine called command"""

        backup = self.gen_backup_obj

        with unittest.mock.patch("gs_bucket_sync.subprocess.run") as mock_subp:
            mock_subp.return_value.stdout = ""

            assert_call_skel = [
                backup.gsutil_path,
                "-m",
                "rsync",
                "-r",
                "-d",
                GENERIC_ARGS["src_bucket"],
                GENERIC_ARGS["backup_bucket"],
            ]

            assert_call_kws = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "check": True,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
            }

            # With dry-run
            backup.rsync_cmd(backup.src, backup.dst, dry=True)
            cmd_dry = assert_call_skel[:4] + ["-n"] + assert_call_skel[4:]
            mock_subp.assert_called_with(cmd_dry, **assert_call_kws)

            # Without dry-run
            backup.rsync_cmd(backup.src, backup.dst)
            mock_subp.assert_called_with(assert_call_skel, **assert_call_kws)

            # Lets try swapping out the gsutil config path
            backup.gsutil_path = "/bin/gsutil"
            cmd_binswap = [backup.gsutil_path] + assert_call_skel[1:]
            backup.rsync_cmd(backup.src, backup.dst)
            mock_subp.assert_called_with(cmd_binswap, **assert_call_kws)

    def test_tar_invocation(self):
        """Ensure we are calling tar with the expected path and returning a full tarfile path"""

        source_dir = "/tmp/dir"
        tar_file_path = "/tmp/work/src-bucket.tar.gz"

        fake_child = Path("/tmp/dir/example.txt")

        with unittest.mock.patch("gs_bucket_sync.tarfile.open") as mock_tar_open:
            with unittest.mock.patch(
                "gs_bucket_sync.Path.iterdir",
                return_value=[fake_child],
            ):
                tar_handle = mock_tar_open.return_value.__enter__.return_value

                tar_action = self.gen_backup_obj.tar_directory(
                    source_dir,
                    tar_file_path,
                )

                assert tar_action == tar_file_path
                mock_tar_open.assert_called_once_with(Path(tar_file_path), "w:gz")
                tar_handle.add.assert_called_once_with(
                    fake_child,
                    arcname="example.txt",
                )
