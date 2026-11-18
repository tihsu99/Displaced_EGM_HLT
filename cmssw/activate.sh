#!/bin/bash
# The worker runs this in scratch, with all configured values passed as arguments.
set -eo pipefail
work_dir=$PWD
source "$1"
export SCRAM_ARCH="$2"
case "$4" in
  prebuilt)
    cd "$5/src"
    ;;
  scratch)
    scram project CMSSW "$3"
    cp -R "$work_dir/cmssw/Displaced_EGM_HLT" "$3/src/"
    cd "$3/src"
    ;;
  *)
    echo "Unknown CMSSW runtime: $4" >&2
    exit 2
    ;;
esac
runtime=$(scram runtime -sh)
eval "$runtime"
if [ "$CMSSW_VERSION" != "$3" ] || [ "$SCRAM_ARCH" != "$2" ]; then
  echo "Activated CMSSW release/architecture differs from the configured runtime" >&2
  exit 2
fi
if [ "$4" = scratch ]; then
  scram b -j "$6"
fi
cd "$work_dir"
exec python3 cmssw/run_job.py
