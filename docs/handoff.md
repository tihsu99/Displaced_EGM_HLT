# Student handoff

## A first useful milestone

Run the synthetic demo and inspect `evaluation/roc.png`, `bdt_confusion.png`,
`learning_curve.png` and the per-sample displacement efficiencies. Read the small
JSON model and use `apply-id`. This teaches the four-stage interface without
waiting for production credentials or a CMSSW build.
Start from the repository root with `source env.sh` in a fresh lxplus Bash shell.
Analysis packages come from CVMFS; CMSSW execution uses `cmsenv`. No virtual
environment or package installation is required or used by the workflow.

## First real-data milestone

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

## Deliberately unresolved inputs

The provided slides do not identify the full DAS datasets, file lists, exact
HLT menu/customizations, GlobalTag, geometry, process/product labels, EOS output
location, electron signal samples, or all original cut formulas. The templates
leave these choices explicit. They cannot be certified by guessing a recent
CMSSW release. Current production support is MC with GenEventInfoProduct and
reco::GenParticleCollection; real data and packed-only generator inputs need an
explicit adapter.

The user subsequently supplied the complete Phase2Spring24 GMSB dataset, now
recorded in production YAML. Its 140X condition-tag spelling does not establish
the exact producer patch release, geometry, retained HLT products or compatibility
with 16_X. Follow the two-release I/O and HLT checks in `docs/cmssw.md`.

## Validation boundary

Local validation on 2026-11-16: 25 Python tests passed. The standalone demo
processed 2,400 synthetic events, produced 2,087 candidate rows and 1,600
generator-denominator rows, trained/exported both IDs, and rendered the complete
evaluation. ROC, confusion and displacement plots were visually inspected.
Synthetic plots carry a visible software-test label. These counts demonstrate
the software contract only.

After the prebuilt-runtime update, 29 Python tests passed, including simulated
shell activation in both runtime modes and rejection of a changed compiled
library after a successful local-test receipt. These simulations do not execute
a real SCRAM build or establish 140X-to-16_X sample compatibility.

After switching the documented setup to direct CVMFS/cmsenv use, eight focused
environment tests passed with the host Python and standard-library unittest.
They cover view sourcing, version/import failures and mixed-environment rejection.
The local Mac has no CVMFS mount, so the full suite and demo have not yet been
rerun under the selected LCG view. Run the environment check and suite on lxplus;
the earlier synthetic tests do not certify the CVMFS runtime.

Python tests exercise production-manifest guards, staging failure behavior,
displaced matching, ancestry precedence, zero-candidate denominators, event
splitting, checksums, portable BDT predictions and synthetic end-to-end outputs.
They do not compile C++ or run CMSSW, access DAS/EOS, submit Condor jobs, validate
conditions/geometry, reproduce the slide numbers, or establish HLT latency.

For CMSSW errors, inspect the scratch `worker.log`, saved event content and
resolved pset. For batch stage-out errors, an output without a receipt is
incomplete. Keep or archive the artifact for diagnosis before reusing a name.
No automated destructive cleanup or blind resubmission is part of this workflow.
