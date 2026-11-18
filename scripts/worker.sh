#!/bin/bash
set -eo pipefail
# Both local tests and batch jobs enter through this script in a clean Python environment.
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV LD_LIBRARY_PATH
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
worker_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec /usr/bin/python3 "$worker_dir/worker.py" "$@"
