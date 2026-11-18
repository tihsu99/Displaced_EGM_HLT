"""Configure the final ROOT ntuple in either the replay or an EDM reading job."""
import json


def add_ntuplizer(process, job, cms, output_file):
    cfg = job["ntuplizer"]
    matching, selection = cfg["matching"], cfg["selection"]
    process.TFileService = cms.Service("TFileService", fileName=cms.string(output_file))
    process.egm = cms.EDAnalyzer(
        "EGMNtuplizer",
        objects=cms.InputTag(cfg["objects"]),
        genParticles=cms.InputTag(cfg["gen_particles"]),
        generator=cms.InputTag(cfg["generator"]),
        pdgIds=cms.vint32(cfg["pdg_ids"]),
        llpPdgIds=cms.vint32(cfg["llp_pdg_ids"]),
        invalidMapValues=cms.vdouble(cfg["invalid_map_values"]),
        divideByCandidateEnergy=cms.vstring(cfg.get("divide_by_candidate_energy", [])),
        ptMin=cms.double(selection["pt_min"]),
        absEtaMax=cms.double(selection["abs_eta_max"]),
        matchingPdgId=cms.int32(matching["pdg_id"]),
        matchingDirection=cms.string(matching["direction"]),
        maxDR=cms.double(matching["max_dr"]),
        ecalRadius=cms.double(matching["ecal_radius_cm"]),
        ecalHalfLength=cms.double(matching["ecal_half_length_cm"]),
        maps=cms.VPSet(*[cms.PSet(name=cms.string(name), src=cms.InputTag(tag))
                        for name, tag in cfg["maps"].items()]),
        metadata=cms.string(json.dumps(dict(
            schema_version=2, sample=job["sample"], sample_config=job["sample_config"],
            fingerprint=job["fingerprint"], job_id=job["id"], input_files=job["files"],
            cmssw=job["cmssw"], ntuplizer=cfg, synthetic=False,
        ), sort_keys=True)),
    )
    return process
