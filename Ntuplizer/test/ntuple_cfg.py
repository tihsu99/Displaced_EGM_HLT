"""Only extraction: no reconstruction, trigger selection, or prompt-ID cuts."""
import json
import FWCore.ParameterSet.Config as cms
from FWCore.ParameterSet.VarParsing import VarParsing

from Displaced_EGM_HLT.Ntuplizer.ntuple_tools import add_ntuplizer

options = VarParsing("analysis")
# Keep the filename shared with the worker; tagString adds _numEventN for trial runs.
options.setType("outputFile", VarParsing.varType.string)
options.register("job", "job.json", VarParsing.multiplicity.singleton, VarParsing.varType.string, "Resolved job JSON")
options.parseArguments()
with open(options.job) as source:
    job = json.load(source)
process = cms.Process("EGMNTUPLE")
process.load("FWCore.MessageService.MessageLogger_cfi")
process.maxEvents = cms.untracked.PSet(input=cms.untracked.int32(options.maxEvents))
process.source = cms.Source("PoolSource", fileNames=cms.untracked.vstring(options.inputFiles))
process.options = cms.untracked.PSet(numberOfThreads=cms.untracked.uint32(1))
add_ntuplizer(process, job, cms, options.outputFile)
process.path = cms.Path(process.egm)
