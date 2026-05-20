#!/usr/bin/env sh
set +e

status_file="/tmp/backup-status.$$"
export BACKUP_STATUS_FILE="$status_file"

emit_error() {
  printf 'Backup error %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
}

trap 'emit_error; exit 143' TERM
trap 'emit_error; exit 130' INT

python3 -u /usr/local/bin/gs_bucket_sync.py "$@"
rc=$?

if [ "$rc" -ne 0 ] && [ ! -s "$status_file" ]; then
  emit_error
fi

rm -f "$status_file"
exit "$rc"
