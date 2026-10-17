#!/usr/bin/env bash
# Configure git to sign commits and tags with the SSH key held by the ssh-agent
# that VS Code forwards into the container.
#
# - Only the *container's* ~/.gitconfig is changed, never the host's.
# - No key path and no private key is involved: git is given the public key itself
#   ("key::<public key>") and asks the agent to do the signing.
# - Runs on every container start (postStartCommand), so a changed or reloaded key
#   is picked up, and a stale `user.signingkey` copied from the host is replaced.
set -euo pipefail

warn() { echo "setup-git-signing: $*" >&2; }

# Identity comes from the host's .gitconfig, which VS Code copies into the container.
for setting in user.name user.email; do
    git config --global --get "${setting}" >/dev/null || warn "${setting} is not set (set it in your host's global git config)"
done

keys="$(ssh-add -L 2>/dev/null || true)"

# Prefer an ed25519 key; otherwise take the first key the agent offers.
key="$(grep -m1 '^ssh-ed25519 ' <<<"${keys}" || true)"
if [[ -z "${key}" ]]; then
    key="$(grep -m1 -E '^(ssh|ecdsa|sk)-' <<<"${keys}" || true)"
fi

if [[ -z "${key}" ]]; then
    # Drop a stale host path (it would not exist here) but keep signing switched on,
    # so an unsigned commit fails at once instead of being rejected at push time.
    git config --global --unset user.signingkey || true
    warn "no key found in the ssh-agent, so commits cannot be signed."
    warn "Start the agent on the host, run 'ssh-add', then rebuild or restart the container."
    exit 0
fi

git config --global gpg.format ssh
git config --global user.signingkey "key::${key}"
git config --global commit.gpgsign true
git config --global tag.gpgsign true
echo "setup-git-signing: signing with ${key%% *} key from the ssh-agent"
