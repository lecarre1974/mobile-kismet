#!/bin/bash
# One-shot update for a finalized unit. Placed on the boot (FAT) partition and
# run once at boot via systemd.run; installs updated capture files from
# /boot/firmware/update/ onto the system, then removes itself and reboots.
exec >/boot/firmware/focus-install.log 2>&1
set -x
date
B=/boot/firmware
U=$B/update

# Remove the boot hook first, so any failure still ends in a normal boot.
sed -i -E 's/ systemd\.run=[^ ]*//; s/ systemd\.run_success_action=[^ ]*//; s/ systemd\.unit=kernel-command-line\.target//' "$B/cmdline.txt"
cat "$B/cmdline.txt"

install -m 755 "$U/wifi-capture.sh"   /usr/local/bin/wifi-capture.sh
install -m 755 "$U/led-update"        /usr/local/bin/led-update
install -m 755 "$U/focus-control.sh"  /usr/local/bin/focus-control.sh
install -m 755 "$U/focus-resolve.py"  /usr/local/bin/focus-resolve.py
install -m 755 "$U/capture-status.py" /usr/local/bin/capture-status.py

cat > /etc/sudoers.d/080-capture-page <<'EOF'
user ALL=(root) NOPASSWD: /usr/bin/systemctl start wifi-capture.service, /usr/bin/systemctl stop wifi-capture.service, /usr/local/bin/checkin-toggle.sh off-async, /usr/local/bin/checkin-toggle.sh extend, /usr/local/bin/focus-control.sh set, /usr/local/bin/focus-control.sh clear
EOF
chmod 440 /etc/sudoers.d/080-capture-page
if ! visudo -cf /etc/sudoers.d/080-capture-page; then
    echo "SUDOERS INVALID - reverting to safe minimal rule"
    cat > /etc/sudoers.d/080-capture-page <<'EOF'
user ALL=(root) NOPASSWD: /usr/bin/systemctl start wifi-capture.service, /usr/bin/systemctl stop wifi-capture.service, /usr/local/bin/checkin-toggle.sh off-async, /usr/local/bin/checkin-toggle.sh extend
EOF
    chmod 440 /etc/sudoers.d/080-capture-page
fi

# syntax self-check of the installed scripts
echo "VERIFY wifi-capture: $(bash -n /usr/local/bin/wifi-capture.sh && echo ok || echo FAIL)"
echo "VERIFY focus-control: $(bash -n /usr/local/bin/focus-control.sh && echo ok || echo FAIL)"
echo "VERIFY status page: $(python3 -I -c 'import ast;ast.parse(open("/usr/local/bin/capture-status.py").read())' && echo ok || echo FAIL)"
echo "VERIFY focus-resolve: $(python3 -I -c 'import ast;ast.parse(open("/usr/local/bin/focus-resolve.py").read())' && echo ok || echo FAIL)"

systemctl daemon-reload
systemctl restart wifi-capture.service
sleep 20
echo "capture state after restart: $(cat /run/capture/state 2>/dev/null)"
systemctl is-active wifi-capture.service

rm -rf "$U" "$B/apply-update.sh"
sync
date
echo "update complete"
exit 0
