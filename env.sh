#!/bin/bash
# Source this file in Bash from a clean lxplus shell; it installs nothing.
_egm_activate_analysis() {
    if [ -n "${VIRTUAL_ENV:-}" ] || [ -n "${CONDA_PREFIX:-}" ]; then
        echo "Open a fresh shell without a virtual/Conda environment, then source env.sh." >&2
        return 1
    fi
    if [ -n "${CMSSW_BASE:-}" ]; then
        echo "Use a fresh shell for the LCG analysis view; keep cmsenv in the CMSSW shell." >&2
        return 1
    fi
    local egm_repo
    egm_repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd) || return
    source "$egm_repo/config/environment.sh" || return
    if [ ! -r "$EGM_LCG_SETUP" ]; then
        echo "LCG setup not found: $EGM_LCG_SETUP" >&2
        echo "Run on a host with CVMFS, or set EGM_LCG_SETUP to a validated CVMFS view." >&2
        return 1
    fi
    source "$EGM_LCG_SETUP" || return
    export PYTHONNOUSERSITE=1
    python3 "$egm_repo/scripts/check_environment.py" || return
    echo "Analysis environment: $EGM_LCG_SETUP"
}
if _egm_activate_analysis; then
    unset -f _egm_activate_analysis
else
    unset -f _egm_activate_analysis
    return 1 2>/dev/null || exit 1
fi
