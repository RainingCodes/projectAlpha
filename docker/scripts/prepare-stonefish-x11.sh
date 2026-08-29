#!/usr/bin/env bash
# Prepare a dedicated Xauthority file for Stonefish in an XRDP/Xorg session.
set -euo pipefail

DISPLAY_VALUE="${DISPLAY:-:10}"
export DISPLAY="$DISPLAY_VALUE"

if ! command -v xauth >/dev/null 2>&1; then
  echo "ERROR: xauth is not installed on the host." >&2
  exit 1
fi

DISPLAY_NUM="${DISPLAY_VALUE#:}"
DISPLAY_NUM="${DISPLAY_NUM%%.*}"
SOCKET="/tmp/.X11-unix/X${DISPLAY_NUM}"

if [[ ! -S "$SOCKET" ]]; then
  echo "ERROR: X11 socket not found: $SOCKET" >&2
  echo "Check DISPLAY. Current DISPLAY=$DISPLAY_VALUE" >&2
  exit 1
fi

COOKIE_DATA="$(xauth nlist "$DISPLAY_VALUE" 2>/dev/null || true)"
if [[ -z "$COOKIE_DATA" ]]; then
  echo "ERROR: xauth has no cookie for DISPLAY=$DISPLAY_VALUE" >&2
  echo "Try: xauth list" >&2
  exit 1
fi

rm -f /tmp/.docker.xauth
touch /tmp/.docker.xauth
printf '%s\n' "$COOKIE_DATA" \
  | sed -e 's/^..../ffff/' \
  | xauth -f /tmp/.docker.xauth nmerge -
chmod 644 /tmp/.docker.xauth

echo "Prepared /tmp/.docker.xauth for DISPLAY=$DISPLAY_VALUE"
xauth -f /tmp/.docker.xauth list
ls -l "$SOCKET"
