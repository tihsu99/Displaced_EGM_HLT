"""Only extraction: no reconstruction, trigger selection, or prompt-ID cuts."""
import json
import FWCore.ParameterSet.Config as cms
from FWCore.ParameterSet.VarParsing import VarParsing

options = VarParsing("analysis")
options.register("job", "job.json", VarParsing.multiplicity.singleton, VarParsing.varType.string, "Resolved job JSON")
options.parseArguments()
with open(options.job) as source:
    job = json.load(source)
cfg = job["ntuplizer"]
process = cms.Process("EGMNTUPLE")
process.load("FWCore.MessageService.MessageLogger_cfi")
process.maxEvents = cms.untracked.PSet(input=cms.untracked.int32(options.maxEvents))
process.source = cms.Source("PoolSource", fileNames=cms.untracked.vstring(options.inputFiles))
process.options = cms.untracked.PSet(numberOfThreads=cms.untracked.uint32(1))
process.TFileService = cms.Service("TFileService", fileName=cms.string(options.outputFile))
process.egm = cms.EDAnalyzer(
    "EGMNtuplizer",
    candidates=cms.InputTag(cfg["candidates"]),
    genParticles=cms.InputTag(cfg["gen_particles"]),
    generator=cms.InputTag(cfg["generator"]),
    pdgIds=cms.vint32(cfg["pdg_ids"]),
    llpPdgIds=cms.vint32(cfg["llp_pdg_ids"]),
    invalidMapValues=cms.vdouble(cfg["invalid_map_values"]),
    divideByCandidateEnergy=cms.vstring(cfg.get("divide_by_candidate_energy", [])),
    maps=cms.VPSet(*[cms.PSet(name=cms.string(name), src=cms.InputTag(tag)) for name, tag in cfg["maps"].items()]),
)
process.path = cms.Path(process.egm)
