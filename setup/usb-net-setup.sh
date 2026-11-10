#!/bin/sh
# One-shot: runs at next boot via systemd.run, makes usb0 come up under
# NetworkManager, removes itself from cmdline.txt, then the Pi reboots.
exec >/boot/firmware/usb-net-setup.log 2>&1
set -x
date

# Remove the boot hook first so any failure below still ends in a normal boot.
sed -i -E 's/ systemd\.run=[^ ]*//; s/ systemd\.run_success_action=[^ ]*//; s/ systemd\.unit=kernel-command-line\.target//' /boot/firmware/cmdline.txt
cat /boot/firmware/cmdline.txt

# Diagnostics, readable from the Mac if this does not work.
cat /etc/os-release
uname -a
hostname
getent passwd user
systemctl is-enabled ssh avahi-daemon NetworkManager cloud-init
grep -n -i gadget /usr/lib/udev/rules.d/*nm-unmanaged* /lib/udev/rules.d/*nm-unmanaged*
NetworkManager --version
ip link show usb0

# Let NetworkManager manage the USB gadget interface.
cat > /etc/udev/rules.d/90-usb0-nm-managed.rules <<'EOF'
SUBSYSTEM=="net", KERNEL=="usb0", ENV{NM_UNMANAGED}="0"
EOF

cat > /etc/NetworkManager/system-connections/usb0.nmconnection <<'EOF'
[connection]
id=usb0
type=ethernet
interface-name=usb0
autoconnect=true

[ethernet]

[ipv4]
method=auto
may-fail=true
dhcp-timeout=2147483647

[ipv6]
method=link-local
EOF
chown root:root /etc/NetworkManager/system-connections/usb0.nmconnection
chmod 600 /etc/NetworkManager/system-connections/usb0.nmconnection

# Fallback: raise the link even if NetworkManager skips it (gives IPv6 link-local).
cat > /etc/systemd/system/usb0-up.service <<'EOF'
[Unit]
Description=Bring up USB gadget link
After=NetworkManager.service
ConditionPathExists=/sys/class/net/usb0

[Service]
Type=oneshot
ExecStart=-/usr/sbin/ip link set usb0 up

[Install]
WantedBy=multi-user.target
EOF
systemctl enable usb0-up.service
systemctl enable ssh

rm -f /boot/firmware/usb-net-setup.sh
sync
date
exit 0
