# Validation checklist

## Software checks

Run the synthetic demo and inspect `evaluation/roc.png`, `bdt_confusion.png`,
`learning_curve.png` and the per-sample displacement efficiencies. Read the small
JSON model and use `apply-id` to check the exported model's inference interface.
The demo exercises all analysis stages without production credentials or a
CMSSW build.
Start from the repository root with `source env.sh` in a fresh lxplus Bash shell.
Analysis packages come from CVMFS; CMSSW execution uses `cmsenv`. No virtual
environment or package installation is required or used by the workflow.

```bash
source env.sh
python3 scripts/check_environment.py --tests
python3 -m pytest -q
python3 -m egm demo --output /tmp/$USER-egm-demo
```

Use a new demo output directory for each run.

## Production checks

- Obtain one exact dataset/file for each enabled sample and its campaign recipe.
- Fill CMSSW release, architecture, conditions provenance and HLT product labels.
- Create the CMSSW area with cmsrel, install the package and run scram b once.
  Set runtime: prebuilt and base in YAML; keep the shared area unchanged in jobs.
- Ensure the signal ancestry survives the chosen generator collection.
- Compile the plugin and run every sample's local test on lxplus.
- Inspect all feature definitions and ranges, generator labels, matched fractions
  and prompt/LLP efficiencies separately. Scan the photon match DeltaR and ECAL
  geometry approximation; test electron matching separately if needed.
- Submit a one-file Condor pilot, inspect EOS ROOT/provenance/receipt, then prepare
  the complete production farm with a fresh campaign name.
- Build the dataset only from a complete farm. Save its config and hashes with
  the models. Verify train/validation/test statistics for every sample.

## Required campaign inputs

Each campaign needs full DAS dataset names or file lists, an HLT menu and its
customizations, GlobalTag, geometry, process/product labels and an EOS output
location. Electron studies also need suitable signal samples. Comparisons with
an existing ID require its complete cut definitions. Record and validate these
inputs before production. Current production support is MC with
GenEventInfoProduct and reco::GenParticleCollection; real data and packed-only
generator inputs need an explicit adapter.

The production YAML includes a complete Phase2Spring24 GMSB dataset name.
Its 140X condition-tag spelling does not establish
the exact producer patch release, geometry, retained HLT products or compatibility
with 16_X. Follow the two-release I/O and HLT checks in
[CMSSW compatibility](cmssw.md).

## Validation boundary

Python tests exercise production-manifest guards, staging failure behavior,
displaced matching, ancestry precedence, zero-candidate denominators, event
splitting, checksums, portable BDT predictions and synthetic end-to-end outputs.
Runtime tests simulate shell activation, dependency failures and rejection of
changed compiled libraries after a local-test receipt. Synthetic plots carry
a visible software-test label.

These checks do not compile C++ or run CMSSW, access DAS/EOS, submit Condor jobs,
validate conditions/geometry, reproduce physics performance, or establish HLT
latency. The selected CVMFS view and the production chain still require lxplus
validation. Run the checks there and retain the logs with the campaign results.

For CMSSW errors, inspect the scratch `worker.log`, saved event content and
resolved pset. For batch stage-out errors, an output without a receipt is
incomplete. Keep or archive the artifact for diagnosis before reusing a name.
No automated destructive cleanup or blind resubmission is part of this workflow.
