#!/usr/bin/env python3

"""Takes a source bucket, a backup bucket, encryption key as args.

Will rsync down the source,
tar those files up,
and upload the resulting tarball to the backup bucket.

If you provide a service account key path, script will call out to gcloud to initialize it

On successful completion, prints:

    Backup success <timestamp>

On failure at any stage, prints:

    Backup error <timestamp>

The status line is written to stdout. Logs are written to stderr.
"""

from __future__ import annotations

import argparse
import datetime
import logging
import os
import shlex
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
logger.addHandler(ch)


def backup_status_timestamp() -> str:
    """Return a simple UTC ISO-8601 timestamp for status output."""
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def print_backup_status(status: str) -> None:
    """Print the one-line backup status.

    This intentionally uses stdout and flush=True so container log collectors,
    cron, Kubernetes, ECS, etc. can see it immediately.
    """
    print(f"{status} {backup_status_timestamp()}", flush=True)


class ChattyArgParser(argparse.ArgumentParser):
    """ArgumentParser that prints full help instead of short usage on argument error"""

    def error(self, message: str) -> None:
        logger.error("%s: %s\n", self.prog, message)
        self.print_help(sys.stderr)
        self.exit(2)


class GCPBucketBackup:
    """Bucket backup functionality"""

    def __init__(  # pylint: disable=too-many-positional-arguments
        self,
        src_bucket: str,
        backup_bucket: str,
        encrypt_key: str,
        filename: str,
        gsutil_path: str,
    ) -> None:
        self.src = src_bucket
        self.dst = backup_bucket
        self.encrypt_key = encrypt_key
        self.gsutil_path = gsutil_path
        self.filename = filename

    def _redact_secret(self, value: str) -> str:
        """Redact the encryption key from logs/errors if it appears."""
        if self.encrypt_key:
            return value.replace(self.encrypt_key, "X" * 10)
        return value

    def _cmd_for_log(self, cmd: list[str]) -> str:
        """Return a shell-like command string for readable debug logs."""
        rendered = " ".join(shlex.quote(str(part)) for part in cmd)
        return self._redact_secret(rendered)

    def _subprocess_debug_wrap(self, cmd: list[str]) -> str:
        """Run a subprocess command and return combined stdout/stderr.

        Raises RuntimeError on failure instead of exiting, so the top-level
        handler can always print "Backup error <timestamp>".
        """
        logger.debug("Calling command %s", self._cmd_for_log(cmd))

        try:
            completed = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"command not found: {self._cmd_for_log(cmd)}") from exc
        except subprocess.CalledProcessError as exc:
            output = exc.stdout or ""
            output = self._redact_secret(output)

            raise RuntimeError(
                "command failed with status "
                f"{exc.returncode}: {self._cmd_for_log(cmd)}\n"
                f"output = {output}"
            ) from exc

        output = completed.stdout or ""
        logger.debug("%s", self._redact_secret(output))

        return output

    def initialize_svc_acct(self, acct_key_path: str) -> None:
        """Initialize gcloud tooling using a GCP service account key"""
        gcloud_auth_cmd = [
            "gcloud",
            "auth",
            "activate-service-account",
            "--key-file",
            acct_key_path,
        ]
        self._subprocess_debug_wrap(gcloud_auth_cmd)

    def gsutil_encrypt_cp_cmd(self, src: str, dst: str) -> None:
        """Copy a local file to a bucket with encryption"""
        gsutil_base_cmd = [
            self.gsutil_path,
            "-o",
            f'"GSUtil:encryption_key={self.encrypt_key}"',
            "cp",
            src,
            dst,
        ]

        self._subprocess_debug_wrap(gsutil_base_cmd)
        logger.info("Uploaded to encrypted bucket destination %s", dst)

    def rsync_cmd(self, src: str, dst: str, dry: bool = False) -> None:
        """Call gsutil rsync against two paths."""
        gsutil_base_cmd = [
            self.gsutil_path,
            "-m",
            "rsync",
            "-r",
            "-d",
            src,
            dst,
        ]

        if dry:
            gsutil_base_cmd.insert(4, "-n")

        self._subprocess_debug_wrap(gsutil_base_cmd)

    def rsync_source_bucket(self, local_dir: str) -> str:
        """Pull down a copy of a bucket contents for local comparison"""
        Path(local_dir).mkdir(parents=True, exist_ok=True)
        logger.debug("Created local dir %s for bucket manipulation", local_dir)

        self.rsync_cmd(self.src, local_dir)

        return local_dir

    def tar_directory(self, source_dir: str, tar_file_path: str) -> str:
        """Tar+gzip up a directory and return path to that tar ball"""
        source_path = Path(source_dir)
        tar_path = Path(tar_file_path)

        with tarfile.open(tar_path, "w:gz") as tar:
            for child in source_path.iterdir():
                tar.add(child, arcname=child.name)

        logger.debug("Created tar at %s of %s", tar_path, source_path)

        return str(tar_path)

    def upload_encrypted_timestamp_file(self, upload_file: str) -> None:
        """Given a file path upload said file to our backup bucket.
        File is timestamp'd and includes file prefix."""
        now = datetime.datetime.now(datetime.timezone.utc)
        timestamp = f"{now.strftime('%Y-%m-%dT%H-%M-%SZ')}-{int(now.timestamp())}"
        backup_bucket_path = os.path.join(self.dst, f"{timestamp}-{self.filename}")

        self.gsutil_encrypt_cp_cmd(upload_file, backup_bucket_path)


def build_parser(encryption_key_from_env: str | None) -> ChattyArgParser:
    """Build CLI argument parser."""
    default_src = os.environ.get("GS_BACKUP_SRC")
    default_dest = os.environ.get("GS_BACKUP_DEST")
    default_name = os.environ.get("GS_BACKUP_FILENAME")

    parser = ChattyArgParser(description=__doc__)

    parser.add_argument(
        "-f",
        "--from-bucket",
        type=str,
        help=(
            "Source bucket URL prefix "
            "(e.g. gs://files.example.org/stuff); or set GS_BACKUP_SRC"
        ),
        default=default_src,
        required=default_src is None,
    )
    parser.add_argument(
        "-t",
        "--to-bucket",
        type=str,
        help=(
            "Destination bucket URL prefix "
            "(e.g. gs://example-org-backups/files); or set GS_BACKUP_DEST"
        ),
        default=default_dest,
        required=default_dest is None,
    )
    parser.add_argument(
        "-n",
        "--filename",
        type=str,
        help=(
            "Object name to create, prefixed with timestamp "
            "(e.g. stuff.tar.gz); or set GS_BACKUP_FILENAME"
        ),
        default=default_name,
        required=default_name is None,
    )
    parser.add_argument(
        "-e",
        "--encryption-key-path",
        type=str,
        help=(
            "File containing key for uploaded object; "
            "or set GS_ENCRYPTION_KEY to value of key"
        ),
        required=encryption_key_from_env is None,
    )
    parser.add_argument(
        "-g",
        "--gsutil",
        type=str,
        help="Path to gsutil binary on disk",
        default="/usr/bin/gsutil",
        required=False,
    )
    parser.add_argument(
        "-s",
        "--svc-acct-key",
        type=str,
        help="Full path to GCP service account key",
        required=False,
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Increase verbosity",
        default=False,
        required=False,
    )

    return parser


def read_encryption_key(parsed_args: argparse.Namespace) -> str:
    """Load encryption key from env or file."""
    encryption_key = os.environ.get("GS_ENCRYPTION_KEY")

    if parsed_args.encryption_key_path is not None:
        key_path = Path(parsed_args.encryption_key_path)

        try:
            encryption_key = key_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(
                f"Could not read encryption key from {parsed_args.encryption_key_path}"
            ) from exc

    if not encryption_key:
        raise RuntimeError(
            "No encryption key provided. Set GS_ENCRYPTION_KEY or use "
            "--encryption-key-path."
        )

    return encryption_key


def run_backup() -> None:
    """Run the full backup process.

    Any exception raised here is caught by main(), which prints Backup error.
    """
    encryption_key_from_env = os.environ.get("GS_ENCRYPTION_KEY")

    parser = build_parser(encryption_key_from_env)
    parsed_args = parser.parse_args()

    if parsed_args.verbose:
        logger.setLevel(logging.DEBUG)

    logger.debug("ARGS piped in: %s", parsed_args)

    encryption_key = read_encryption_key(parsed_args)

    backup = GCPBucketBackup(
        src_bucket=parsed_args.from_bucket,
        backup_bucket=parsed_args.to_bucket,
        encrypt_key=encryption_key,
        filename=parsed_args.filename,
        gsutil_path=parsed_args.gsutil,
    )

    with tempfile.TemporaryDirectory(prefix="gcp-bucket-backup-") as work_dir:
        work_path = Path(work_dir)

        sync_dir = work_path / "src"
        tar_path = work_path / "src-bucket.tar.gz"

        if parsed_args.svc_acct_key:
            backup.initialize_svc_acct(parsed_args.svc_acct_key)

        backup.rsync_source_bucket(str(sync_dir))
        local_tar = backup.tar_directory(str(sync_dir), str(tar_path))
        backup.upload_encrypted_timestamp_file(local_tar)


def main() -> int:
    """Script entrypoint.

    Catches failures so we can emit the required status line before exiting.
    """
    try:
        run_backup()

    except SystemExit as exc:
        # argparse exits this way. For --help, code is 0, and this was not
        # a backup attempt, so do not print Backup success or Backup error.
        code = exc.code if isinstance(exc.code, int) else 1

        if code != 0:
            print_backup_status("Backup error")

        return code

    except Exception:  # pylint: disable=broad-exception-caught
        # We *want* to catch broad exceptions of any kind.
        logger.exception("Backup failed")
        print_backup_status("Backup error")
        return 1

    print_backup_status("Backup success")
    return 0


if __name__ == "__main__":
    sys.exit(main())
