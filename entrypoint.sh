#!/usr/bin/env sh
set +e
# Never echo commands: the encryption key can be present briefly while this
# wrapper writes the private gsutil/boto config.
set +x

status_file="/tmp/backup-status.$$"
export BACKUP_STATUS_FILE="$status_file"

backup_tmp_dir=""

emit_error() {
  printf 'Backup error %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
}

cleanup() {
  rm -f "$status_file"

  if [ -n "$backup_tmp_dir" ]; then
    rm -rf "$backup_tmp_dir"
  fi
}

find_encryption_key_path() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      -e|--encryption-key-path)
        shift
        if [ "$#" -gt 0 ]; then
          printf '%s\n' "$1"
          return 0
        fi
        ;;
      --encryption-key-path=*)
        printf '%s\n' "${1#*=}"
        return 0
        ;;
    esac
    shift
  done

  return 1
}

append_boto_path() {
  if [ -z "${1:-}" ]; then
    return 0
  fi

  if [ -n "${new_boto_path:-}" ]; then
    new_boto_path="${new_boto_path}:$1"
  else
    new_boto_path="$1"
  fi
}

configure_gsutil_encryption() {
  key_value=""
  key_path=""
  new_boto_path=""

  if [ -n "${GS_ENCRYPTION_KEY:-}" ]; then
    key_value="$GS_ENCRYPTION_KEY"
  else
    key_path="$(find_encryption_key_path "$@")" || key_path=""

    if [ -n "$key_path" ]; then
      if [ ! -r "$key_path" ]; then
        printf 'ERROR: Could not read encryption key file\n' >&2
        return 1
      fi

      # Strip line endings from Kubernetes Secret files and simple key files.
      key_value="$(tr -d '\r\n' < "$key_path")"
    fi
  fi

  if [ -n "$key_value" ]; then
    backup_tmp_dir="$(mktemp -d /tmp/gcp-bucket-backup.XXXXXX)" || return 1

    # Keep the key out of argv, logs, and child process environments. gsutil
    # reads this config file via BOTO_PATH.
    umask 077
    boto_config="$backup_tmp_dir/boto.cfg"
    {
      printf '[GSUtil]\n'
      printf 'encryption_key = %s\n' "$key_value"
    } > "$boto_config" || return 1

    # Use BOTO_PATH rather than BOTO_CONFIG so we do not stomp any existing
    # Cloud SDK/gsutil auth config. Later files override earlier files.
    append_boto_path "${BOTO_PATH:-}"
    append_boto_path "${BOTO_CONFIG:-}"
    if [ -r /etc/boto.cfg ]; then
      append_boto_path /etc/boto.cfg
    fi
    if [ -n "${HOME:-}" ] && [ -r "$HOME/.boto" ]; then
      append_boto_path "$HOME/.boto"
    fi
    append_boto_path "$boto_config"

    export BOTO_PATH="$new_boto_path"
    unset BOTO_CONFIG
    export GSUTIL_ENCRYPTION_CONFIGURED=1
    unset GS_ENCRYPTION_KEY

    key_value=""
  fi
}

trap 'emit_error; cleanup; exit 143' TERM
trap 'emit_error; cleanup; exit 130' INT

configure_gsutil_encryption "$@"
rc=$?
if [ "$rc" -ne 0 ]; then
  emit_error
  cleanup
  exit "$rc"
fi


python3 -u /usr/local/bin/gs_bucket_sync.py "$@"
rc=$?

if [ "$rc" -ne 0 ] && [ ! -s "$status_file" ]; then
  emit_error
fi

cleanup
exit "$rc"
