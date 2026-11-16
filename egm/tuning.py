"""Fit on train, choose settings/working points on validation, leave test untouched."""
import json
from pathlib import Path

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import log_loss, roc_auc_score
from sklearn.model_selection import ParameterGrid

from .config import digest, read_yaml, validate_study, write_json
from .data import load_dataset, output_workspace


def efficiency(mask, weights):
    weights = np.asarray(weights, dtype=float)
    total = weights.sum()
    if total <= 0:
        raise ValueError("Efficiency denominator has no positive weight")
    return float(weights[np.asarray(mask, dtype=bool)].sum() / total)


def pass_cuts(data, cuts, features):
    result = np.ones(len(data), dtype=bool)
    for name, threshold in cuts.items():
        result &= data[name].to_numpy() <= threshold if features[name]["direction"] == "less" else data[name].to_numpy() >= threshold
    return result


def weighted_quantile(values, weights, quantiles):
    order = np.argsort(values)
    values, weights = np.asarray(values)[order], np.asarray(weights)[order]
    positive = weights > 0
    values, weights = values[positive], weights[positive]
    cumulative = np.cumsum(weights) / weights.sum()
    indices = np.searchsorted(cumulative, quantiles, side="left")
    return values[np.minimum(indices, len(values) - 1)]


def wp_threshold(scores, weights, target):
    # score >= threshold includes tied scores, preserving the requested efficiency.
    return float(weighted_quantile(scores, weights, [1 - target])[0])


def model_header(kind, cfg, metadata):
    return dict(kind=kind, features=list(cfg["features"]), feature_spec=cfg["features"], config_digest=digest(cfg),
                dataset_sha256=metadata["content_sha256"], provenance=metadata["provenance"],
                weight_policy=cfg["weights"], working_points={})


def tune_cuts(dataset, study, output, max_rows=2_000_000):
    cfg = validate_study(read_yaml(study))
    data, metadata = load_dataset(dataset, cfg, max_rows)
    train = data[data.split == "train"]
    valid = data[data.split == "validation"]
    signal = train[train.label == 1]
    rng = np.random.default_rng(cfg["seed"])
    names = list(cfg["features"])
    # Randomly allocate a total rejection budget across variables, then use signal quantiles.
    budget = rng.uniform(0, 1, cfg["cuts"]["trials"])
    fractions = rng.dirichlet(np.ones(len(names)), len(budget))
    quantiles = 1 - fractions * budget[:, None]
    trials = []
    for index, name in enumerate(names):
        spec = cfg["features"][name]
        q = quantiles[:, index] if spec["direction"] == "less" else 1 - quantiles[:, index]
        thresholds = weighted_quantile(signal[name], signal.weight, q)
        loose = spec["max"] if spec["direction"] == "less" else spec["min"]
        trials.append(np.r_[loose, np.clip(thresholds, spec["min"], spec["max"])])
    best = {}
    train_s, valid_s = train.label.to_numpy() == 1, valid.label.to_numpy() == 1
    for values in np.array(trials).T:
        cuts = dict(zip(names, map(float, values)))
        passed = pass_cuts(train, cuts, cfg["features"])
        train_eff = efficiency(passed[train_s], train.weight.to_numpy()[train_s])
        possible = [target for target in cfg["working_points"] if train_eff >= target]
        if not possible:
            continue
        passed = pass_cuts(valid, cuts, cfg["features"])
        seff = efficiency(passed[valid_s], valid.weight.to_numpy()[valid_s])
        beff = efficiency(passed[~valid_s], valid.weight.to_numpy()[~valid_s])
        for target in possible:
            if seff >= target and (target not in best or (beff, seff - target) < (best[target][0], best[target][1] - target)):
                best[target] = (beff, seff, cuts, train_eff)
    model = model_header("cuts", cfg, metadata)
    for target in cfg["working_points"]:
        if target not in best:
            raise ValueError(f"No cut point reaches signal efficiency {target}; inspect bounds/statistics or increase trials")
        beff, seff, cuts, train_eff = best[target]
        model["working_points"][str(target)] = dict(cuts=cuts, validation_signal_efficiency=seff,
                                                  validation_background_efficiency=beff, train_signal_efficiency=train_eff)
    with output_workspace(output) as out:
        write_json(out / "model.json", model)
        write_json(out / "study.json", cfg)
    print(f"Cut model: {output}/model.json")
    return model


def export_bdt(estimator):
    trees = []
    for stage in estimator.estimators_:
        tree = stage[0].tree_
        trees.append(dict(left=tree.children_left.tolist(), right=tree.children_right.tolist(),
                          feature=tree.feature.tolist(), threshold=tree.threshold.tolist(), value=tree.value[:, 0, 0].tolist()))
    prior = estimator.init_.class_prior_
    return dict(base_score=float(np.log(prior[1] / prior[0])), learning_rate=float(estimator.learning_rate), trees=trees)


def predict_bdt(model, data):
    x = np.asarray(data[model["features"]], dtype=np.float32)
    raw = np.full(len(x), model["ensemble"]["base_score"])
    for tree in model["ensemble"]["trees"]:
        nodes = np.zeros(len(x), dtype=int)
        left, right, features = (np.asarray(tree[key]) for key in ["left", "right", "feature"])
        thresholds = np.asarray(tree["threshold"])
        active = left[nodes] != -1
        while active.any():
            rows = np.flatnonzero(active)
            node = nodes[rows]
            nodes[rows] = np.where(x[rows, features[node]] <= thresholds[node], left[node], right[node])
            active = left[nodes] != -1
        raw += model["ensemble"]["learning_rate"] * np.asarray(tree["value"])[nodes]
    return 1 / (1 + np.exp(-np.clip(raw, -700, 700)))


def tune_bdt(dataset, study, output, max_rows=2_000_000):
    import sklearn
    cfg = validate_study(read_yaml(study))
    data, metadata = load_dataset(dataset, cfg, max_rows)
    train, valid = (data[data.split == split] for split in ["train", "validation"])
    features = list(cfg["features"])
    best, history = None, []
    for params in ParameterGrid(cfg["bdt"]["grid"]):
        classifier = GradientBoostingClassifier(random_state=cfg["seed"], **params)
        classifier.fit(train[features], train.label, sample_weight=train.weight)
        scores = classifier.predict_proba(valid[features])[:, 1]
        auc = float(roc_auc_score(valid.label, scores, sample_weight=valid.weight))
        history.append(dict(parameters=params, validation_auc=auc))
        if best is None or auc > best[0]:
            best = (auc, classifier, scores, params)
    if best is None:
        raise ValueError("Empty BDT parameter grid")
    auc, classifier, scores, params = best
    model = model_header("bdt", cfg, metadata)
    model.update(ensemble=export_bdt(classifier), sklearn_version=sklearn.__version__, parameters=params,
                 validation_auc=auc, grid_history=history)
    exported = predict_bdt(model, valid)
    np.testing.assert_allclose(exported, scores, rtol=1e-9, atol=1e-10)
    signal = valid.label.to_numpy() == 1
    for target in cfg["working_points"]:
        threshold = wp_threshold(scores[signal], valid.weight.to_numpy()[signal], target)
        model["working_points"][str(target)] = dict(threshold=threshold,
            validation_signal_efficiency=efficiency(scores[signal] >= threshold, valid.weight.to_numpy()[signal]),
            validation_background_efficiency=efficiency(scores[~signal] >= threshold, valid.weight.to_numpy()[~signal]))
    learning = {}
    for name, frame in [("train", train), ("validation", valid)]:
        learning[name] = [float(log_loss(frame.label, probability, sample_weight=frame.weight, labels=[0, 1]))
                          for probability in classifier.staged_predict_proba(frame[features])]
    model["learning_curve"] = learning
    model["feature_importance"] = dict(zip(features, map(float, classifier.feature_importances_)))
    with output_workspace(output) as out:
        write_json(out / "model.json", model)
        write_json(out / "study.json", cfg)
    print(f"BDT model: {output}/model.json")
    return model


def read_model(path, cfg, metadata, kind):
    model = json.loads(Path(path).read_text())
    if model["kind"] != kind or model["config_digest"] != digest(cfg) or model["dataset_sha256"] != metadata["content_sha256"]:
        raise ValueError(f"Model/config/dataset mismatch: {path}")
    return model
