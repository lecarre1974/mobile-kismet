#!/bin/bash
# Stage the capture update onto a finalized unit's SD card from macOS.
# Run with the card's boot partition mounted at /Volumes/bootfs.
# Copies updated files + apply-update.sh to the FAT boot partition and adds a
# one-shot boot hook; the Pi installs them on next boot, then reboots clean.
set -eu
V=/Volumes/bootfs
P=$(cd "$(dirname "$0")" && pwd)
BK=$P/sd-backup

[ -f "$V/cmdline.txt" ] || { echo "No $V/cmdline.txt - is the card's boot partition mounted?" >&2; exit 1; }
grep -q 'root=PARTUUID=fd148819-02' "$V/cmdline.txt" || { echo "This does not look like the unit's card (PARTUUID mismatch)." >&2; exit 1; }
grep -q 'systemd.run=' "$V/cmdline.txt" && { echo "A boot hook is already present in cmdline.txt; aborting." >&2; exit 1; }

mkdir -p "$BK"; cp "$V/cmdline.txt" "$BK/cmdline.txt.preupdate"
rm -rf "$V/update"; mkdir -p "$V/update"
for f in wifi-capture.sh led-update focus-control.sh focus-resolve.py capture-status.py; do
    cp "$P/files/$f" "$V/update/$f"
done
cp "$P/apply-update.sh" "$V/apply-update.sh"

# strip any CR that a copy might have introduced
for f in "$V"/update/* "$V/apply-update.sh"; do perl -pi -e 's/\r$//' "$f"; done

perl -pi -e 's/\s*$/ systemd.run=\/boot\/firmware\/apply-update.sh systemd.run_success_action=reboot systemd.unit=kernel-command-line.target\n/' "$V/cmdline.txt"
rm -f "$V/cmdline.txt.bak"; dot_clean -m "$V" 2>/dev/null || true; sync

echo "--- cmdline now ---"; cat "$V/cmdline.txt"
L=$(wc -l < "$V/cmdline.txt" | tr -d ' '); echo "cmdline lines: $L"; [ "$L" -le 1 ] || { echo "ERROR: cmdline is not a single line" >&2; exit 1; }
grep -q 'root=PARTUUID=fd148819-02' "$V/cmdline.txt"
echo "--- staged files ---"; ls -la "$V/update"; ls -la "$V/apply-update.sh"
for f in "$V"/update/*; do bash -n "$f" 2>/dev/null || python3 -I -c "import ast;ast.parse(open('$f').read())" 2>/dev/null && echo "ok $(basename "$f")" || echo "unchecked $(basename "$f")"; done
sync; diskutil eject "$V"
echo "STAGED. Put the card back in the Pi and power on."
