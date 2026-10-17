#!/bin/sh
# Invoked explicitly by the native GUI through the OS authorization dialog.
set -eu
if [ "$(id -u)" -ne 0 ]; then
    echo 'Administrator authorization is required.' >&2
    exit 1
fi
tracker_ts_installer="$(mktemp /tmp/tracker-tailscale-install.XXXXXX)"
trap 'rm -f "$tracker_ts_installer"' EXIT HUP INT TERM
if command -v curl >/dev/null 2>&1; then
    curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --tlsv1.2 \
        https://tailscale.com/install.sh -o "$tracker_ts_installer"
elif command -v wget >/dev/null 2>&1; then
    wget --https-only -q https://tailscale.com/install.sh -O "$tracker_ts_installer"
else
    echo 'Install curl or wget, or use https://tailscale.com/download.' >&2
    exit 1
fi
/bin/sh "$tracker_ts_installer"
