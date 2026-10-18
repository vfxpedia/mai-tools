#!/usr/bin/env bash
# User-owned runtime only. Does not change existing Codex, login files or PATH.
set -euo pipefail
if [ "$#" -ne 2 ]; then
  printf 'Usage: bash bootstrap-linux.sh PACKAGE.tgz codex:ACCOUNT\n' >&2
  exit 2
fi
package_path=$(realpath "$1")
account_alias=$2
[[ "$account_alias" =~ ^codex:[a-zA-Z0-9_-]+$ ]] || exit 2
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || { printf 'This pinned bootstrap supports Linux x86_64 only.\n' >&2; exit 2; }
for required in curl tar xz sha256sum awk; do command -v "$required" >/dev/null; done
runtime_root="$HOME/.local/share/mai-codex-runtime/node-24.13.0-codex-0.160.1"
if [ -e "$runtime_root" ]; then
  printf 'Runtime already exists. Preserve it and use its installer explicitly: %s\n' "$runtime_root" >&2
  exit 2
fi
mkdir -p "$runtime_root/downloads" "$runtime_root/product"
node_archive=node-v24.13.0-linux-x64.tar.xz
node_url=https://nodejs.org/dist/v24.13.0
curl --fail --location --proto '=https' --tlsv1.2 "$node_url/$node_archive" -o "$runtime_root/downloads/$node_archive"
curl --fail --location --proto '=https' --tlsv1.2 "$node_url/SHASUMS256.txt" -o "$runtime_root/downloads/node-sha256.txt"
(cd "$runtime_root/downloads"; awk -v name="$node_archive" '$2==name {print}' node-sha256.txt | sha256sum --check --strict -)
codex_archive=codex-package-x86_64-unknown-linux-musl.tar.gz
curl --fail --location --proto '=https' --tlsv1.2 "https://github.com/openai/codex/releases/download/rust-v0.160.1/$codex_archive" -o "$runtime_root/downloads/$codex_archive"
(cd "$runtime_root/downloads"; printf '%s  %s\n' 340801565906a7028f6baaa9ab6853addaef221f0016a1417a7c1ffdd96c21f0 "$codex_archive" | sha256sum --check --strict -)
tar -xf "$runtime_root/downloads/$node_archive" -C "$runtime_root"
tar -xzf "$runtime_root/downloads/$codex_archive" -C "$runtime_root"
tar -xzf "$package_path" -C "$runtime_root/product"
export PATH="$runtime_root/node-v24.13.0-linux-x64/bin:$PATH"
codex_executable="$runtime_root/bin/codex"
test -x "$runtime_root/bin/codex-code-mode-host"
test -x "$runtime_root/codex-resources/bwrap"
product="$runtime_root/product/package"
node --version
"$codex_executable" --version
node "$product/src/setup.mjs" install --account "$account_alias"
# Invocation is the direct user's explicit installation and trust approval.
node "$product/src/setup.mjs" trust --approve true --exe "$codex_executable"
node "$product/src/setup.mjs" doctor --native true --exe "$codex_executable"
printf '\nRuntime: %s\nProduct: %s\n' "$runtime_root" "$product"
