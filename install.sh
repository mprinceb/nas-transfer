#!/usr/bin/env bash
# Run as your normal desktop user; only apt runs with administrator privileges.
set -euo pipefail
export PATH="/usr/sbin:/usr/bin:/sbin:/bin:$PATH"
installer_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
package_name=trinet-nas-transfer_0.4.0_all.deb
case "${1:-}" in
  '') check_only=false ;;
  --check) check_only=true ;;
  --help|-h)
    echo 'Usage: bash install.sh [--check]'
    echo 'Checks system dependencies and installs the bundled application with apt.'
    echo '--check reports dependencies without installing anything.'
    exit 0 ;;
  *) echo "Unknown option: $1" >&2; exit 2 ;;
esac
if ! command -v apt-get >/dev/null || ! command -v dpkg-query >/dev/null; then
  echo 'This installer supports Ubuntu/Debian Linux with apt. Other distributions must use their package manager; see README.md.' >&2
  exit 1
fi
package_file="$installer_dir/$package_name"
if [[ ! -f "$package_file" ]]; then
  package_file="$installer_dir/dist/$package_name"
fi
if [[ ! -f "$package_file" ]]; then
  echo "Missing $package_name. Extract the complete installer bundle, or run bash build-deb.sh from the source folder." >&2
  exit 1
fi
dependencies=(python3 python3-tk cifs-utils pkexec util-linux mount sudo coreutils samba-common-bin libnss-mdns)
missing=()
echo 'Checking required system packages:'
for dependency in "${dependencies[@]}"; do
  status=$(dpkg-query -W -f='${Status}' "$dependency" 2>/dev/null || true)
  if [[ "$status" == 'install ok installed' ]]; then
    echo "  OK       $dependency"
  else
    echo "  MISSING  $dependency"
    missing+=("$dependency")
  fi
done
python_version=$(dpkg-query -W -f='${Version}' python3 2>/dev/null || true)
if [[ -n "$python_version" ]] && ! dpkg --compare-versions "$python_version" ge 3.10; then
  echo 'Python 3.10+ is required. Upgrade to a distribution release providing Python 3.10+.' >&2
  exit 1
fi
if "$check_only"; then
  if ((${#missing[@]})); then exit 1; fi
  echo 'All required packages are installed.'
  exit 0
fi
if (( EUID == 0 )); then
  elevate=()
elif command -v sudo >/dev/null; then
  elevate=(sudo)
elif command -v pkexec >/dev/null; then
  elevate=(pkexec)
else
  echo 'Administrator access is needed to install dependencies. Run this installer as root.' >&2
  exit 1
fi
# Give apt's unprivileged download helper a readable path even when the bundle
# was extracted into a private home folder.
package_temp=$(mktemp -d /tmp/trinet-install.XXXXXXXX)
trap 'rm -rf -- "$package_temp"' EXIT
chmod 755 "$package_temp"
install -m 644 "$package_file" "$package_temp/$package_name"
if ((${#missing[@]})); then
  echo 'Refreshing apt metadata for missing dependencies…'
  "${elevate[@]}" apt-get update
fi
echo 'Installing Ego Trinet Transfer and required dependencies…'
"${elevate[@]}" apt-get install -y --no-remove "$package_temp/$package_name"
echo 'Checking installed runtime…'
/usr/bin/python3 -c 'import sys, tkinter; assert sys.version_info >= (3, 10)'
for tool in mount.cifs mount pkexec lsblk findmnt sudo timeout nmblookup; do
  command -v "$tool" >/dev/null || { echo "Required command still missing: $tool" >&2; exit 1; }
done
if [[ ! -x /usr/bin/trinet-nas-transfer ]]; then
  echo 'The application launcher was not installed correctly.' >&2
  exit 1
fi
echo 'Installed. Open “Ego Trinet Transfer” from the application menu.'
echo 'Or run: trinet-nas-transfer'
echo 'CLI: trinet-nas-transfer-cli'
