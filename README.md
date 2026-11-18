# Displaced EGM HLT

Develop cut-based and BDT photon IDs for the CMS Phase-2 HLT: reconstruct HLT
features, produce ntuples on EOS, tune IDs, and evaluate held-out events.
The default study uses Phase2Spring24 PU200 samples, pT > 5 GeV and |etaSC| < 1.44.

The current **unvalidated candidate** is **CMSSW_20_1_0_pre5, el9_amd64_gcc14**,
selected from the release list checked on 2026-11-18. Compatibility with the
configured 140X GMSB sample has not been established. The profile uses D110 geometry,
`Phase2C17I13M9`, `auto:phase2_realistic_T35` and the `75e33` HLT producers.
The release and producer definitions are source-checked. Choose the working
release only after the actual sample passes HLT replay and ntuple production
with a clean exit and validated output; source inspection alone is insufficient.
See [CMSSW sources and implementation](docs/cmssw.md).

Run these commands in Bash on lxplus EL9. CMSSW uses `cmsenv`; analysis uses a
CVMFS LCG view. Run each step only after the previous command succeeds.

## 1. Create the CMSSW area and build the ntuplizer

In a fresh shell:

```bash
source /cvmfs/cms.cern.ch/cmsset_default.sh
export SCRAM_ARCH=el9_amd64_gcc14
export EGM_WORKDIR=/absolute/path/to/workdir
mkdir -p "$EGM_WORKDIR"
cd "$EGM_WORKDIR"
cmsrel CMSSW_20_1_0_pre5
cd CMSSW_20_1_0_pre5/src
cmsenv
git clone https://github.com/tihsu99/Displaced_EGM_HLT.git
scram b -j 8
edmPluginHelp -p EGMNtuplizer
```

Set `EGM_WORKDIR` to your working directory. The clone itself provides the CMSSW
package at `src/Displaced_EGM_HLT/Ntuplizer`; `scram b` builds it in place.
The last command must find `EGMNtuplizer`. Keep the compiled area accessible at
the same path from Condor workers. After editing `Ntuplizer/plugins/EGMNtuplizer.cc`,
run `scram b -j 8` in that CMSSW area and prepare a new farm.

## 2. Activate analysis tools and set the output location

Open a **second fresh shell**, without `cmsenv`:

```bash
source /cvmfs/cms.cern.ch/cmsset_default.sh
export EGM_WORKDIR=/absolute/path/to/workdir
export EGM_CMSSW_BASE="$EGM_WORKDIR/CMSSW_20_1_0_pre5"
cd "$EGM_CMSSW_BASE/src/Displaced_EGM_HLT"
source env.sh
voms-proxy-init --voms cms --valid 192:00
export X509_USER_PROXY=$(voms-proxy-info --path)
export EGM_EOS="root://eosuser.cern.ch//eos/user/${USER:0:1}/$USER/displaced_egm"
export EGM_RESULTS="/eos/user/${USER:0:1}/$USER/displaced_egm/study_v1"
cp config/production.yaml config/my_production.yaml
python3 -m egm validate config/my_production.yaml
```

Expect `Configuration valid:` followed by the enabled sample names. The template
contains the release, conditions, replay sequence, InputTags and five dataset
names. Change `samples.<name>.enabled` to choose samples; change `campaign` for
each new production. `EGM_EOS` and `EGM_CMSSW_BASE` are the two site-specific paths.

`env.sh` sources `LCG_107/x86_64-el9-gcc14-opt` and checks the analysis libraries.
Its setup path is controlled by `config/environment.sh` or `EGM_LCG_SETUP`.
If that check fails, stop and select a compatible centrally installed view.

## 3. Run one GMSB file locally

Continue in the analysis shell:

```bash
export EGM_PILOT=/tmp/$USER-egm-pilot-v1
python3 -m egm prepare config/my_production.yaml --samples gmsb --max-files 1 --farm "$EGM_PILOT"
python3 -m egm local-test --farm "$EGM_PILOT"
```

`prepare` resolves the input with DAS and freezes the code, configuration and
compiled plugin checksums. `local-test` activates CMSSW, stages one file in `/tmp`,
reruns the configured HLT producers for 100 events, and writes the ntuple. It
does not submit jobs or upload event data.

Expect `LOCAL TEST PASSED; ROOT and logs: ...`. In that printed scratch directory,
inspect `worker.log`, `event_content.txt`, `replay_metadata.json`,
`replay_config.py`, `inspection.json` and `ntuple.root`. A failure stops here;
the end of `worker.log` is also printed. Successful output must close cleanly and
contain nonzero event and candidate counts.

The replay schedules feature producers for every event, without L1 or ID filters.
It lowers the supercluster ET threshold from 10 to 0 GeV; the 5 GeV analysis cut
is applied later. `hoe` is the HLT hadronic-energy map divided by candidate energy.
See [feature definitions](docs/cmssw.md#feature-definitions).

## 4. Submit the one-file Condor pilot

```bash
python3 -m egm submit --farm "$EGM_PILOT" --dry-run
```

This prints the submit description. To submit that pilot:

```bash
python3 -m egm submit --farm "$EGM_PILOT"
condor_q "$USER"
```

Workers run in `_CONDOR_SCRATCH_DIR`. Successful jobs upload the ROOT ntuple and
provenance archive to EOS, then publish a JSON completion receipt. Check for all
three files under `phase2_barrel_201pre5_v1/gmsb/` at your EOS destination.
The pilot processes the whole first file in batch; the local test processes only
`production.local_test_events`. Neither output represents the complete sample.

## 5. Produce all enabled samples

Set a new campaign name so full production does not collide with the pilot:

```bash
python3 - <<'PY'
from pathlib import Path
import yaml
path = Path("config/my_production.yaml")
config = yaml.safe_load(path.read_text())
config["campaign"] = "phase2_barrel_201pre5_full_v1"
path.write_text(yaml.safe_dump(config, sort_keys=False))
PY
export EGM_FARM="$HOME/egm-farms/phase2_barrel_201pre5_full_v1"
python3 -m egm prepare config/my_production.yaml --farm "$EGM_FARM"
python3 -m egm local-test --farm "$EGM_FARM"
python3 -m egm submit --farm "$EGM_FARM" --dry-run
```

The local test must pass for every enabled sample. After reviewing the dry run:

```bash
python3 -m egm submit --farm "$EGM_FARM"
```

The farm holds small job descriptions, source snapshots and Condor logs. Event
data and replay intermediates stay in scratch; completed ntuples go to EOS.
Keep the farm and compiled area unchanged while jobs run. Existing outputs are
never overwritten. Inspect incomplete output before retrying a failed job.

## 6. Build the dataset, tune IDs and evaluate

After every job has a completion receipt, run from the repository root in the
analysis environment. Use a batch allocation for full datasets; the automated
Condor commands above cover ntuple production.

```bash
python3 -m egm dataset --farm "$EGM_FARM" --study config/study.yaml --output "$EGM_RESULTS/dataset"
python3 -m egm tune-cuts --dataset "$EGM_RESULTS/dataset" --study config/study.yaml --output "$EGM_RESULTS/cuts"
python3 -m egm tune-bdt --dataset "$EGM_RESULTS/dataset" --study config/study.yaml --output "$EGM_RESULTS/bdt"
python3 -m egm evaluate --dataset "$EGM_RESULTS/dataset" --study config/study.yaml --cuts "$EGM_RESULTS/cuts/model.json" --bdt "$EGM_RESULTS/bdt/model.json" --output "$EGM_RESULTS/evaluation"
```

Expect candidate, generator and event Parquet tables; two `model.json` files;
and evaluation PNG/PDF plots with JSON metrics. `dataset` verifies the receipts
and ROOT checksums. Analysis outputs use a mounted EOS path and are first written
in local temporary storage. Use new output directories for another run.

The default event split is 60/20/20 for training, validation and testing.
`config/study.yaml` controls matching, features, cut bounds, BDT parameters,
working points and plot bins. Tuning loads candidates into memory and limits
input to two million rows unless `--max-rows` is set explicitly. Cut working points
are optimized independently and need not be nested. Evaluation reports object
efficiencies and event acceptance, not a trigger rate in Hz.

## 7. Apply an exported ID

```bash
python3 -m egm apply-id --input "$EGM_RESULTS/dataset/candidates.parquet" --model "$EGM_RESULTS/bdt/model.json" --working-point 0.8 --output "$EGM_RESULTS/applied_bdt"
```

The result is `predictions.parquet` with scores and ID decisions. Inputs must use
the same feature definitions and selection as training. Deployment inside an
HLT filter and latency measurements are separate from this offline workflow.

## Software checks and further reading

For a synthetic end-to-end check in the analysis shell:

```bash
python3 scripts/check_environment.py --tests
python3 -m pytest -q
python3 -m egm demo --output /tmp/$USER-egm-demo
```

Synthetic checks exercise analysis and workflow logic. A CMSSW build,
sample-level replay, Condor pilot and EOS receipt are required before production.

- [CMSSW sources and implementation](docs/cmssw.md)
- [Physics definitions and limits](docs/physics.md)
- [Validation checklist](docs/handoff.md)
