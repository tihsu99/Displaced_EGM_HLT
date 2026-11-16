"""Read YAML and reject ambiguous production settings before any submission."""

import hashlib
import json
import math
import os
from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[1]


def read_yaml(path):
    path = Path(path).resolve()
    data = yaml.safe_load(os.path.expandvars(path.read_text()))
    if not isinstance(data, dict):
        raise ValueError(f"Expected a YAML mapping: {path}")
    return data


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def file_digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")


def validate_production(c):
    errors = []
    for section, keys in {
        "storage": ["eos"], "cmssw": ["release", "scram_arch"],
        "ntuplizer": ["candidates", "gen_particles", "generator"],
    }.items():
        for key in keys:
            if not c.get(section, {}).get(key):
                errors.append(f"Set {section}.{key}")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", c.get("campaign", "")):
        errors.append("campaign must contain only letters, digits, '_' or '-'")
    eos = c.get("storage", {}).get("eos") or ""
    if not re.fullmatch(r"root://[A-Za-z0-9.-]+//eos/[A-Za-z0-9_./-]+", eos):
        errors.append("storage.eos must be a root://host//eos/... URL")
    if not re.fullmatch(r"CMSSW_[0-9]+_[0-9]+_[0-9]+(?:_[A-Za-z0-9]+)*", c.get("cmssw", {}).get("release") or ""):
        errors.append("cmssw.release must be an explicit CMSSW release")
    runtime = c.get("cmssw", {}).get("runtime")
    if runtime not in {"prebuilt", "scratch"}:
        errors.append("cmssw.runtime must be prebuilt or scratch")
    if runtime == "prebuilt":
        base = c["cmssw"].get("base")
        if not isinstance(base, str) or not Path(base).is_absolute():
            errors.append("Set cmssw.base to the absolute, already compiled CMSSW area")
    if any(part == ".." for part in eos.split("/")):
        errors.append("storage.eos cannot contain '..' components")
    invalid_values = c.get("ntuplizer", {}).get("invalid_map_values")
    if not isinstance(invalid_values, list) or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in invalid_values):
        errors.append("ntuplizer.invalid_map_values must be a finite numeric list")
    for name, tag in c.get("ntuplizer", {}).get("maps", {}).items():
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name) or not tag:
            errors.append(f"Set a valid ntuplizer.maps.{name} InputTag")
    if not c.get("ntuplizer", {}).get("maps"):
        errors.append("Configure ntuplizer.maps")
    mode = c.get("cmssw", {}).get("mode")
    if mode not in {"existing", "rerun"}:
        errors.append("cmssw.mode must be existing or rerun")
    if mode == "rerun" and not c["cmssw"].get("replay_pset"):
        errors.append("Set cmssw.replay_pset for HLT rerunning")
    for key in ("global_tag", "geometry", "era", "menu", "input_campaign"):
        if not c.get("cmssw", {}).get("provenance", {}).get(key):
            errors.append(f"Record cmssw.provenance.{key}")
    samples = {k: v for k, v in c.get("samples", {}).items() if v.get("enabled")}
    if not samples:
        errors.append("Enable at least one sample after supplying its exact dataset/files")
    for name, sample in samples.items():
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            errors.append(f"Invalid sample key: {name}")
        if bool(sample.get("das")) == bool(sample.get("files")):
            errors.append(f"{name}: provide exactly one of das or files")
        if sample.get("role") not in {"signal", "background"}:
            errors.append(f"{name}: role must be signal or background")
        if sample.get("truth") not in {"prompt", "llp", "all"}:
            errors.append(f"{name}: truth must be prompt, llp or all")
        if sample.get("role") == "signal" and sample.get("truth") == "all":
            errors.append(f"{name}: signal requires prompt or llp truth")
        if not sample.get("tier"):
            errors.append(f"{name}: record the input data tier")
        if (sample.get("tier") or "").startswith("NANO"):
            errors.append(f"{name}: NanoAOD cannot supply the required EDM HLT maps")
    for section, keys in {"production": ["files_per_job", "local_test_events", "stageout_attempts"],
                          "condor": ["cpus", "memory_mb", "disk_mb"], "cmssw": ["build_jobs"]}.items():
        for key in keys:
            value = c.get(section, {}).get(key, 0)
            if not isinstance(value, int) or value <= 0:
                errors.append(f"{section}.{key} must be a positive integer")
    if c.get("production", {}).get("max_events", 0) not in [-1] and c.get("production", {}).get("max_events", 0) <= 0:
        errors.append("production.max_events must be -1 or positive")
    if errors:
        raise ValueError("Production configuration incomplete:\n  " + "\n  ".join(errors))
    return samples


def validate_study(c):
    if c["selection"]["pdg_id"] not in (11, 22):
        raise ValueError("selection.pdg_id must be 11 or 22")
    if c["matching"]["direction"] not in ("momentum", "ecal_barrel"):
        raise ValueError("matching.direction must be momentum or ecal_barrel")
    if c["selection"]["pdg_id"] == 11 and c["matching"]["direction"] != "momentum":
        raise ValueError("Electrons cannot use straight photon propagation; use momentum for a diagnostic study")
    if c["matching"]["direction"] == "ecal_barrel" and c["selection"]["abs_eta_max"] > 1.5:
        raise ValueError("ecal_barrel is not an endcap geometry model")
    if c["matching"]["max_dr"] <= 0 or c["selection"]["pt_min"] < 0 or c["selection"]["abs_eta_max"] <= 0:
        raise ValueError("Invalid matching/acceptance range")
    if any(c["matching"][name] <= 0 for name in ["ecal_radius_cm", "ecal_half_length_cm"]):
        raise ValueError("ECAL geometry dimensions must be positive")
    if not 0 < c["split"]["train"] < 1 or not 0 < c["split"]["validation"] < 1 - c["split"]["train"]:
        raise ValueError("Require positive, disjoint train/validation/test fractions")
    if c["weights"]["generator"] not in ("absolute", "unit"):
        raise ValueError("ID probability training supports absolute or unit generator weights")
    if not c["features"] or not all(0 < wp < 1 for wp in c["working_points"]):
        raise ValueError("Supply features and working points in (0, 1)")
    for name, spec in c["features"].items():
        if spec["direction"] not in ("less", "greater") or spec["min"] >= spec["max"]:
            raise ValueError(f"Invalid cut range/direction: {name}")
    if c["evaluation"]["working_point"] not in c["working_points"]:
        raise ValueError("evaluation.working_point must be one of working_points")
    for variable, bins in c["evaluation"]["bins"].items():
        if variable not in {"pt", "eta", "gen_lxy", "gen_abs_z"} or len(bins) < 2 or not all(math.isfinite(x) for x in bins) or any(a >= b for a, b in zip(bins[:-1], bins[1:])):
            raise ValueError(f"Invalid evaluation variable/bins: {variable}")
    return c
