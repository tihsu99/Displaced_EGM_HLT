# Displaced EGM HLT

A small, independent workflow for a PhD student studying prompt/displaced photon
identification at the Phase-2 HLT. The default physics scope follows the supplied
26-page *Phase2 HLT: Displaced photon* slides: Phase2Spring24 PU200, barrel,
reconstructed pT > 5 GeV, prompt H -> gamma gamma and GMSB photons versus QCD.
The requested classifier is a BDT; the slides use a DNN.

**Scouting_EGM_ID is a read-only reference.** This project neither imports it nor
modifies, runs, or links to its code. Its useful patterns are YAML configuration,
scratch-based production, separate training and validation, and portable ID output.
The implementation here is independent; the old tuner is not silently reused.

**Status:** the Python workflow can be exercised using synthetic ROOT inputs.
The CMSSW plugin, actual Phase-2 samples, HLT replay, Condor and EOS still require
the lxplus checks below. No sample/release compatibility or physics performance
is certified by a passing synthetic test. Production YAML deliberately leaves
unknown product labels, release and runtime conditions unset. The supplied
Phase2Spring24 GMSB dataset is recorded; its content has not yet been tested.

## Student interface

| Step | Command | What you edit | Result |
| --- | --- | --- | --- |
| 1. Ntuplizer | `prepare`, `local-test`, `submit` | `config/production.yaml` | ROOT + completion receipt + provenance on EOS |
| Dataset | `dataset` | `config/study.yaml` | Candidate, generator, and event Parquet tables |
| 2. Cut ID | `tune-cuts` | Feature bounds/directions and target efficiencies | Portable cut JSON |
| 3. BDT ID | `tune-bdt` | Features and BDT parameter grid | Portable tree JSON, validation working points |
| 4. Evaluation | `evaluate` | Bins and the working point to display | ROC, confusion, shapes, correlations, loss, efficiencies |
| Inference | `apply-id` | Model path and working point | Parquet with ID decisions/scores |

The train/validation/test split is 60/20/20 by **event**, shared by all candidates
and generator denominators. Hyperparameters and thresholds use validation; the
test split is reserved for the final evaluation. Nothing trains directly on
displacement or generator labels as input features.

## First session: software demo

Use the centrally installed software directly: `cmsenv` for the CMSSW ntuplizer,
and a CVMFS LCG view for dataset preparation, ID tuning and evaluation. No virtual
environment or package installation is part of this workflow. Run the analysis
commands from the repository root so Python can import `egm` directly.

In a fresh **Bash** shell on lxplus EL9:

```bash
source env.sh
python3 -m egm --help
python3 -m egm demo --output /tmp/$USER-egm-demo
python3 scripts/check_environment.py --tests
python3 -m pytest -q
```

`env.sh` follows the reference project's direct `source /cvmfs/.../setup.sh`
pattern. The view is selected in `config/environment.sh`, defaulting to
`LCG_107/x86_64-el9-gcc14-opt`. This published view is listed in the
[CERN LCG_107 announcement](https://spi.web.cern.ch/2025/02/06/lcg-107-announce.html).
Override `EGM_LCG_SETUP` with another validated CVMFS setup path if needed.
The wrapper checks actual imports and minimum versions from `pyproject.toml`;
it never installs missing packages. The reference's older LCG_102b selection
is not assumed compatible with this project's Python >= 3.10, Uproot 5 and
Awkward 2 requirements. Availability of a view is not an end-to-end validation.

Keep the LCG analysis shell separate from the CMSSW build/runtime shell. If you
want to run an analysis command directly under `cmsenv`, first run
`python3 scripts/check_environment.py` in that shell; all analysis dependencies
must be present. Do not source the LCG view on top of `cmsenv` to fill gaps.
`pyproject.toml` describes the required libraries; the supported entry point is
`python3 -m egm`, without an editable install. An existing `uv.lock` is not used
to select or build the production runtime.

The demo creates synthetic ROOT inputs, builds the dataset, tunes both IDs,
exports/reloads the BDT, and generates evaluation plots. Its outputs are clearly
marked synthetic. It does not exercise CMSSW, HLT or storage authentication.
Use a new output directory on each run; existing results are never overwritten.

## Step 1: lxplus production

1. Copy `config/production.yaml` to a personal config in this repository.
2. Fill full DAS names (or explicit ROOT URLs), data tier, CMSSW release and
   architecture, conditions provenance, and the EOS output URL. Enable only the
   samples you intend to process. The slide only supplies sample short names.
3. Follow [CMSSW compatibility](docs/cmssw.md) to inspect one file and identify
   the **pre-ID** EGM collection and its feature maps. Fill the InputTags in YAML.
4. Choose `cmssw.mode: existing` if the needed HLT products are persisted, or
   `rerun` with a self-contained, campaign-compatible HLT replay pset.

First create and compile a CMSSW area using the usual CMS development workflow.
`EGM_REPO` is the absolute path of your checkout, outside the CMSSW area.
Set `EGM_RELEASE` and `SCRAM_ARCH` to the exact release/architecture you want to
test; the dataset's `140X` GlobalTag prefix does not identify a patch release.

```bash
source /cvmfs/cms.cern.ch/cmsset_default.sh
export EGM_REPO=/absolute/path/to/Displaced_EGM_HLT
export EGM_RELEASE=CMSSW_X_Y_Z
export SCRAM_ARCH=YOUR_VALIDATED_SCRAM_ARCH
cmsrel "$EGM_RELEASE"
cd "$EGM_RELEASE/src"
cmsenv
mkdir -p DisplacedEGM
cp -R "$EGM_REPO/cmssw/DisplacedEGM/Ntuplizer" DisplacedEGM/
scram b -j 8
edmPluginHelp -p EGMNtuplizer
```

The copy installs this checkout's C++ package at CMSSW's required two-level
package path; clone/update the repository before this step when working on
lxplus. If `DisplacedEGM/Ntuplizer` already exists, inspect and synchronize its
source instead of copying another directory into it. When the code changes,
update that package and run `scram b` again. Record `$CMSSW_BASE`,
`$CMSSW_VERSION` and `$SCRAM_ARCH` in `cmssw.base`, `release` and `scram_arch` in
your YAML. Keep the compiled area on a filesystem accessible to batch workers
at the same absolute path. `/tmp` is unsuitable for a shared batch runtime.

The default is `cmssw.runtime: prebuilt`: compile once, then activate the same
area for local and Condor runs. `prepare` checks the installed package against
this checkout and saves source/library checksums. Rebuilding or changing that
package/library invalidates the farm and its local-test receipts. Do not edit
the shared area while jobs run; custom replay dependencies also need to remain
unchanged. Only this ntuplizer's source/library are checksum-tracked.

Start in a fresh lxplus shell with CMS tools and a valid CMS proxy available.
Do not activate an LCG/Coffea environment inside the worker. `dasgoclient`,
`xrdcp`, `xrdfs`, `condor_submit`, `voms-proxy-info`, and CVMFS must be available.

```bash
source /cvmfs/cms.cern.ch/cmsset_default.sh
voms-proxy-init --voms cms --valid 192:00
export X509_USER_PROXY=$(voms-proxy-info --path)
source env.sh

python3 -m egm validate config/my_production.yaml
export EGM_FARM=/tmp/$USER-egm-farm-v1
python3 -m egm prepare config/my_production.yaml --farm "$EGM_FARM"
python3 -m egm local-test --farm "$EGM_FARM"
python3 -m egm submit --farm "$EGM_FARM" --dry-run
python3 -m egm submit --farm "$EGM_FARM"
```

`prepare --samples gmsb --max-files 1` prepares a smaller pilot farm. Local tests
use the first input file of each selected sample and `production.local_test_events`.
The same worker and frozen source run locally and in batch. **Do not use a
one-file pilot's output as the full production dataset.** Prepare a full farm,
test it, then submit it when ready. A farm is a small snapshot, jobs, manifests,
and logs; it may live in AFS if you need durable submission metadata. Do not
submit from EOS. `/tmp` farms need to be archived before the submit node cleans
them; keep `manifest.json`, job JSONs, source archive and worker files together.

Each worker activates the configured area with `scram runtime -sh` (the Bash
equivalent of `cmsenv`), returns to `_CONDOR_SCRATCH_DIR` (or `/tmp` for a local
test), and executes `cmsRun`. There is no build in the default worker flow.
Staged input files, optional HLT replay output, ROOT ntuple and logs all stay in
scratch. The job needs disk for all of them together; measure before increasing
files/job. The earlier per-worker build remains opt-in with
`cmssw.runtime: scratch`; it uses `cmssw.build_jobs` and ignores `cmssw.base`.

Successful batch jobs copy ROOT and provenance to EOS using checksum-verified
XRootD, then publish the JSON receipt last. Interrupted output without a receipt
is not accepted as complete. No existing output is overwritten. If stage-out
partly succeeds, inspect/archive that job's artifacts before retrying; automatic
resubmission is intentionally not provided. A failed local job prints its scratch
path; inspect `worker.log`. Batch failure logs are forwarded to the Condor error
log; worker scratch may be deleted by Condor at exit.

The local test verifies reading, the selected compiled plugin, product availability,
nonempty events/candidates and ROOT schema. It does **not** certify HLT physics,
global-tag/geometry correctness, all files of a sample, or EOS write permission.
Run a one-file Condor pilot and inspect the EOS receipt before a full campaign.

## Steps 2-4: datasets, tuning, evaluation

Use an EOS **mounted path** for final analysis artifacts. Every stage writes in
local temporary storage first and copies completed artifacts to the destination.
The ntuplizer uses XRootD URLs; analysis output uses filesystem paths. No large
data is written under this repository or AFS.
Start these commands from the repository root in the LCG shell (`source env.sh`).

```bash
export EGM_RESULTS=/eos/user/u/username/displaced_egm/study_v1
python3 -m egm dataset --farm "$EGM_FARM" --study config/study.yaml \
    --output "$EGM_RESULTS/dataset"
python3 -m egm tune-cuts --dataset "$EGM_RESULTS/dataset" --study config/study.yaml \
    --output "$EGM_RESULTS/cuts"
python3 -m egm tune-bdt --dataset "$EGM_RESULTS/dataset" --study config/study.yaml \
    --output "$EGM_RESULTS/bdt"
python3 -m egm evaluate --dataset "$EGM_RESULTS/dataset" --study config/study.yaml \
    --cuts "$EGM_RESULTS/cuts/model.json" --bdt "$EGM_RESULTS/bdt/model.json" \
    --output "$EGM_RESULTS/evaluation"
```

`dataset` requires a receipt for every job in the farm and verifies the ROOT
SHA256 before reading. It streams ROOT chunks to Parquet and detects duplicate
event identities. Candidate tables preserve sample, event identity, truth category,
signed generator weight and displacement. A separate generator table includes
unmatched signal particles, and an event table includes zero-candidate events.
The event-identity index grows with the number of events; allocate adequate RAM.

Tuning loads candidates into memory and refuses more than 2 million rows by
default. For a larger study, request an appropriate batch memory allocation and
set `--max-rows` explicitly. No silent truncation or resampling occurs. Full-scale
dataset conversion/training should run in a batch allocation rather than occupy
a shared lxplus login node. The automated Condor interface currently covers
Step 1; Steps 2-4 use these same CLI commands in your chosen allocation.

The cut tuner searches signal-quantile thresholds within YAML bounds and requires
the target signal efficiency on both train and validation. Working points are
optimized independently and are **not guaranteed to be nested**. The BDT uses
`GradientBoostingClassifier`, selects its grid point by weighted validation AUC,
then freezes validation thresholds. JSON export is numerically compared with
the fitted classifier. `apply-id` uses only JSON and input features, without
deserializing Python pickle objects:

```bash
python3 -m egm apply-id --input "$EGM_RESULTS/dataset/candidates.parquet" \
    --model "$EGM_RESULTS/bdt/model.json" --working-point 0.8 \
    --output "$EGM_RESULTS/applied_bdt"
```

Input features must have the same definitions, units and preselection used in
training. The application command does not apply reconstruction or preselection.
These exported IDs are for offline studies; deploying a BDT in an HLT filter,
CMSSW model conversion and latency validation are separate work.

## Where students develop

| File | Responsibility |
| --- | --- |
| `config/production.yaml` | Samples, CMSSW, product labels, scratch/EOS/Condor |
| `env.sh`, `config/environment.sh` | Direct CVMFS analysis setup, with no local environment creation |
| `config/study.yaml` | Acceptance, matching, features, tuning and plots |
| `cmssw/DisplacedEGM/Ntuplizer/plugins/EGMNtuplizer.cc` | Lossless extraction of the configured products |
| `cmssw/ntuple_cfg.py` | CMSSW extraction configuration |
| `scripts/worker.py` | Scratch lifecycle and stage-out |
| `egm/production.py` | Frozen jobs, local-test gate, Condor submission |
| `egm/data.py` | Truth, matching, event splits, denominators |
| `egm/tuning.py` | Cut/BDT fitting and portable inference |
| `egm/evaluation.py` | Held-out plots and explicit denominators |
| `tests/` | Synthetic physics-logic and workflow regression checks |

Read [physics choices](docs/physics.md), [CMSSW compatibility](docs/cmssw.md), and
[the handoff checklist](docs/handoff.md) before interpreting a result.
