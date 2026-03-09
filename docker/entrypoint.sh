#!/bin/sh
set -eu

mkdir -p "${DATA_DIR:-/app/data}"

exec "$@"
