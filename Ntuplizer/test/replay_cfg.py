"""cmsRun entry point for the HLT replay configured in the frozen job JSON."""
import json
import os
from pathlib import Path
import runpy
import subprocess

import FWCore.ParameterSet.Config as cms
from FWCore.ParameterSet.VarParsing import VarParsing

from Displaced_EGM_HLT.Ntuplizer.replay_tools import configure_replay, driver_command, save_replay_provenance
from Displaced_EGM_HLT.Ntuplizer.ntuple_tools import add_ntuplizer

options = VarParsing("analysis")
# Keep the filename shared with the worker; tagString adds _numEventN for trial runs.
options.setType("outputFile", VarParsing.varType.string)
options.register("job", "resolved.json", VarParsing.multiplicity.singleton,
                 VarParsing.varType.string, "Resolved job JSON")
options.parseArguments()
job = json.loads(Path(options.job).read_text())
if os.environ.get("CMSSW_VERSION") != job["cmssw"]["release"]:
    raise RuntimeError("Active CMSSW release differs from the configured replay release")

command = driver_command(job, options.inputFiles, options.maxEvents)
subprocess.run(command, check=True)
process = runpy.run_path("replay_base.py")["process"]
process = configure_replay(process, job, cms)
add_ntuplizer(process, job, cms, options.outputFile)
packer = getattr(process, job["cmssw"]["replay"]["extra"]["module"])
process.egmNtuple = cms.EndPath(packer + process.egm)
process.schedule.append(process.egmNtuple)
save_replay_provenance(process, job, command)
