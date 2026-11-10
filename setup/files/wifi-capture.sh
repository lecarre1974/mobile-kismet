#!/bin/bash
# Passive all-band Wi-Fi capture. airodump-ng hops channels and writes a summary
# CSV; tcpdump writes full frames (radiotap) to rotating pcap files.
# Default: hop every enabled channel. Focus: hop only the channels of chosen
# SSIDs/BSSIDs so the radio dwells on them. Either way it only listens.
# Run by wifi-capture.service, which restarts this script if it exits.
set -u
umask 022
export PATH=/usr/sbin:/usr/bin:/sbin:/bin

BASE=/var/lib/capture
RUN=/run/capture
OWNER=user
MIN_FREE_MB=2048       # stop capturing below this
WARN_FREE_MB=5120      # SOS light below this
WARN_BATTERY=20        # SOS light below this percent when not charging
ROTATE_SECS=300
HOP_MS=200
FOCUS_TARGETS="$RUN/focus-targets"

mkdir -p "$BASE" "$RUN"
chown "$OWNER:$OWNER" "$BASE"

set_state() { printf '%s\n' "$1" > "$RUN/state"; /usr/local/bin/led-update; }

find_adapter() {
    local i d
    for i in /sys/class/net/*; do
        d=$(readlink "$i/device/driver" 2>/dev/null) || continue
        [ "$(basename "$d")" = mt7921u ] && { basename "$i"; return 0; }
    done
    return 1
}

free_mb() { df -Pm "$BASE" | awk 'NR==2 {print $4}'; }

pisugar_get() {
    local out
    exec 3<>/dev/tcp/127.0.0.1/8423 || return 1
    printf 'get %s\n' "$1" >&3
    out=$(timeout 3 head -1 <&3)
    exec 3>&-
    printf '%s\n' "${out#*: }"
}

check_warning() {
    local w="" bat plugged old
    [ "$(free_mb)" -lt "$WARN_FREE_MB" ] && w="SD card nearly full"
    bat=$(pisugar_get battery 2>/dev/null)
    plugged=$(pisugar_get battery_power_plugged 2>/dev/null)
    if [ -n "$bat" ] && [ "$plugged" != true ] && \
       awk -v b="$bat" -v t="$WARN_BATTERY" 'BEGIN {exit !(b+0 < t)}'; then
        w="${w:+$w; }battery low (${bat%%.*}%)"
    fi
    old=$(cat "$RUN/warning" 2>/dev/null)
    [ "$w" != "$old" ] && { printf '%s' "$w" > "$RUN/warning"; /usr/local/bin/led-update; }
}

TP="" AP=""
stop_children() {
    [ -n "$TP" ] && kill -INT "$TP" 2>/dev/null
    [ -n "$AP" ] && kill -INT "$AP" 2>/dev/null
    sleep 2
    [ -n "$AP" ] && kill -9 "$AP" 2>/dev/null
    wait 2>/dev/null
    TP="" AP=""
}
trap 'stop_children; set_state stopped; exit 0' TERM INT

# ---- bring up the adapter ----
set_state waiting-for-adapter
IF=""
for _ in $(seq 1 90); do IF=$(find_adapter) && break; sleep 2; done
[ -z "$IF" ] && { set_state no-adapter; echo "capture adapter not found" >&2; exit 1; }
printf '%s\n' "$IF" > "$RUN/iface"

while [ "$(free_mb)" -lt "$MIN_FREE_MB" ]; do set_state disk-full; sleep 60; done

ip link set "$IF" down
iw dev "$IF" set type monitor || { set_state adapter-error; exit 1; }
ip link set "$IF" up || { set_state adapter-error; exit 1; }
PHY=$(cat "/sys/class/net/$IF/phy80211/name")

# channel -> frequency map (enabled channels only)
declare -A CH2FREQ
while read -r f c; do CH2FREQ[$c]=$f; done < <(
    iw phy "$PHY" info | awk '/MHz \[/ && !/disabled/ {
        f=$2; sub(/\..*/,"",f);
        for (i=1;i<=NF;i++) if ($i ~ /^\[[0-9]+\]$/) { c=$i; gsub(/[][]/,"",c) }
        print f, c }'
)
FREQS_ALL=$(printf '%s\n' "${CH2FREQ[@]}" | sort -un | paste -sd,)
[ -z "$FREQS_ALL" ] && { set_state adapter-error; echo "no usable frequencies" >&2; exit 1; }

# ---- choose focus or all-band ----
FOCUSED=0
PENDING=""
FREQS="$FREQS_ALL"
PREFIX="cap"
rm -f "$RUN/focus"
if [ -s "$FOCUS_TARGETS" ]; then
    chans=""
    while read -r kind rest; do
        case "$kind" in
            chan) f=${CH2FREQ[$rest]:-}; [ -n "$f" ] && chans="${chans:+$chans,}$f" ;;
            pending) PENDING="${PENDING:+$PENDING; }$rest" ;;
        esac
    done < <(/usr/bin/python3 -I /usr/local/bin/focus-resolve.py "$BASE" "$FOCUS_TARGETS")
    tgtcount=$(grep -c . "$FOCUS_TARGETS")
    if [ -n "$chans" ]; then
        FOCUSED=1
        FREQS="$chans"
        PREFIX="focus"
        printf 'focused on %d target(s)%s; channels: %s' \
            "$tgtcount" "${PENDING:+, pending ($PENDING)}" \
            "$(echo "$chans" | tr ',' ' ')" > "$RUN/focus"
    else
        # targets set but none seen yet: stay all-band to discover them, then restart
        printf 'focus pending: %s not seen yet, scanning all channels' "$PENDING" > "$RUN/focus"
    fi
fi

echo "$FREQS" | tr , '\n' | awk '$1<3000{a++} $1>=5000&&$1<5900{b++} $1>=5900{c++}
    END {printf "%d on 2.4 GHz, %d on 5 GHz, %d on 6 GHz\n", a, b, c}' > "$RUN/hop"

SESSION="$BASE/$PREFIX-$(date +%Y%m%d-%H%M%S)"
install -d -o "$OWNER" -g "$OWNER" -m 755 "$SESSION"
printf '%s\n' "$SESSION" > "$RUN/session"

airodump-ng "$IF" --background 1 -C "$FREQS" -f "$HOP_MS" \
    --write "$SESSION/summary" --output-format csv --write-interval 30 \
    </dev/null >/dev/null 2>&1 &
AP=$!
tcpdump -i "$IF" -n -s 0 -U -Z "$OWNER" -G "$ROTATE_SECS" \
    -w "$SESSION/${PREFIX}-%Y%m%d-%H%M%S.pcap" </dev/null 2>"$RUN/tcpdump.log" &
TP=$!

: > "$RUN/warning"
set_state capturing
check_warning

# ---- supervise ----
tick=0
while sleep 10; do
    tick=$((tick + 1))
    if ! kill -0 "$TP" 2>/dev/null || ! kill -0 "$AP" 2>/dev/null; then
        echo "capture process exited" >&2; break
    fi
    [ ! -e "/sys/class/net/$IF" ] && { echo "adapter gone" >&2; break; }
    # A pending focus target has now been seen: restart to lock onto its channel.
    if [ -n "$PENDING" ] && [ $((tick % 3)) -eq 0 ] && [ -s "$FOCUS_TARGETS" ]; then
        if /usr/bin/python3 -I /usr/local/bin/focus-resolve.py "$BASE" "$FOCUS_TARGETS" | grep -q '^chan '; then
            echo "focus target now visible, restarting to lock on" >&2
            stop_children; set_state restarting; exit 1
        fi
    fi
    if [ $((tick % 6)) -eq 0 ]; then
        check_warning
        if [ "$(free_mb)" -lt "$MIN_FREE_MB" ]; then
            echo "disk nearly full, stopping" >&2
            stop_children; set_state disk-full
            while [ "$(free_mb)" -lt "$MIN_FREE_MB" ]; do sleep 60; done
            exit 0
        fi
    fi
done

stop_children
set_state restarting
exit 1
