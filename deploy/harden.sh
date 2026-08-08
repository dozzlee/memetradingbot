#!/usr/bin/env bash
# Netcup VPS hardening per PRD §8 step 2. Run once as root on a fresh box,
# AFTER you've copied your SSH public key to the server (ssh-copy-id) —
# this script disables password auth, so confirm key-based login works
# in a separate session before closing this one.
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
  echo "run as root" >&2
  exit 1
fi

echo "==> Creating non-root user 'vanguard' (if missing)"
id -u vanguard &>/dev/null || adduser --disabled-password --gecos "" vanguard
mkdir -p /home/vanguard/.ssh
cp -n /root/.ssh/authorized_keys /home/vanguard/.ssh/authorized_keys 2>/dev/null || true
chown -R vanguard:vanguard /home/vanguard/.ssh
chmod 700 /home/vanguard/.ssh
chmod 600 /home/vanguard/.ssh/authorized_keys 2>/dev/null || true

echo "==> SSH: key-only auth, no root login"
sed -i \
  -e 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' \
  -e 's/^#\?PermitRootLogin.*/PermitRootLogin no/' \
  -e 's/^#\?ChallengeResponseAuthentication.*/ChallengeResponseAuthentication no/' \
  /etc/ssh/sshd_config
systemctl restart sshd

echo "==> Firewall (ufw): SSH only, deny everything else"
apt-get update -qq && apt-get install -y -qq ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw --force enable

echo "==> Unattended security upgrades"
apt-get install -y -qq unattended-upgrades
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "==> Done. Verify you can SSH in as 'vanguard' with your key BEFORE closing this session."
echo "    Dashboard should stay bound to 127.0.0.1 — see README for tunnel/reverse-proxy notes."
