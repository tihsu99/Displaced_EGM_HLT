"""Build object rows, generator denominators, and independent event splits."""
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile

import awkward as ak
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import uproot

from .config import ROOT, digest, file_digest, read_yaml, validate_study, write_json
from .production import read_farm


@contextmanager
def output_workspace(destination):
    destination = Path(destination).resolve()
    if destination.is_relative_to(ROOT) or str(destination).startswith("/afs/"):
        raise ValueError("Store outputs outside the code/AFS area; use /tmp or /eos")
    if destination.exists():
        raise ValueError(f"Output already exists: {destination}")
    with tempfile.TemporaryDirectory(prefix="egm-output-") as directory:
        yield Path(directory)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(directory, destination)


def event_split(sample, run, lumi, event, cfg):
    identity = f"{cfg['seed']}:{sample}:{run}:{lumi}:{event}"
    value = int(hashlib.sha256(identity.encode()).hexdigest()[:16], 16) / 2**64
    if value < cfg["split"]["train"]:
        return "train"
    if value < cfg["split"]["train"] + cfg["split"]["validation"]:
        return "validation"
    return "test"


def projected_direction(gen, cfg):
    """Barrel-only photon ray; a production point outside the barrel is not accepted."""
    if cfg["direction"] == "momentum":
        return float(gen["eta"]), float(gen["phi"])
    x, y, z = (float(gen[key]) for key in ("vx", "vy", "vz"))
    radius, half_z = cfg["ecal_radius_cm"], cfg["ecal_half_length_cm"]
    if math.hypot(x, y) >= radius or abs(z) >= half_z:
        return None
    ux, uy = math.cos(gen["phi"]), math.sin(gen["phi"])
    dot = x * ux + y * uy
    distance = -dot + math.sqrt(dot * dot + radius * radius - x * x - y * y)
    hit_x, hit_y = x + distance * ux, y + distance * uy
    hit_z = z + distance * math.sinh(gen["eta"])
    if abs(hit_z) >= half_z:
        return None
    return math.asinh(hit_z / radius), math.atan2(hit_y, hit_x)


def match_unique(candidates, generators, cfg):
    """Greedy nearest-dR one-to-one matches; keep unmatched generators in the denominator."""
    pairs = []
    for gi, gen in enumerate(generators):
        direction = projected_direction(gen, cfg)
        if direction is None:
            continue
        eta, phi = direction
        for ci, candidate in enumerate(candidates):
            eta_key, phi_key = ("sc_eta", "sc_phi") if cfg["direction"] == "ecal_barrel" else ("eta", "phi")
            dr = math.hypot(candidate[eta_key] - eta, math.remainder(candidate[phi_key] - phi, 2 * math.pi))
            if dr < cfg["max_dr"]:
                pairs.append((dr, ci, gi))
    matches, used_gen = {}, set()
    for dr, ci, gi in sorted(pairs):
        if ci not in matches and gi not in used_gen:
            matches[ci] = (gi, dr)
            used_gen.add(gi)
    return matches


def event_rows(event, sample, spec, cfg):
    split = event_split(sample, event["run"], event["lumi"], event["event"], cfg)
    key = f"{sample}:{event['run']}:{event['lumi']}:{event['event']}"
    signed = float(event["gen_weight"])
    if not np.isfinite(signed):
        raise ValueError("Nonfinite generator weight")
    weight = abs(signed) if cfg["weights"]["generator"] == "absolute" else 1.0
    common = dict(sample=sample, role=spec["role"], split=split, event_key=key,
                  gen_weight=signed, weight=weight)
    reco_names = ["pt", "eta", "phi", "sc_eta", "sc_phi"] + [name for name in cfg["features"] if name != "shape_asymmetry" and name not in {"pt", "eta", "phi", "sc_eta", "sc_phi"}]
    if "shape_asymmetry" in cfg["features"]:
        reco_names = list(dict.fromkeys(reco_names + ["s_major", "s_minor"]))
    candidates = []
    for i in range(len(event["pt"])):
        c = {name: float(event[name][i]) for name in reco_names}
        if not all(np.isfinite(value) for value in c.values()):
            raise ValueError("Nonfinite candidate feature")
        if c["pt"] <= cfg["selection"]["pt_min"] or abs(c["sc_eta"]) >= cfg["selection"]["abs_eta_max"]:
            continue
        if "shape_asymmetry" in cfg["features"]:
            total = c["s_major"] + c["s_minor"]
            if total <= 0:
                raise ValueError("Undefined shower asymmetry; inspect s_major/s_minor maps")
            c["shape_asymmetry"] = (c["s_major"] - c["s_minor"]) / total
        c["candidate_key"] = f"{key}:{i}"
        candidates.append(c)
    generators = []
    for i, pdg in enumerate(event["gen_pdg_id"]):
        if abs(pdg) != cfg["selection"]["pdg_id"]:
            continue
        g = {name: float(event["gen_" + name][i]) for name in ["pt", "eta", "phi", "vx", "vy", "vz"]}
        if not all(np.isfinite(value) for value in g.values()):
            raise ValueError("Nonfinite generator kinematics")
        # LLP ancestry takes precedence: CMS isPrompt is not a displacement measurement.
        g["truth"] = "llp" if event["gen_llp"][i] else "prompt" if event["gen_prompt"][i] else "other"
        g["lxy"] = math.hypot(g["vx"], g["vy"])
        g["abs_z"] = abs(g["vz"])
        direction = projected_direction(g, cfg["matching"])
        g["fiducial"] = (g["pt"] > cfg["selection"]["pt_min"] and direction is not None and abs(direction[0]) < cfg["selection"]["abs_eta_max"])
        generators.append(g)
    matches = match_unique(candidates, generators, cfg["matching"])
    rows = []
    matched_gen = {}
    for ci, c in enumerate(candidates):
        gi, dr = matches.get(ci, (None, None))
        gen = generators[gi] if gi is not None else None
        if spec["role"] == "signal" and (gen is None or not gen["fiducial"] or gen["truth"] != spec["truth"]):
            continue
        row = dict(common, **c, label=int(spec["role"] == "signal"), truth=gen["truth"] if gen else "unmatched",
                   gen_pt=gen["pt"] if gen else np.nan, gen_lxy=gen["lxy"] if gen else np.nan,
                   gen_abs_z=gen["abs_z"] if gen else np.nan, match_dr=dr if dr is not None else np.nan)
        rows.append(row)
        if gi is not None:
            matched_gen[gi] = c["candidate_key"]
    denominator = []
    if spec["role"] == "signal":
        for gi, gen in enumerate(generators):
            if gen["fiducial"] and gen["truth"] == spec["truth"]:
                denominator.append(dict(common, truth=gen["truth"], pt=gen["pt"], eta=gen["eta"],
                                        gen_lxy=gen["lxy"], gen_abs_z=gen["abs_z"],
                                        candidate_key=matched_gen.get(gi, "")))
    event_record = dict(common, candidates=len(event["pt"]), selected_candidates=len(rows))
    return rows, denominator, event_record


def copy_input(source, target):
    if source.startswith("root://"):
        subprocess.run(["xrdcp", "--nopbar", "--cksum", "adler32", source, str(target)], check=True)
    else:
        shutil.copyfile(source, target)


def build_dataset(records, cfg, destination, provenance):
    """Stream ROOT chunks into Parquet; memory is bounded by a ROOT chunk."""
    validate_study(cfg)
    with output_workspace(destination) as out, tempfile.TemporaryDirectory(prefix="egm-input-") as scratch:
        writers = {}
        counts = dict(candidates=0, generators=0, events=0)
        sample_counts = {r["sample"]: dict(candidates=0, generators=0, events=0) for r in records}
        seen = set()
        try:
            for record in records:
                path = Path(scratch) / "input.root"
                copy_input(record["path"], path)
                if record.get("sha256") and file_digest(path) != record["sha256"]:
                    raise ValueError(f"Checksum mismatch: {record['path']}")
                with uproot.open(path) as source:
                    for chunk in source["egm/Events"].iterate(step_size="20 MB", library="ak"):
                        batches = dict(candidates=[], generators=[], events=[])
                        for event in ak.to_list(chunk):
                            candidates, generators, summary = event_rows(event, record["sample"], record["sample_config"], cfg)
                            if summary["event_key"] in seen:
                                raise ValueError(f"Duplicate event identity: {summary['event_key']}")
                            seen.add(summary["event_key"])
                            batches["candidates"].extend(candidates)
                            batches["generators"].extend(generators)
                            batches["events"].append(summary)
                            sample_counts[record["sample"]]["events"] += 1
                            sample_counts[record["sample"]]["candidates"] += len(candidates)
                            sample_counts[record["sample"]]["generators"] += len(generators)
                        for name, rows in batches.items():
                            if not rows:
                                continue
                            table = pa.Table.from_pandas(pd.DataFrame(rows), preserve_index=False)
                            if name not in writers:
                                writers[name] = pq.ParquetWriter(out / f"{name}.parquet", table.schema)
                            writers[name].write_table(table)
                            counts[name] += len(rows)
                path.unlink()
        finally:
            for writer in writers.values():
                writer.close()
        if not all(counts.values()):
            raise ValueError(f"Empty dataset component: {counts}; check signal truth/matching and sample choices")
        for record in records:
            statistics = sample_counts[record["sample"]]
            if statistics["candidates"] == 0 or (record["sample_config"]["role"] == "signal" and statistics["generators"] == 0):
                raise ValueError(f"Sample has no selected candidates or signal denominator: {record['sample']}; check truth and matching")
        metadata = dict(config=cfg, config_digest=digest(cfg), counts=counts, per_sample_counts=sample_counts, provenance=provenance,
                        content_sha256={name: file_digest(out / f"{name}.parquet") for name in counts})
        write_json(out / "dataset.json", metadata)
    print(f"Dataset: {destination} ({counts})")


def dataset_from_farm(farm, study, destination):
    farm, manifest = read_farm(farm)
    records = []
    with tempfile.TemporaryDirectory(prefix="egm-receipts-") as scratch:
        for job in manifest["jobs"]:
            receipt_path = Path(scratch) / "receipt.json"
            copy_input(job["output_url"] + ".json", receipt_path)
            report = json.loads(receipt_path.read_text())
            if report.get("local_test") or report.get("fingerprint") != manifest["fingerprint"] or report.get("id") != job["id"] or report.get("files") != job["files"]:
                raise ValueError(f"Receipt does not match the completed production job: {job['id']}")
            records.append(dict(path=job["output_url"], sha256=report["root_sha256"], sample=job["sample"], sample_config=job["sample_config"]))
    build_dataset(records, read_yaml(study), destination, dict(farm_fingerprint=manifest["fingerprint"], jobs=len(records), synthetic=False))


def load_dataset(directory, cfg, max_rows=2_000_000):
    directory = Path(directory)
    metadata = json.loads((directory / "dataset.json").read_text())
    if metadata["config_digest"] != digest(cfg):
        raise ValueError("Study YAML differs from the dataset snapshot; rebuild the dataset")
    if metadata["counts"]["candidates"] > max_rows:
        raise ValueError(f"Dataset exceeds --max-rows={max_rows}; use a larger-memory batch allocation and set the limit explicitly")
    for name, expected in metadata["content_sha256"].items():
        if file_digest(directory / f"{name}.parquet") != expected:
            raise ValueError(f"Dataset file changed: {name}")
    data = pd.read_parquet(directory / "candidates.parquet")
    if data.candidate_key.duplicated().any() or data.groupby("event_key").split.nunique().max() > 1:
        raise ValueError("Duplicate candidates or event leakage")
    if not np.isfinite(data[list(cfg["features"]) + ["weight"]].to_numpy()).all() or (data.weight < 0).any():
        raise ValueError("Invalid feature or training weight")
    if cfg["weights"]["balance_samples"]:
        # Learn sample normalizations from training only, and freeze them for all splits.
        totals = data[data.split == "train"].groupby("sample").weight.sum()
        if set(totals.index) != set(data["sample"]) or (totals <= 0).any():
            raise ValueError("Every sample needs positive training weight")
        data["weight"] = data.weight / data["sample"].map(totals)
    for split in ["train", "validation", "test"]:
        totals = data[data.split == split].groupby("label").weight.sum()
        if set(totals.index) != {0, 1} or (totals <= 0).any():
            raise ValueError(f"Both classes need positive weights in {split}")
    return data, metadata
