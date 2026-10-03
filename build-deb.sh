#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
version=0.3.0
command -v dpkg-deb >/dev/null || { echo 'Building requires dpkg-deb (package: dpkg).' >&2; exit 1; }
staging=$(mktemp -d)
trap 'rm -rf -- "$staging"' EXIT
chmod 755 "$staging"
install -d "$staging/DEBIAN" "$staging/usr/lib/trinet-nas-transfer" "$staging/usr/bin" \
  "$staging/usr/share/applications" "$staging/usr/share/icons/hicolor/scalable/apps" \
  "$staging/usr/share/doc/trinet-nas-transfer" "$project_dir/dist"
for module in nas_transfer.py nas_transfer_cli.py nas_config.py nas_paths.py nas_windows.py; do
  install -m 644 "$project_dir/$module" "$staging/usr/lib/trinet-nas-transfer/$module"
done
cat > "$staging/usr/bin/trinet-nas-transfer" <<'LAUNCHER'
#!/bin/sh
export PATH="/usr/sbin:/usr/bin:/sbin:/bin:$PATH"
exec /usr/bin/python3 /usr/lib/trinet-nas-transfer/nas_transfer.py "$@"
LAUNCHER
cat > "$staging/usr/bin/trinet-nas-transfer-cli" <<'LAUNCHER'
#!/bin/sh
export PATH="/usr/sbin:/usr/bin:/sbin:/bin:$PATH"
exec /usr/bin/python3 /usr/lib/trinet-nas-transfer/nas_transfer_cli.py "$@"
LAUNCHER
chmod 755 "$staging/usr/bin/"*
install -m 644 "$project_dir/packaging/trinet-nas-transfer.desktop" "$staging/usr/share/applications/"
install -m 644 "$project_dir/packaging/trinet-nas-transfer.svg" "$staging/usr/share/icons/hicolor/scalable/apps/"
install -m 644 "$project_dir/README.md" "$staging/usr/share/doc/trinet-nas-transfer/"
installed_size=$(du -sk "$staging/usr" | cut -f1)
cat > "$staging/DEBIAN/control" <<CONTROL
Package: trinet-nas-transfer
Version: $version
Section: utils
Priority: optional
Architecture: all
Maintainer: Trinet Internal Tools <trinet-tools@localhost>
Depends: python3 (>= 3.10), python3-tk, cifs-utils, pkexec, util-linux, mount, sudo, coreutils, samba-common-bin, libnss-mdns
Installed-Size: $installed_size
Description: Ego NAS recording transfer desktop and CLI utility
 Transfer up to 15 mounted SD cards in a verified desktop queue.
 Includes a CLI, automatic destination numbering and NAS connection retry.
CONTROL
# Desktop/icon caches are maintained by the distro's standard dpkg triggers.
# No post-install script runs the application or accesses removable storage.
dpkg-deb --root-owner-group --build "$staging" "$project_dir/dist/trinet-nas-transfer_${version}_all.deb"
install -m 755 "$project_dir/install.sh" "$project_dir/dist/install.sh"
archive="trinet-nas-transfer_${version}_linux.tar.gz"
tar -czf "$project_dir/dist/$archive" -C "$project_dir/dist" install.sh "trinet-nas-transfer_${version}_all.deb"
echo "Built: $project_dir/dist/$archive"
