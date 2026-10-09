#!/usr/bin/env bash
#
# Deploy one commit of the API to an instance of the application.
#
# The CI calls it through an SSH key restricted to this command, which receives
# the commit SHA in SSH_ORIGINAL_COMMAND. An administrator can run it by hand:
#
#     sudo -u cdf3 cdf3-release-back preprod <commit-sha>
#
# Every commit gets its own release directory and virtual environment. The
# database is migrated before the switch, so migrations must stay compatible
# with the previous release (see CLAUDE.md). The `current` link is switched
# atomically, and a release that fails its health check is rolled back.
set -euo pipefail

readonly APP_ROOT=/var/www/cdf3
readonly KEEP_RELEASES=3
readonly TAG=cdf3-release-back

# Details go to the journal (journalctl -t cdf3-release-back); the caller only
# gets one status line, as the logs of a public CI are readable by anyone.
exec 3>&1
exec 1> >(systemd-cat -t "$TAG") 2>&1
# A dropped SSH connection must not stop a deployment halfway through.
trap '' HUP PIPE

fail() {
    echo "error: $*"
    printf 'Deployment failed: %s\n' "$*" >&3 || true
    exit 1
}

main() {
    local instance=${1:-} sha=${2:-${SSH_ORIGINAL_COMMAND:-}}
    [[ $instance =~ ^(preprod|prod)$ ]] || fail "unknown instance '$instance'"
    [[ $sha =~ ^[0-9a-f]{40}$ ]] || fail "a full commit SHA is expected"

    local base=$APP_ROOT/$instance
    local app=$base/back
    local release=$app/releases/$sha
    local env_file=$base/shared/back.env
    export HOME=/var/lib/cdf3

    exec 9>"$base/deploy.lock"
    flock -w 600 9 || fail "another deployment is still running"

    echo "deploying $sha to $instance"
    git -C "$app/repo.git" fetch --quiet origin main
    git -C "$app/repo.git" merge-base --is-ancestor "$sha" FETCH_HEAD ||
        fail "$sha is not a commit of main"

    if [[ ! -d $release ]]; then
        rm -rf "$release.partial"
        mkdir "$release.partial"
        git -C "$app/repo.git" archive "$sha" | tar -x -C "$release.partial"
        printf '%s\n' "$sha" >"$release.partial/REVISION"
        ln -s "$env_file" "$release.partial/.env"
        mv "$release.partial" "$release"
    fi

    (cd "$release" && uv sync --locked --no-dev --quiet)
    manage "$release" check --deploy --fail-level WARNING
    manage "$release" migrate --noinput
    # The cache table the throttles count in; like migrate, it only creates
    # what is missing.
    manage "$release" createcachetable
    manage "$release" collectstatic --noinput --verbosity 0

    local previous
    previous=$(readlink -f "$app/current" || true)
    activate "$app" "$release"
    sudo systemctl restart "cdf3-api@$instance.service"

    if ! healthy "$env_file" "$sha"; then
        [[ -n $previous && $previous != "$release" ]] || fail "$sha did not pass its health check"
        local previous_sha
        previous_sha=$(basename "$previous")
        echo "health check failed, rolling back to $previous_sha"
        activate "$app" "$previous"
        sudo systemctl restart "cdf3-api@$instance.service"
        # The caller must know whether the service is back, not only that the
        # deployment failed.
        healthy "$env_file" "$previous_sha" ||
            fail "$sha did not pass its health check, nor did $previous_sha after the rollback"
        fail "$sha did not pass its health check, rolled back to $previous_sha"
    fi

    prune "$app/releases" "$release"
    echo "deployed $sha"
    printf 'Deployed %s to %s\n' "$sha" "$instance" >&3 || true
}

# Run a management command of a release with the production settings.
manage() {
    local release=$1
    shift
    (cd "$release" && DJANGO_SETTINGS_MODULE=config.settings.prod .venv/bin/python manage.py "$@")
}

# Point the `current` link at a release, atomically (rename over the old link).
activate() {
    local app=$1 target=$2
    ln -sfn "$target" "$app/current.next"
    mv -T "$app/current.next" "$app/current"
}

# The API must answer with a reachable database and the expected release.
healthy() {
    local env_file=$1 sha=$2 bind attempt body
    bind=$(sed -n 's/^GUNICORN_BIND=//p' "$env_file")
    for attempt in $(seq 15); do
        if body=$(curl -fsS --max-time 5 "http://$bind/api/health" 2>&1) &&
            python3 -c '
import json, sys
expected = {"database": True, "release": sys.argv[2]}
try:
    sys.exit(0 if json.loads(sys.argv[1]) == expected else 1)
except ValueError:
    sys.exit(1)
' "$body" "$sha"; then
            return 0
        fi
        echo "health check $attempt failed (${body:-no answer}), retrying"
        sleep 2
    done
    return 1
}

# Keep the most recent releases, never the one just deployed.
prune() {
    local releases=$1 keep=$2 dir
    find "$releases" -mindepth 1 -maxdepth 1 -type d ! -name '*.partial' -printf '%T@ %p\n' |
        sort -rn | tail -n +$((KEEP_RELEASES + 1)) | cut -d' ' -f2- |
        while read -r dir; do
            [[ $dir == "$keep" ]] || rm -rf "$dir"
        done
}

main "$@"
