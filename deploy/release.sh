#!/usr/bin/env bash
set -euo pipefail

# Root-owned copy at /usr/local/sbin/deathmatch-release; callable by deploy.
revision=${1:-}
[[ $(id -u) -eq 0 && $(hostname) == ai-options-deathmatch ]] || { echo 'Unexpected execution identity or host' >&2; exit 1; }
[[ $revision =~ ^[0-9a-f]{40}$ ]] || { echo 'Expected a full commit SHA' >&2; exit 1; }
repo=/opt/ai-options-deathmatch
[[ $(stat -c %U "$repo") == deploy ]] || { echo 'Unexpected repository owner' >&2; exit 1; }
exec 9>/run/lock/deathmatch-release.lock
flock -n 9 || { echo 'Another release is running' >&2; exit 1; }

git_deploy() { runuser -u deploy -- git -C "$repo" "$@"; }
[[ -z $(git_deploy status --porcelain) ]] || { echo 'Refusing dirty production tree' >&2; exit 1; }
git_deploy fetch --no-tags origin master
git_deploy cat-file -e "$revision^{commit}"
git_deploy merge-base --is-ancestor "$revision" refs/remotes/origin/master || { echo 'Commit not on origin/master' >&2; exit 1; }

previous=$(git_deploy rev-parse HEAD)
git_deploy checkout --detach "$revision"
printf 'APP_COMMIT=%s\nRESULTS_PUBLIC=true\nLEDGER_PATH=/var/lib/ai-options-deathmatch-public/results.json\n' "$revision" >/etc/ai-options-deathmatch.env
chmod 644 /etc/ai-options-deathmatch.env
systemctl restart deathmatch

healthy=false
for attempt in {1..20}; do
    if curl -fsS http://127.0.0.1:8000/healthz 2>/dev/null | grep -Fq "\"commit\": \"$revision\""; then
        healthy=true
        break
    fi
    sleep 1
done
if [[ $healthy != true ]]; then
    echo "Health check failed; previous revision was $previous. Diagnose before another release." >&2
    exit 1
fi
echo "Deployed $revision (previous: $previous)"
