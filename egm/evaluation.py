"""Held-out diagnostics: object ID, generator acceptance, and per-sample performance."""
import os
from pathlib import Path
import tempfile

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "egm-matplotlib"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix, roc_auc_score, roc_curve

from .config import read_yaml, validate_study, write_json
from .data import load_dataset, output_workspace
from .tuning import efficiency, pass_cuts, predict_bdt, read_model


def interval(passed, weight):
    """Positive-weight efficiency and an approximate effective-N Wilson interval."""
    weight = np.asarray(weight, dtype=float)
    total = float(weight.sum())
    if total <= 0:
        return dict(efficiency=None, low=None, high=None, effective_n=0.0, entries=len(weight))
    value = efficiency(passed, weight)
    neff = total * total / float(np.square(weight).sum())
    center = (value + 0.5 / neff) / (1 + 1 / neff)
    half = np.sqrt(value * (1 - value) / neff + 0.25 / neff**2) / (1 + 1 / neff)
    return dict(efficiency=value, low=max(0.0, min(value, float(center - half))), high=min(1.0, max(value, float(center + half))),
                effective_n=neff, entries=len(weight))


def classification_metrics(labels, passed, weights):
    cm = confusion_matrix(labels, passed.astype(int), sample_weight=weights, labels=[0, 1])
    tn, fp, fn, tp = cm.ravel()
    precision = float(tp / (tp + fp)) if tp + fp > 0 else None
    recall = float(tp / (tp + fn)) if tp + fn > 0 else None
    return dict(confusion_matrix=cm.tolist(), accuracy=float((tp + tn) / cm.sum()), precision=precision,
                recall=recall, f1=float(2 * tp / (2 * tp + fp + fn)) if 2 * tp + fp + fn > 0 else None)


def save(fig, out, name, synthetic=False):
    if synthetic:
        fig.suptitle("SYNTHETIC SOFTWARE TEST", fontsize=10, color="darkred")
    fig.tight_layout()
    fig.savefig(out / (name + ".png"), dpi=150)
    fig.savefig(out / (name + ".pdf"))
    plt.close(fig)


def evaluate(dataset, study, cuts_path, bdt_path, output, max_rows=2_000_000):
    cfg = validate_study(read_yaml(study))
    data, metadata = load_dataset(dataset, cfg, max_rows)
    cuts = read_model(cuts_path, cfg, metadata, "cuts")
    bdt = read_model(bdt_path, cfg, metadata, "bdt")
    test = data[data.split == "test"].copy()
    wp = str(cfg["evaluation"]["working_point"])
    test["bdt_score"] = predict_bdt(bdt, test)
    test["cuts_pass"] = pass_cuts(test, cuts["working_points"][wp]["cuts"], cfg["features"])
    test["bdt_pass"] = test.bdt_score >= bdt["working_points"][wp]["threshold"]
    summary = dict(provenance=metadata["provenance"], working_point=float(wp),
                   denominator="Selected reconstructed candidates; signal requires unique truth matching",
                   weight_policy=cfg["weights"], uncertainty="Approximate effective-N Wilson; no signed-weight inference",
                   rate_hz=None, rate_note="Overlapping QCD samples are separate shape studies; no rate normalization supplied",
                   test_auc=float(roc_auc_score(test.label, test.bdt_score, sample_weight=test.weight)), per_sample={})
    synthetic = metadata["provenance"].get("synthetic", False)
    for name in ["cuts", "bdt"]:
        summary[name] = classification_metrics(test.label, test[name + "_pass"].to_numpy(), test.weight)
    for sample, frame in test.groupby("sample"):
        summary["per_sample"][sample] = {name: interval(frame[name + "_pass"], frame.weight) for name in ["cuts", "bdt"]}
    with output_workspace(output) as out:
        test.to_parquet(out / "test_predictions.parquet", index=False)
        fig, ax = plt.subplots(figsize=(6, 5))
        fpr, tpr, _ = roc_curve(test.label, test.bdt_score, sample_weight=test.weight)
        ax.plot(fpr, tpr, label=f"BDT test AUC = {summary['test_auc']:.3f}")
        points = []
        for target, point in cuts["working_points"].items():
            mask = pass_cuts(test, point["cuts"], cfg["features"])
            signal = test.label.to_numpy() == 1
            seff = efficiency(mask[signal], test.weight.to_numpy()[signal])
            beff = efficiency(mask[~signal], test.weight.to_numpy()[~signal])
            points.append(dict(target=float(target), signal_efficiency=seff, background_efficiency=beff))
            ax.scatter(beff, seff, label=f"Cuts target {target}")
        summary["cut_roc_points"] = points
        ax.set(xlabel="Background object efficiency", ylabel="Signal object efficiency", xlim=(0, 1), ylim=(0, 1))
        ax.legend(fontsize=8)
        save(fig, out, "roc", synthetic)
        for name in ["cuts", "bdt"]:
            matrix = np.array(summary[name]["confusion_matrix"])
            fractions = matrix / matrix.sum(axis=1, keepdims=True)
            fig, ax = plt.subplots(figsize=(5, 4))
            ax.imshow(fractions, vmin=0, vmax=1, cmap="Blues")
            for row in range(2):
                for col in range(2):
                    ax.text(col, row, f"{fractions[row, col]:.1%}", ha="center", va="center", color="white" if fractions[row, col] > 0.5 else "black")
            ax.set(xticks=[0, 1], yticks=[0, 1], xticklabels=["Reject", "Accept"], yticklabels=["Background", "Signal"],
                   xlabel="ID decision", ylabel="Truth", title=f"{name.upper()} test (weighted, row normalized)")
            save(fig, out, name + "_confusion", synthetic)
        fig, ax = plt.subplots(figsize=(6, 4))
        for sample, frame in test.groupby("sample"):
            ax.hist(frame.bdt_score, bins=np.linspace(0, 1, 41), weights=frame.weight / frame.weight.sum(),
                    histtype="step", label=sample)
        ax.set(xlabel="BDT score", ylabel="Weighted fraction / bin")
        ax.legend(fontsize=8)
        save(fig, out, "bdt_scores", synthetic)
        fig, ax = plt.subplots(figsize=(6, 4))
        for split, losses in bdt["learning_curve"].items():
            ax.plot(np.arange(1, len(losses) + 1), losses, label=split)
        ax.set(xlabel="Boosting stage", ylabel="Weighted log loss")
        ax.legend()
        save(fig, out, "learning_curve", synthetic)
        variables = list(dict.fromkeys(["pt"] + list(cfg["features"])))
        for variable in variables:
            fig, ax = plt.subplots(figsize=(6, 4))
            lo, hi = np.quantile(test[variable], [0.001, 0.999])
            if hi <= lo:
                hi = lo + 1
            bins = np.linspace(lo, hi, 41)
            for sample, frame in test.groupby("sample"):
                ax.hist(frame[variable], bins=bins, weights=frame.weight / frame.weight.sum(), histtype="step", label=sample)
            ax.set(xlabel=variable, ylabel="Weighted fraction / bin", title="Test distributions (0.1-99.9% displayed)")
            ax.legend(fontsize=7)
            save(fig, out, "feature_" + variable, synthetic)
        for label in [0, 1]:
            frame = test[test.label == label]
            covariance = np.cov(frame[list(cfg["features"])] .to_numpy().T, aweights=frame.weight)
            scale = np.sqrt(np.diag(covariance))
            correlation = np.divide(covariance, np.outer(scale, scale), out=np.zeros_like(covariance), where=np.outer(scale, scale) > 0)
            fig, ax = plt.subplots(figsize=(8, 7))
            plot = ax.imshow(correlation, vmin=-1, vmax=1, cmap="coolwarm")
            ax.set(xticks=np.arange(len(scale)), yticks=np.arange(len(scale)), xticklabels=list(cfg["features"]),
                   yticklabels=list(cfg["features"]), title="Signal" if label else "Background")
            plt.setp(ax.get_xticklabels(), rotation=60, ha="right")
            fig.colorbar(plot, ax=ax)
            save(fig, out, "correlation_" + ("signal" if label else "background"), synthetic)
        efficiencies = []
        for sample, frame in test.groupby("sample"):
            for variable, bins in cfg["evaluation"]["bins"].items():
                for low, high in zip(bins[:-1], bins[1:]):
                    subset = frame[(frame[variable] >= low) & (frame[variable] < high)]
                    for name in ["cuts", "bdt"]:
                        efficiencies.append(dict(sample=sample, variable=variable, low_edge=low, high_edge=high,
                                                 model=name, denominator="reconstructed", **interval(subset[name + "_pass"], subset.weight)))
        gen = pd.read_parquet(Path(dataset) / "generators.parquet")
        gen = gen[gen.split == "test"]
        passed_keys = {name: set(test.loc[test[name + "_pass"], "candidate_key"]) for name in ["cuts", "bdt"]}
        for sample, frame in gen.groupby("sample"):
            for variable, bins in cfg["evaluation"]["bins"].items():
                for low, high in zip(bins[:-1], bins[1:]):
                    subset = frame[(frame[variable] >= low) & (frame[variable] < high)]
                    for name in ["cuts", "bdt"]:
                        passed = subset.candidate_key.isin(passed_keys[name])
                        efficiencies.append(dict(sample=sample, variable=variable, low_edge=low, high_edge=high,
                                                 model=name, denominator="generator_fiducial", **interval(passed, subset.weight)))
        # Event acceptance includes events with zero EGM candidates; it is not a rate in Hz.
        events = pd.read_parquet(Path(dataset) / "events.parquet")
        events = events[events.split == "test"]
        summary["event_acceptance"] = {}
        for sample, frame in events.groupby("sample"):
            summary["event_acceptance"][sample] = {}
            for name in ["cuts", "bdt"]:
                accepted = set(test.loc[test[name + "_pass"], "event_key"])
                summary["event_acceptance"][sample][name] = interval(frame.event_key.isin(accepted), frame.weight)
        write_json(out / "efficiencies.json", efficiencies)
        write_json(out / "metrics.json", summary)
        for denominator in ["reconstructed", "generator_fiducial"]:
            for variable in cfg["evaluation"]["bins"]:
                fig, ax = plt.subplots(figsize=(7, 5))
                relevant = [row for row in efficiencies if row["denominator"] == denominator and row["variable"] == variable]
                for sample in sorted({row["sample"] for row in relevant}):
                    for name, style in [("cuts", "--"), ("bdt", "-")]:
                        rows = [row for row in relevant if row["sample"] == sample and row["model"] == name and row["efficiency"] is not None]
                        if rows:
                            ax.errorbar([(r["low_edge"] + r["high_edge"]) / 2 for r in rows], [r["efficiency"] for r in rows],
                                        yerr=[[r["efficiency"] - r["low"] for r in rows], [r["high"] - r["efficiency"] for r in rows]],
                                        fmt="o" + style, ms=3, label=f"{sample} {name}")
                ax.set(xlabel=variable + (" [cm]" if variable.startswith("gen_") else ""), ylabel="Efficiency", ylim=(0, 1.05), title=denominator)
                if ax.lines:
                    ax.legend(fontsize=7)
                save(fig, out, f"efficiency_{denominator}_{variable}", synthetic)
        (out / "README.md").write_text(
            "# Evaluation\n\n" + ("SYNTHETIC SOFTWARE TEST. No physics performance claim.\n\n" if metadata["provenance"].get("synthetic") else "") +
            "All reported performance uses held-out events. Working points and BDT settings were selected on validation.\n\n"
            "`roc`, confusion matrices, score distributions, feature distributions, class correlations, and the BDT learning curve correspond to the slide's diagnostics.\n\n"
            "`efficiencies.json` separates conditional reconstructed-object ID efficiency from generator-fiducial reconstruction-times-ID efficiency. "
            "Displacement is the generator production vertex relative to the detector origin, in cm. "
            "Generator pt/eta bins use generated kinematics; reconstructed pt/eta bins use candidate kinematics.\n\n"
            "Weights are positive training/shape weights. Precision depends on this chosen mixture. "
            "QCD inclusive, EM-enriched and bcToE overlap; do not add these samples for a physical trigger rate. "
            "The event acceptance assumes at least one passing object, with no L1 seed, trigger-path thresholds, or prescales.\n\n"
            "A lower validation loss alone does not demonstrate absence of overtraining. Check split distributions, statistics, and independent samples.\n")
    print(f"Evaluation: {output}")
    return summary
