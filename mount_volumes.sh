#!/bin/bash
#
# ClipStage v5.0 - mount NAS volumes over SMB before indexing / starting the API.
#
# clipstage_env.sh's mount_volumes() already calls this file if it exists (from
# start_clipstage.sh, nightly_index.sh and manual_index.sh) - nothing else to wire up.
# If this file is absent, those scripts just assume the volumes are already mounted,
# so it's always safe to add or remove this file.
#
# Reads from .env (already loaded into the environment by clipstage_env.sh by the time
# this runs) — a DOMAIN NAS ACCOUNT, separate from the Supabase logins editors use to
# sign in to the app itself:
#
#   CLIPSTAGE_NAS_HOST       NAS hostname or IP (required)
#   CLIPSTAGE_NAS_DOMAIN     AD/Windows domain for the account (optional - omit if none)
#   CLIPSTAGE_NAS_USER       Domain username (required)
#   CLIPSTAGE_NAS_PASSWORD   Domain password (required)
#   CLIPSTAGE_SCAN_VOLUMES   Comma list of share names to mount (defaults to the same
#                             list clipstage_config.py scans, so it's usually already
#                             set in your .env and nothing extra to configure here)
#
# One NAS host, same account, for every share in CLIPSTAGE_SCAN_VOLUMES. Each share is
# mounted at /Volumes/<share name> — exactly where indexer.py expects to find it.
# Already-mounted shares are left alone; this never unmounts anything. Safe to re-run.
#
# Security note: the password is handed to mount_smbfs via the $PASSWD environment
# variable (its documented password source) instead of embedding it in the command
# line, so it does not show up in `ps` output for other users on this Mac. It still
# lives in plain text in .env, same as TYPESENSE_KEY and the Supabase key — .env is
# already gitignored; also run `chmod 600 .env` so only this Mac's owner can read it.

set -u

NAS_HOST="${CLIPSTAGE_NAS_HOST:-}"
NAS_DOMAIN="${CLIPSTAGE_NAS_DOMAIN:-}"
NAS_USER="${CLIPSTAGE_NAS_USER:-}"
NAS_PASSWORD="${CLIPSTAGE_NAS_PASSWORD:-}"

if [ -z "$NAS_HOST" ] || [ -z "$NAS_USER" ] || [ -z "$NAS_PASSWORD" ]; then
    echo "mount_volumes.sh: CLIPSTAGE_NAS_HOST / CLIPSTAGE_NAS_USER / CLIPSTAGE_NAS_PASSWORD" \
         "not all set in .env - skipping automatic mount (assuming volumes are already mounted)."
    exit 0
fi

# Share list: CLIPSTAGE_SCAN_VOLUMES if set (same comma list clipstage_config.py reads),
# else the built-in defaults, so this stays in sync with what the indexer actually scans.
IFS=',' read -r -a VOLS <<< "${CLIPSTAGE_SCAN_VOLUMES:-EDIT,EDIT2,INGEST,PLAYOUT,DIGITAL,SHARE FOLDER,TRANSCODER}"

# URL-encode a piece of a smb:// URL (username/domain/share names can contain spaces,
# e.g. "SHARE FOLDER" - mount_smbfs's URL form breaks on raw spaces/@/:/%).
_urlenc() {
    local s="$1" out="" c i
    for (( i = 0; i < ${#s}; i++ )); do
        c="${s:$i:1}"
        case "$c" in
            [a-zA-Z0-9.~_-]) out+="$c" ;;
            *) out+=$(printf '%%%02X' "'$c") ;;
        esac
    done
    printf '%s' "$out"
}

ENC_USER="$(_urlenc "$NAS_USER")"
AUTH="$ENC_USER"
[ -n "$NAS_DOMAIN" ] && AUTH="$(_urlenc "$NAS_DOMAIN");$ENC_USER"

export PASSWD="$NAS_PASSWORD"   # mount_smbfs's documented password source - keeps it off argv/`ps`

ok=0 failed=0
for vol in "${VOLS[@]}"; do
    vol="$(echo "$vol" | sed 's/^ *//;s/ *$//')"   # trim whitespace from the comma list
    [ -z "$vol" ] && continue
    mountpoint="/Volumes/$vol"

    if mount | grep -qF " on $mountpoint "; then
        echo "  $vol: OK (already mounted)"
        ok=$((ok + 1))
        continue
    fi

    enc_vol="$(_urlenc "$vol")"
    mounted=0
    : > /tmp/clipstage_mount_err
    if mkdir -p "$mountpoint" 2>/dev/null; then
        # Normal path (works when /Volumes is writable, e.g. admin/sudo-less setups)
        if mount_smbfs "//$AUTH@$NAS_HOST/$enc_vol" "$mountpoint" 2>/tmp/clipstage_mount_err; then
            mounted=1
        else
            rmdir "$mountpoint" 2>/dev/null   # remove the empty mountpoint we just created
        fi
    else
        # /Volumes is root-owned: once macOS removes /Volumes/<share> (e.g. after an
        # unmount) a normal user can't recreate it for mount_smbfs. Ask the system to
        # mount it the way Finder does (open smb://; osascript segfaults under launchd) - it creates /Volumes/<share> itself.
        enc_pass="$(_urlenc "$NAS_PASSWORD")"
        /usr/bin/open -g -j "smb://$AUTH:$enc_pass@$NAS_HOST/$enc_vol" \
            >/dev/null 2>/tmp/clipstage_mount_err
        for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do      # wait up to ~12s for it to appear
            mount | grep -qF " on $mountpoint " && { mounted=1; break; }
            sleep 1
        done
        [ "$mounted" -eq 0 ] && echo "open smb:// did not mount it within 12s" >>/tmp/clipstage_mount_err
    fi

    if [ "$mounted" -eq 1 ]; then
        echo "  $vol: RECONNECTED (was missing, mounted it just now)"
        ok=$((ok + 1))
    else
        echo "  $vol: FAILED - $(cat /tmp/clipstage_mount_err 2>/dev/null)"
        failed=$((failed + 1))
    fi
done

unset PASSWD
rm -f /tmp/clipstage_mount_err

echo "mount_volumes.sh: $ok mounted/already mounted, $failed failed"
[ "$failed" -gt 0 ] && exit 1
exit 0
