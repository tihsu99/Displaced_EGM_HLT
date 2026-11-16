"""Synthetic plumbing test; deliberately not a detector simulation."""
from pathlib import Path

import awkward as ak
import numpy as np
import uproot
import yaml

from .config import ROOT, read_yaml
from .data import build_dataset, output_workspace
from .evaluation import evaluate
from .tuning import tune_bdt, tune_cuts


def make_root(path, sample, events, seed):
    rng = np.random.default_rng(seed)
    signal = sample != "qcd"
    llp = sample == "gmsb"
    float_vectors = ["pt", "eta", "phi", "sc_eta", "sc_phi", "sigma_ieta_ieta", "s_major", "s_minor",
                     "hoe", "ecal_iso", "hcal_iso", "r9", "track_iso", "gen_pt", "gen_eta", "gen_phi", "gen_vx", "gen_vy", "gen_vz"]
    int_vectors = ["gen_pdg_id", "gen_prompt", "gen_llp"]
    columns = {name: [] for name in float_vectors + int_vectors}
    for _ in range(events):
        pt, eta, phi = rng.uniform(6, 200), rng.uniform(-1.3, 1.3), rng.uniform(-np.pi, np.pi)
        radius = rng.uniform(0.01, 100) if llp else 0.0
        x, y = radius * np.cos(phi), radius * np.sin(phi)
        z = radius * np.sinh(eta)
        reconstructed = rng.random() < (0.85 if signal else 0.9)
        vals = dict(pt=pt, eta=eta, phi=phi, sc_eta=eta, sc_phi=phi,
                    sigma_ieta_ieta=abs(rng.normal(0.011 if signal else 0.022, 0.008)),
                    s_major=abs(rng.normal(0.7 if signal else 1.2, 0.45)),
                    s_minor=abs(rng.normal(0.2 if signal else 0.35, 0.14)),
                    hoe=rng.exponential(0.045 if signal else 0.12),
                    ecal_iso=rng.exponential(5 if signal else 11),
                    hcal_iso=rng.exponential(4 if signal else 10),
                    r9=np.clip(rng.normal(0.91 if signal else 0.73, 0.13), 0, 1.1),
                    track_iso=rng.exponential(3 if signal else 9))
        gen = dict(gen_pt=pt, gen_eta=eta, gen_phi=phi, gen_vx=x, gen_vy=y, gen_vz=z,
                   gen_pdg_id=22, gen_prompt=int(not llp), gen_llp=int(llp))
        for name in float_vectors + int_vectors:
            columns[name].append([gen[name]] if name in gen and signal else [vals[name]] if name in vals and reconstructed else [])
    types = {name: "var * float32" for name in float_vectors}
    types.update({name: "var * int32" for name in int_vectors})
    types.update(run="uint32", lumi="uint32", event="uint64", gen_weight="float64")
    columns = {name: ak.Array(value) for name, value in columns.items()}
    columns.update(run=np.ones(events, dtype=np.uint32), lumi=np.ones(events, dtype=np.uint32),
                   event=np.arange(1, events + 1, dtype=np.uint64), gen_weight=np.where(rng.random(events) < 0.05, -1.0, 1.0))
    with uproot.recreate(path) as output:
        output.mktree("egm/Events", types)
        output["egm/Events"].extend(columns)


def demo(destination, events=1000):
    if events < 100:
        raise ValueError("Use at least 100 events per sample for the demo")
    # An outer scratch workspace ensures no partial result is mistaken for a finished demo.
    with output_workspace(destination) as out:
        cfg = read_yaml(ROOT / "config/study.yaml")
        cfg["cuts"]["trials"] = 300
        cfg["bdt"]["grid"] = dict(n_estimators=[40], learning_rate=[0.1], max_depth=[2], min_samples_leaf=[10], subsample=[0.8])
        (out / "study.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
        records = []
        for i, name in enumerate(["gmsb", "hgg", "qcd"]):
            path = out / (name + ".root")
            make_root(path, name, events, cfg["seed"] + i)
            records.append(dict(path=str(path), sample=name,
                                sample_config=dict(role="background" if name == "qcd" else "signal",
                                                   truth="all" if name == "qcd" else "llp" if name == "gmsb" else "prompt")))
        build_dataset(records, cfg, out / "dataset", dict(synthetic=True, description="Synthetic software test, not CMSSW or physics validation"))
        tune_cuts(out / "dataset", out / "study.yaml", out / "cuts")
        tune_bdt(out / "dataset", out / "study.yaml", out / "bdt")
        evaluate(out / "dataset", out / "study.yaml", out / "cuts/model.json", out / "bdt/model.json", out / "evaluation")
    print(f"Synthetic end-to-end demo complete: {destination}")
