#!/bin/bash
# The worker runs this in scratch, with all configured values passed as arguments.
set -eo pipefail
work_dir=$PWD
echo "[stage] Sourcing CMS setup: $1"
source "$1"
export SCRAM_ARCH="$2"
echo "[stage] Activating $3 ($SCRAM_ARCH, $4)"
case "$4" in
  prebuilt)
    cd "$5/src"
    ;;
  scratch)
    scram project CMSSW "$3"
    mkdir -p "$3/src/Displaced_EGM_HLT"
    cp -R "$work_dir/Ntuplizer" "$3/src/Displaced_EGM_HLT/"
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
  echo "[stage] Building the CMSSW package"
  scram b -j "$6"
fi
cd "$work_dir"
echo "[stage] CMSSW ready; starting the job in $work_dir"
exec python3 -u scripts/run_job.py
