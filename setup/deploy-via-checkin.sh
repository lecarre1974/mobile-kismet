#!/bin/bash
# Push the updated status page to a FINALIZED unit over its check-in network,
# with NO SD card and NO reboot. Run on the Mac while joined to the unit's
# check-in Wi-Fi. Capture (wifi-capture.service) is left untouched.
#
#   1. On the unit: double tap the USB-port button, wait for the fast blink.
#   2. On the Mac: join the check-in Wi-Fi, then run this script.
#   3. Type the unit's login password when asked (once to connect, once for sudo).
#
# It verifies the new file parses ON the unit, backs up the current one, installs
# it, restarts only the status-page service, and rolls back if that fails.
# A transcript is written to a temp file, printed at the end.
set -u
P=$(cd "$(dirname "$0")" && pwd)
SRC="$P/files/capture-status.py"
D=$(mktemp -d "${TMPDIR:-/tmp}/silent-deploy.XXXXXX")
LOG="$D/deploy-output.txt"
H=user@10.42.0.1
S=(-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$D/unit_known_hosts"
   -o ControlMaster=auto -o ControlPath="$D/dm-%r@%h" -o ControlPersist=180 -o ConnectTimeout=10)

[ -f "$SRC" ] || { echo "Cannot find $SRC" >&2; exit 1; }
python3 -c "import ast;ast.parse(open('$SRC').read())" || { echo "Local file does not parse; aborting." >&2; exit 1; }

exec > >(tee "$LOG") 2>&1
echo "== deploy $(date) =="
echo "You'll be asked for the unit's login password (once to connect, once for sudo)."

# 1) open the shared connection + copy the new file to the unit's /tmp (one prompt)
scp "${S[@]}" "$SRC" "$H:/tmp/capture-status.new" || { echo "Copy failed. Is this machine on the unit's check-in Wi-Fi?"; exit 1; }

# 2) verify + install + restart, with rollback (sudo prompts once over the tty)
ssh -t "${S[@]}" "$H" '
set -e
echo "-- verifying new file parses on the unit --"
python3 -c "import ast;ast.parse(open(\"/tmp/capture-status.new\").read())" && echo "parse OK"
TS=$(date +%Y%m%d-%H%M%S)
echo "-- backing up and installing (sudo) --"
sudo cp -a /usr/local/bin/capture-status.py "/tmp/capture-status.bak-$TS"
sudo install -m 755 /tmp/capture-status.new /usr/local/bin/capture-status.py
echo "-- restarting the status page --"
sudo systemctl restart capture-status.service
sleep 2
if systemctl is-active --quiet capture-status.service; then
    echo "RESULT: status page updated and running."
    grep -c "Paste one or more MACs" /usr/local/bin/capture-status.py >/dev/null && echo "new multi-paste page confirmed installed."
else
    echo "RESULT: new page failed to start - ROLLING BACK."
    sudo install -m 755 "/tmp/capture-status.bak-$TS" /usr/local/bin/capture-status.py
    sudo systemctl restart capture-status.service
    systemctl is-active capture-status.service && echo "rolled back to the previous page."
fi
rm -f /tmp/capture-status.new
'
ssh "${S[@]}" -O exit "$H" 2>/dev/null
echo "== done. The page reloads next time you open 10.42.0.1 on the phone. =="
echo "Transcript: $LOG"
