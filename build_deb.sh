#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
VERSION=$(sed -n 's/^__version__[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "$ROOT/lunawetter/__init__.py")
BUILD=$(mktemp -d "${TMPDIR:-/tmp}/lunawetter-build.XXXXXX")
DIST="$ROOT/dist"
trap 'rm -rf "$BUILD"' EXIT HUP INT TERM
mkdir -p "$BUILD/DEBIAN" "$BUILD/usr/share/lunawetter/lunawetter" "$BUILD/usr/share/doc/lunawetter" "$BUILD/usr/bin" "$BUILD/usr/share/applications" "$BUILD/usr/share/pixmaps"
cp -a "$ROOT/lunawetter/"*.py "$BUILD/usr/share/lunawetter/lunawetter/"
install -m 0644 "$ROOT/README.md" "$BUILD/usr/share/doc/lunawetter/README.md"
install -m 0644 "$ROOT/CHANGELOG.md" "$BUILD/usr/share/doc/lunawetter/changelog.md"
install -m 0644 "$ROOT/debian/lunawetter.desktop" "$BUILD/usr/share/applications/lunawetter.desktop"
install -m 0644 "$ROOT/assets/lunawetter.svg" "$BUILD/usr/share/pixmaps/lunawetter.svg"
cat > "$BUILD/usr/bin/lunawetter" <<'LAUNCH'
#!/bin/sh
export PYTHONPATH="/usr/share/lunawetter${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 -m lunawetter "$@"
LAUNCH
chmod 0755 "$BUILD/usr/bin/lunawetter"
cat > "$BUILD/DEBIAN/control" <<CONTROL
Package: lunawetter
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Depends: python3, python3-pyside6.qtwidgets, python3-gi, gir1.2-gtk-3.0
Maintainer: Goldisoft <maintainer@example.invalid>
Description: LunaWetter – Wettervergleich mit mehreren Anbietern
 Graphit-basierte Wetteranwendung mit mehreren Datenquellen und GTK-System-Tray.
CONTROL
chmod 0755 "$BUILD/DEBIAN"
mkdir -p "$DIST"
dpkg-deb --build --root-owner-group "$BUILD" "$DIST/lunawetter_${VERSION}_all.deb"
echo "Fertig: $DIST/lunawetter_${VERSION}_all.deb"
