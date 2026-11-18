"""Run the L1/HLT menu, fill inclusive EGM features, and write only the ntuple."""
import json
from pathlib import Path


def driver_command(job, files, max_events):
    cfg = job["cmssw"]
    provenance, replay = cfg["provenance"], cfg["replay"]
    command = [
        "cmsDriver.py", "EGMReplay", "--mc", "--no_exec",
        "--step", ",".join(replay["steps"]),
        "--conditions", provenance["global_tag"],
        "--geometry", provenance["geometry"], "--era", provenance["era"],
        "--processName", replay["process"],
        "--filein", ",".join(files),
        "--number", str(max_events), "--nThreads", str(replay["threads"]),
        "--python_filename", "replay_base.py",
        "--no_output",
    ]
    if replay.get("customise"):
        command.extend(["--customise", ",".join(replay["customise"])])
    return command


def configure_replay(process, job, cms):
    cfg = job["cmssw"]["replay"]
    for module in cfg["load"]:
        process.load(module)
    for name, value in cfg["parameters"].items():
        label, parameter = name.split(".", 1)
        getattr(getattr(process, label), parameter).setValue(value)

    sequence = cms.Sequence()
    for label in cfg["sequence"]:
        sequence += getattr(process, label)
    names = set(sequence.moduleNames())
    filters = names.intersection(process.filters_())
    if filters:
        raise ValueError(f"The inclusive feature path contains EDFilter modules: {sorted(filters)}")
    tags = [job["ntuplizer"]["candidates"], *job["ntuplizer"]["maps"].values()]
    for tag in tags:
        parts = tag.split(":")
        if parts[0] not in names:
            raise ValueError(f"Required ntuple product is not scheduled: {tag}")
        if len(parts) != 3 or parts[2] != cfg["process"]:
            raise ValueError(f"Ntuple product must explicitly use process {cfg['process']}: {tag}")

    extra = cfg["extra"]
    expected = f"{extra['module']}:{extra['instance']}:{cfg['process']}"
    if job["ntuplizer"]["objects"] != expected:
        raise ValueError(f"Ntuplizer objects must be {expected}")
    process.load(extra["load"])
    packer = getattr(process, extra["module"])
    packer.egCands = cms.VPSet(cms.PSet(
        ecalCands=cms.InputTag(job["ntuplizer"]["candidates"]),
        pixelSeeds=cms.InputTag(extra["pixel_seeds"]),
        gsfTracks=cms.InputTag(extra["gsf_tracks"]),
        label=cms.string(extra["instance"]),
    ))

    process.source.inputCommands = cms.untracked.vstring(cfg["input_commands"])
    process.source.dropDescendantsOfDroppedBranches = cms.untracked.bool(False)
    process.options.numberOfThreads = cms.untracked.uint32(cfg["threads"])
    process.options.numberOfStreams = cms.untracked.uint32(1)
    process.options.accelerators = cms.untracked.vstring("cpu")
    process.options.wantSummary = cms.untracked.bool(True)
    process.egmFeatures = cms.Path(sequence)
    # Preserve the generated L1/HLT paths. The extra feature path has no filters.
    process.schedule.append(process.egmFeatures)
    return process


def save_replay_provenance(process, job, command):
    Path("replay_config.py").write_text(process.dumpPython())
    Path("replay_metadata.json").write_text(json.dumps({
        "release": job["cmssw"]["release"],
        "cmsdriver": command,
        "global_tag": process.GlobalTag.globaltag.value(),
        "conditions_overrides": process.GlobalTag.toGet.dumpPython(),
        "feature_modules": sorted(process.egmFeatures.moduleNames()),
        "objects": job["ntuplizer"]["objects"],
        "feature_sources": job["ntuplizer"]["maps"],
        "parameters": job["cmssw"]["replay"]["parameters"],
    }, indent=2) + "\n")
