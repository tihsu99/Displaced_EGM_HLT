"""Production and plotting commands. Heavy imports are stage-local."""
import argparse
import json
from pathlib import Path
import sys

from .config import ROOT, read_yaml, validate_production


def parser():
    p = argparse.ArgumentParser(prog="egm", description="HLT EGM ntuples on Condor and signal/background variable plots")
    commands = p.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Check production YAML without querying DAS")
    validate.add_argument("config")
    condor = commands.add_parser("condor", help="Create job shells with --dry-run; submit a tested farm without it")
    condor.add_argument("config", nargs="?", help="Production YAML; supplied only when creating jobs")
    condor.add_argument("--farm", required=True)
    condor.add_argument("--dry-run", action="store_true")
    condor.add_argument("--samples", nargs="+")
    condor.add_argument("--max-files", type=int)
    prepare = commands.add_parser("prepare", help="Resolve datasets and freeze source/configuration")
    prepare.add_argument("config")
    prepare.add_argument("--farm", required=True)
    prepare.add_argument("--samples", nargs="+")
    prepare.add_argument("--max-files", type=int)
    local = commands.add_parser("local-test", help="Run the production worker locally on one file per sample")
    local.add_argument("--farm", required=True)
    local.add_argument("--sample")
    local.add_argument("--n", type=int, help="Event limit per local job; overrides production.local_test_events")
    submit = commands.add_parser("submit", help="Require matching local tests, then submit to Condor")
    submit.add_argument("--farm", required=True)
    submit.add_argument("--dry-run", action="store_true")
    plots = commands.add_parser("plot-variables", help="Plot signal/background variables directly from matched ROOT ntuples")
    plots.add_argument("--inputs", nargs="+", required=True, help="Local/EOS ROOT paths or explicit XRootD URLs")
    plots.add_argument("--config", default=str(ROOT / "config/plots.yaml"))
    plots.add_argument("--output", required=True, help="New output directory on mounted EOS or /tmp")
    dataset = commands.add_parser("dataset", help="Verify EOS receipts and build independent event splits")
    dataset.add_argument("--farm", required=True)
    dataset.add_argument("--study", default=str(ROOT / "config/study.yaml"))
    dataset.add_argument("--output", required=True)
    for name in ["tune-cuts", "tune-bdt", "evaluate"]:
        stage = commands.add_parser(name)
        stage.add_argument("--dataset", required=True)
        stage.add_argument("--study", default=str(ROOT / "config/study.yaml"))
        stage.add_argument("--output", required=True)
        stage.add_argument("--max-rows", type=int, default=2_000_000)
        if name == "evaluate":
            stage.add_argument("--cuts", required=True, help="Cut model JSON")
            stage.add_argument("--bdt", required=True, help="BDT model JSON")
    apply = commands.add_parser("apply-id", help="Apply a portable JSON ID to a feature Parquet table")
    apply.add_argument("--input", required=True)
    apply.add_argument("--model", required=True)
    apply.add_argument("--working-point", required=True, type=float)
    apply.add_argument("--output", required=True)
    demo = commands.add_parser("demo", help="Run a synthetic ROOT -> ID -> evaluation test without CMSSW")
    demo.add_argument("--output", required=True)
    demo.add_argument("--events", type=int, default=1000, help="Events per synthetic sample")
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    try:
        if args.command == "validate":
            samples = validate_production(read_yaml(args.config))
            print("Configuration valid:", ", ".join(samples))
        elif args.command == "condor":
            from .production import prepare, submit
            if args.dry_run:
                if not args.config:
                    raise ValueError("Pass production YAML when creating jobs with --dry-run")
                prepare(args.config, args.farm, args.samples, args.max_files)
                print((Path(args.farm) / "jobs.sub").read_text())
            else:
                if args.config or args.samples or args.max_files is not None:
                    raise ValueError("Submission uses the frozen farm; omit configuration and sample overrides")
                submit(args.farm)
        elif args.command == "prepare":
            from .production import prepare
            prepare(args.config, args.farm, args.samples, args.max_files)
        elif args.command == "local-test":
            from .production import local_test
            local_test(args.farm, args.sample, args.n)
        elif args.command == "submit":
            from .production import submit
            submit(args.farm, args.dry_run)
        elif args.command == "plot-variables":
            from .distributions import plot_variables
            plot_variables(args.inputs, args.config, args.output)
        elif args.command == "dataset":
            from .data import dataset_from_farm
            dataset_from_farm(args.farm, args.study, args.output)
        elif args.command in ["tune-cuts", "tune-bdt"]:
            from .tuning import tune_bdt, tune_cuts
            function = tune_cuts if args.command == "tune-cuts" else tune_bdt
            function(args.dataset, args.study, args.output, args.max_rows)
        elif args.command == "evaluate":
            from .evaluation import evaluate
            evaluate(args.dataset, args.study, args.cuts, args.bdt, args.output, args.max_rows)
        elif args.command == "apply-id":
            import numpy as np
            import pandas as pd
            from .data import output_workspace
            from .tuning import pass_cuts, predict_bdt
            model = json.loads(Path(args.model).read_text())
            frame = pd.read_parquet(args.input)
            if not np.isfinite(frame[model["features"]].to_numpy()).all():
                raise ValueError("Input features must be finite")
            wp = model["working_points"][str(args.working_point)]
            if model["kind"] == "bdt":
                frame["id_score"] = predict_bdt(model, frame)
                frame["id_pass"] = frame.id_score >= wp["threshold"]
            elif model["kind"] == "cuts":
                frame["id_pass"] = pass_cuts(frame, wp["cuts"], model["feature_spec"])
            else:
                raise ValueError("Unknown model kind")
            with output_workspace(args.output) as out:
                frame.to_parquet(out / "predictions.parquet", index=False)
        elif args.command == "demo":
            from .demo import demo
            demo(args.output, args.events)
    except (ValueError, KeyError, FileNotFoundError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
