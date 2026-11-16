"""Executed inside the selected CMSSW runtime (no analysis dependencies)."""
import json
import os
from pathlib import Path
import subprocess

import ROOT

job = json.loads(Path("resolved.json").read_text())
if os.environ.get("CMSSW_VERSION") != job["cmssw"]["release"]:
    raise RuntimeError("Active CMSSW release does not match the frozen job")
if job["cmssw"]["runtime"] == "prebuilt" and Path(os.environ.get("CMSSW_BASE", "")).resolve() != Path(job["cmssw"]["base"]).resolve():
    raise RuntimeError("Active CMSSW_BASE differs from the configured prebuilt area")
files = job["input_files"]
for command, output in [("edmProvDump", "input_provenance.txt"), ("edmDumpEventContent", "event_content.txt")]:
    with open(output, "w") as handle:
        subprocess.run([command, files[0]], stdout=handle, check=True)
if job["cmssw"]["mode"] == "rerun":
    subprocess.run(["cmsRun", "-j", "ReplayJobReport.xml", "cmssw/replay_cfg.py",
                    "inputFiles=" + ",".join(files), "outputFile=replayed.root", f"maxEvents={job['max_events']}"], check=True)
    files = ["file:" + str(Path("replayed.root").resolve())]
args = ["cmssw/ntuple_cfg.py", "job=resolved.json", "inputFiles=" + ",".join(files),
        "outputFile=ntuple.root", f"maxEvents={job['max_events']}"]
with open("ntuple_config.py", "w") as output:
    subprocess.run(["edmConfigDump", *args], stdout=output, check=True)
subprocess.run(["cmsRun", "-j", "FrameworkJobReport.xml", *args], check=True)
source = ROOT.TFile.Open("ntuple.root")
if not source or source.IsZombie() or source.TestBit(ROOT.TFile.kRecovered):
    raise RuntimeError("Output ROOT file is invalid or recovered")
tree = source.Get("egm/Events")
if not tree or tree.GetEntries() == 0:
    raise RuntimeError("No processed events")
required = {"run", "lumi", "event", "gen_weight", "pt", "eta", "phi", "sc_eta", "sc_phi",
            "gen_pt", "gen_eta", "gen_phi", "gen_vx", "gen_vy", "gen_vz", "gen_pdg_id", "gen_prompt", "gen_llp"} | set(job["ntuplizer"]["maps"])
missing = required - {branch.GetName() for branch in tree.GetListOfBranches()}
if missing:
    raise RuntimeError(f"Missing branches: {sorted(missing)}")
import math
summary = dict(events=0, candidates=0, gen_particles=0, sum_gen_weight=0.0, sum_abs_gen_weight=0.0)
for entry in tree:
    weight = float(entry.gen_weight)
    if not math.isfinite(weight):
        raise RuntimeError("Nonfinite generator weight")
    summary["events"] += 1
    summary["candidates"] += len(entry.pt)
    summary["gen_particles"] += len(entry.gen_pt)
    summary["sum_gen_weight"] += weight
    summary["sum_abs_gen_weight"] += abs(weight)
if summary["candidates"] == 0:
    raise RuntimeError("No candidates; increase the smoke event count or inspect the HLT products")
source.Close()
Path("inspection.json").write_text(json.dumps(summary, indent=2))
