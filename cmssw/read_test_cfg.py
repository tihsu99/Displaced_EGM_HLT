"""Force a small EDM read/write to probe I/O compatibility; no HLT reconstruction."""
import FWCore.ParameterSet.Config as cms
from FWCore.ParameterSet.VarParsing import VarParsing

options = VarParsing("analysis")
options.maxEvents = 10
options.outputFile = "read_test.root"
options.parseArguments()
if not options.inputFiles:
    raise ValueError("Pass inputFiles=/store/...root or inputFiles=file:/tmp/input.root")
process = cms.Process("READTEST")
process.load("FWCore.MessageService.MessageLogger_cfi")
process.maxEvents = cms.untracked.PSet(input=cms.untracked.int32(options.maxEvents))
process.source = cms.Source("PoolSource", fileNames=cms.untracked.vstring(options.inputFiles))
process.output = cms.OutputModule(
    "PoolOutputModule",
    fileName=cms.untracked.string(options.outputFile),
    outputCommands=cms.untracked.vstring("keep *"),
    fastCloning=cms.untracked.bool(False),
)
process.end = cms.EndPath(process.output)
