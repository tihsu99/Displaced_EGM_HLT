"""Plot stored HLT variables directly from matched ROOT ntuples."""
import json
import os
from pathlib import Path
import tempfile

import numpy as np


def selected_objects(arrays, sample):
    """Signal uses its stored truth match; background retains every stored object."""
    if sample["role"] == "background":
        return np.ones(len(arrays["pt"]), dtype=bool)
    if sample["role"] != "signal" or sample["truth"] not in {"prompt", "llp"}:
        raise ValueError("Signal samples require prompt or llp truth")
    mask = (arrays["matched_gen_index"] >= 0) & (arrays["match_gen_fiducial"] != 0)
    if sample["truth"] == "llp":
        return mask & (arrays["match_llp"] != 0)
    return mask & (arrays["match_prompt"] != 0) & (arrays["match_llp"] == 0)


def histogram(values, weights, edges):
    values, weights, edges = (np.asarray(x, dtype=float) for x in (values, weights, edges))
    if len(edges) < 2 or not np.isfinite(edges).all() or not (np.diff(edges) > 0).all():
        raise ValueError("Histogram edges must be finite and strictly increasing")
    if values.shape != weights.shape or not np.isfinite(values).all() or not np.isfinite(weights).all() or (weights < 0).any():
        raise ValueError("Histogram values and nonnegative weights must be finite and aligned")
    # Fold tails into edge bins; normalization includes every selected object.
    clipped = np.clip(values, edges[0], edges[-1])
    sumw = np.histogram(clipped, bins=edges, weights=weights)[0]
    sumw2 = np.histogram(clipped, bins=edges, weights=weights**2)[0]
    return sumw, sumw2, int((values < edges[0]).sum()), int((values > edges[-1]).sum())


def bin_edges(spec):
    if "edges" in spec:
        edges = np.asarray(spec["edges"], dtype=float)
    else:
        count = spec["bins"]
        if not isinstance(count, int) or count < 1:
            raise ValueError("bins must be a positive integer")
        edges = np.linspace(spec["min"], spec["max"], count + 1)
    histogram([], [], edges)
    return edges


def plot_variables(inputs, config, output):
    import awkward as ak
    import uproot
    from .config import read_yaml, write_json
    from .data import copy_input, output_workspace

    cfg = read_yaml(config)
    if cfg["weights"] not in {"absolute", "unit"}:
        raise ValueError("Plot weights must be absolute or unit")
    variables = cfg["variables"]
    if not variables or any(not name.replace("_", "").isalnum() for name in variables):
        raise ValueError("Configure named plot variables")
    edges = {name: bin_edges(spec) for name, spec in variables.items()}
    required = {"pt", "matched_gen_index", "match_gen_fiducial", "match_llp", "match_prompt"}
    required |= set(variables) - {"shape_asymmetry"}
    if "shape_asymmetry" in variables:
        required |= {"s_major", "s_minor"}
    if not inputs or len(inputs) != len(set(inputs)):
        raise ValueError("Supply distinct ntuple ROOT files")
    samples, jobs, contract = {}, set(), None
    with tempfile.TemporaryDirectory(prefix="egm-plot-input-") as scratch:
        for source in inputs:
            path = Path(scratch) / "ntuple.root"
            copy_input(source, path)
            with uproot.open(path) as root:
                metadata = json.loads(root["egm/metadata"].member("fTitle"))
                if metadata.get("schema_version") != 2:
                    raise ValueError(f"Expected a ntuple with stored gen matching: {source}")
                identity = (metadata["fingerprint"], metadata["job_id"])
                if identity in jobs:
                    raise ValueError(f"Duplicate ntuple job: {identity}")
                jobs.add(identity)
                current = dict(ntuplizer=metadata["ntuplizer"], release=metadata["cmssw"]["release"],
                               provenance=metadata["cmssw"]["provenance"], synthetic=metadata.get("synthetic", False))
                if contract is not None and contract != current:
                    raise ValueError("Ntuples use different reconstruction, selection, matching, or variable definitions")
                contract = current
                name, sample = metadata["sample"], metadata["sample_config"]
                if name not in samples:
                    samples[name] = dict(config=sample, fingerprint=metadata["fingerprint"], events=0,
                                         objects=0, selected=0, sumw=0., files=[], histograms={
                                             variable: dict(sumw=np.zeros(len(bins)-1), sumw2=np.zeros(len(bins)-1),
                                                            underflow=0, overflow=0) for variable, bins in edges.items()})
                result = samples[name]
                if result["config"] != sample or result["fingerprint"] != metadata["fingerprint"]:
                    raise ValueError(f"Mixed production definitions for sample {name}")
                result["files"].append(source)
                tree = root["egm/Events"]
                missing = (required | {"gen_weight"}) - set(tree.keys())
                if missing:
                    raise ValueError(f"Missing stored branches in {source}: {sorted(missing)}")
                for chunk in tree.iterate(expressions=sorted(required | {"gen_weight"}), step_size="20 MB", library="ak"):
                    arrays = {key: ak.to_numpy(ak.flatten(chunk[key])) for key in required}
                    mask = selected_objects(arrays, sample)
                    weights = ak.to_numpy(ak.flatten(ak.broadcast_arrays(chunk.gen_weight, chunk.pt)[0]))
                    weights = np.abs(weights) if cfg["weights"] == "absolute" else np.ones_like(weights)
                    weights = weights[mask]
                    result["events"] += len(chunk)
                    result["objects"] += len(mask)
                    result["selected"] += int(mask.sum())
                    result["sumw"] += float(weights.sum())
                    for variable in variables:
                        if variable == "shape_asymmetry":
                            major, minor = arrays["s_major"][mask], arrays["s_minor"][mask]
                            if ((major + minor) <= 0).any():
                                raise ValueError("Undefined shape asymmetry; inspect s_major and s_minor")
                            values = (major - minor) / (major + minor)
                        else:
                            values = arrays[variable][mask]
                        counts, squared, under, over = histogram(values, weights, edges[variable])
                        hist = result["histograms"][variable]
                        hist["sumw"] += counts
                        hist["sumw2"] += squared
                        hist["underflow"] += under
                        hist["overflow"] += over
            path.unlink()
    if {s["config"]["role"] for s in samples.values()} != {"signal", "background"}:
        raise ValueError("Supply both signal and background ntuples")
    for name, result in samples.items():
        if result["sumw"] <= 0:
            raise ValueError(f"No positive-weight selected objects for {name}; inspect matching or increase statistics")

    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "egm-matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    with output_workspace(output) as out:
        for variable, spec in variables.items():
            fig, ax = plt.subplots(figsize=(7, 5))
            for name, result in samples.items():
                style = cfg.get("samples", {}).get(name, {})
                hist = result["histograms"][variable]
                fraction = hist["sumw"] / result["sumw"]
                ax.stairs(fraction, edges[variable], label=style.get("label", name),
                          color=style.get("color"), linewidth=1.8,
                          linestyle="-" if result["config"]["role"] == "signal" else "--")
            ax.set(xlabel=spec.get("label", variable), ylabel="Fraction of selected objects / bin",
                   xlim=(edges[variable][0], edges[variable][-1]))
            if spec.get("log_y", False):
                ax.set_yscale("log")
            ax.legend(fontsize=9)
            selection = contract["ntuplizer"]["selection"]
            ax.set_title(f"HLT EGM: pT > {selection['pt_min']:g} GeV, |etaSC| < {selection['abs_eta_max']:g}",
                         loc="right", fontsize=9)
            ax.text(0, 1.01, "CMS Simulation", transform=ax.transAxes, fontsize=12)
            fig.text(0.5, 0.01, "Signal: truth matched; background: all selected objects. Tails included in edge bins.",
                     ha="center", fontsize=8)
            if contract["synthetic"]:
                fig.suptitle("SYNTHETIC SOFTWARE TEST", color="darkred")
            fig.tight_layout(rect=(0, 0.035, 1, 0.96))
            for suffix in ["png", "pdf"]:
                fig.savefig(out / f"{variable}.{suffix}", dpi=160)
            plt.close(fig)
        for result in samples.values():
            for hist in result["histograms"].values():
                for key in ["sumw", "sumw2"]:
                    hist[key] = hist[key].tolist()
        write_json(out / "distributions.json", dict(config=cfg, contract=contract, samples=samples,
                    edges={name: values.tolist() for name, values in edges.items()},
                    normalization="Per-sample unit area, including tails; not a cross-section or trigger rate"))
    print(f"Variable plots: {output}")
