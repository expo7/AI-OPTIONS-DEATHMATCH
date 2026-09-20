#!/usr/bin/env bash
set -euo pipefail
[[ $(id -u) -eq 0 && $(hostname) == ai-options-deathmatch ]] || { echo 'Unexpected execution identity or host' >&2; exit 1; }
[[ $(pwd -P) == /opt/ai-options-deathmatch ]] || { echo 'Run from Deathmatch repository root' >&2; exit 1; }
[[ $(stat -c %U .) == deploy ]] || { echo 'Unexpected repository owner' >&2; exit 1; }
install -o root -g root -m 755 deploy/release.sh /usr/local/sbin/deathmatch-release
printf 'deploy ALL=(root) NOPASSWD: /usr/local/sbin/deathmatch-release *\n' >/etc/sudoers.d/deathmatch-release
chmod 440 /etc/sudoers.d/deathmatch-release
visudo -cf /etc/sudoers.d/deathmatch-release
echo 'Release command installed for deploy user'
