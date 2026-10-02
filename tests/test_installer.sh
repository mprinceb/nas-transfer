#!/usr/bin/env bash
# Exercise missing-dependency handling without invoking apt or privilege tools.
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
test_tmp=$(mktemp -d)
trap 'rm -rf -- "$test_tmp"' EXIT
export INSTALLER_TEST_LOG="$test_tmp/apt-calls"
dpkg-query() {
  if [[ "${*: -1}" == cifs-utils ]]; then return 1; fi
  command dpkg-query "$@"
}
apt-get() {
  printf '%s\n' "$*" >> "$INSTALLER_TEST_LOG"
  if [[ "$1" == update ]]; then return 0; fi
  return 42
}
sudo() { "$@"; }
pkexec() { "$@"; }
export -f dpkg-query apt-get sudo pkexec
set +e
bash "$project_dir/install.sh" > "$test_tmp/output" 2>&1
result=$?
set -e
[[ "$result" == 42 ]]
grep -q 'MISSING  cifs-utils' "$test_tmp/output"
grep -qx update "$INSTALLER_TEST_LOG"
grep -q '^install -y --no-remove /tmp/trinet-install.' "$INSTALLER_TEST_LOG"
! grep -q '^Installed\.' "$test_tmp/output"
rm "$INSTALLER_TEST_LOG"
set +e
bash "$project_dir/install.sh" --check > "$test_tmp/check-output" 2>&1
result=$?
set -e
[[ "$result" == 1 ]]
[[ ! -e "$INSTALLER_TEST_LOG" ]]
echo 'Passed: missing dependency detection, apt refresh/install invocation, apt failure propagation, read-only --check.'
