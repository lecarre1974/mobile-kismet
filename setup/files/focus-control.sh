#!/bin/bash
# Sets or clears the focus target list, then restarts capture to apply it.
# Usage:
#   focus-control.sh set     # reads targets on stdin, one per line:
#                            #   bssid AA:BB:CC:DD:EE:FF
#                            #   ssid Some Network Name
#   focus-control.sh clear
# Targets live in tmpfs (/run), so a power-cycle always returns to all channels.
set -u
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
RUN=/run/capture
TARGETS="$RUN/focus-targets"
mkdir -p "$RUN"

valid_mac() { printf '%s' "$1" | grep -Eqi '^([0-9a-f]{2}:){5}[0-9a-f]{2}$'; }

case "${1:-}" in
    set)
        tmp=$(mktemp "$RUN/focus.XXXXXX") || exit 1
        n=0
        while IFS= read -r line; do
            kind=${line%% *}; val=${line#* }
            case "$kind" in
                bssid)
                    valid_mac "$val" || continue
                    printf 'bssid %s\n' "$(printf '%s' "$val" | tr 'a-f' 'A-F')" >> "$tmp"
                    n=$((n + 1)) ;;
                ssid)
                    # one line, printable, 1..32 chars
                    val=$(printf '%s' "$val" | tr -d '\000-\037' | cut -c1-32)
                    [ -n "$val" ] || continue
                    printf 'ssid %s\n' "$val" >> "$tmp"
                    n=$((n + 1)) ;;
            esac
            [ "$n" -ge 32 ] && break
        done
        if [ "$n" -eq 0 ]; then
            rm -f "$tmp"
            echo "no valid targets" >&2
            exit 1
        fi
        sort -u "$tmp" > "$TARGETS"
        rm -f "$tmp"
        echo "set $n target(s)"
        ;;
    clear)
        rm -f "$TARGETS"
        echo "cleared"
        ;;
    *)
        echo "usage: focus-control.sh set|clear" >&2
        exit 2
        ;;
esac

systemctl restart wifi-capture.service
