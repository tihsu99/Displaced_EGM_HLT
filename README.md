# Displaced EGM HLT

Produce ROOT ntuples of HLT EGM variables and generator matches, then plot
signal versus background distributions directly from those ntuples.

```text
sample -> L1/HLT reconstruction -> EgammaObject -> gen matching -> ntuple on EOS
ntuple -> plot-variables -> signal/background distributions
```

Use **CMSSW_17_0_0, el9_amd64_gcc13** for the configured Phase2Spring24 inputs.
CMSSW 20_X breaks compatibility with legacy non-RAW data formats; the 20_1_0_pre5
attempt failed while opening the GMSB file. The 17_0_0 dictionaries and HLT
configuration have been source-checked; full sample processing remains unvalidated.
See [CMSSW implementation](docs/cmssw.md) for the compatibility evidence.
Run the following commands in Bash on lxplus EL9.

## 1. Create the CMSSW area and build the ntuplizer

In a fresh shell:

```bash
source /cvmfs/cms.cern.ch/cmsset_default.sh
export SCRAM_ARCH=el9_amd64_gcc13
export EGM_WORKDIR=/absolute/path/to/workdir
mkdir -p "$EGM_WORKDIR"
cd "$EGM_WORKDIR"
cmsrel CMSSW_17_0_0
cd CMSSW_17_0_0/src
cmsenv
git clone https://github.com/tihsu99/Displaced_EGM_HLT.git
scram b -j 8
edmPluginHelp -p EGMNtuplizer
```

Set `EGM_WORKDIR` to your working directory. The clone itself provides the CMSSW
package at `src/Displaced_EGM_HLT/Ntuplizer`; `scram b` builds it in place.
The last command must find `EGMNtuplizer` and list its parameter descriptions.
Parameter values come from the production YAML through the bundled cmsRun
configuration; the generated cfi alone is not a complete job configuration.
Keep the compiled area accessible at the same path from Condor workers.
After editing `Ntuplizer/plugins/EGMNtuplizer.cc`,
run `scram b -j 8` in that CMSSW area and prepare a new farm.

Source layout:

```text
Ntuplizer/plugins/    C++ ntuplizer
Ntuplizer/interface/ Generator matching
Ntuplizer/python/    Shared reconstruction and ntuple configuration
Ntuplizer/test/      cmsRun entry points
scripts/             Condor worker and runtime activation
config/              Sample, production and plotting YAML
```

## 2. Activate analysis tools and set the output location

Open a **second fresh shell**, without `cmsenv`:

```bash
source /cvmfs/cms.cern.ch/cmsset_default.sh
export EGM_WORKDIR=/absolute/path/to/workdir
export EGM_CMSSW_BASE="$EGM_WORKDIR/CMSSW_17_0_0"
cd "$EGM_CMSSW_BASE/src/Displaced_EGM_HLT"
source env.sh
voms-proxy-init --voms cms --valid 192:00
export X509_USER_PROXY=$(voms-proxy-info --path)
export EGM_EOS="root://eosuser.cern.ch//eos/user/${USER:0:1}/$USER/displaced_egm"
python3 -m egm validate config/production.yaml
```

Expect `Configuration valid:` followed by the enabled sample names. The configuration
contains the release, conditions, replay sequence, InputTags and five dataset
names. Change `samples.<name>.enabled` to choose samples; change `campaign` for
each new production. `EGM_EOS` and `EGM_CMSSW_BASE` are the two site-specific paths.

`env.sh` sources `LCG_107/x86_64-el9-gcc14-opt` and checks the analysis libraries.
Its setup path is controlled by `config/environment.sh` or `EGM_LCG_SETUP`.
If that check fails, stop and select a compatible centrally installed view.

## 3. Produce ntuples with Condor

Edit `config/production.yaml`: select the enabled samples and set `storage.eos`
through `EGM_EOS`. The photon defaults are pT > 5 GeV and |etaSC| < 1.44.
`ntuplizer.matching` controls the generator PDG ID, matching cone and displaced
photon propagation to the barrel ECAL. Electron matching requires its own
validated prescription.

Start with one file per enabled sample:

```bash
export EGM_FARM="$HOME/egm-farms/phase2_barrel_1700_ntuple_v2"
python3 -m egm condor config/production.yaml --max-files 1 --farm "$EGM_FARM" --dry-run

# Test the generated shell for the first file of each enabled sample.
for job in "$EGM_FARM"/jobs/*_00000.sh; do
    bash "$job" --local || break
done

# Submit only after every local test prints LOCAL TEST PASSED.
python3 -m egm condor --farm "$EGM_FARM"
condor_q "$USER"
```

`condor --dry-run` creates `jobs/<sample>_<index>.sh`, job configuration and
`jobs.sub`; it does not execute or submit jobs. `bash job.sh --local` runs 100
events without uploading data. Condor executes the same shell without `--local`
for production. Submission checks the frozen source, scripts, configuration and
compiled library, and requires a matching successful test for every sample.
After the pilot passes, use a new campaign/farm and omit `--max-files 1` for full
production. Never overwrite an existing campaign.

Local tests stream CMSSW output to the terminal and retain the same output in
the printed `LOG` path (`<scratch>/worker.log`). Stage messages identify CMS
setup, input inspection, `cmsRun` and ntuple validation. For a job already
running, use `tail -f <scratch>/worker.log` on the same lxplus host. Condor jobs
keep the full log in scratch and print its last 100 lines on processing failure.

Each worker activates the prebuilt CMSSW area and reads its `root://` inputs
directly. Reconstruction, matching and ntuple writing run in one `cmsRun`;
the ntuple, generated configurations and logs stay in `_CONDOR_SCRATCH_DIR`.
Set `production.stage_inputs: true` only to copy each complete input file to
scratch before processing. The default is `false`, including for local tests.
Only the final ntuple and small job provenance/receipt files are uploaded to
`storage.eos/<campaign>/<sample>/`. Successful workers remove their scratch area.
AFS holds code and small submission files. Failed/local jobs retain diagnostics.
The outer worker uses system XRootD tools for optional input copies and EOS
uploads; `cmsRun` uses the selected CMSSW runtime. Changes to the YAML or worker
scripts require preparing a new farm with `--dry-run`.

The ROOT tree `egm/Events` stores kinematics, `s_major`, `s_minor`, shower shapes,
isolations, generator particles and per-candidate matching fields:
`matched_gen_index`, `match_dr`, `match_pdg_id`, `match_prompt`, `match_llp`,
`match_gen_fiducial`. Unmatched objects have index and distance -1.
`egm/metadata` records the sample, variable sources, matching settings and CMSSW
configuration. Missing required EGM variables fail the job rather than becoming
zero. Events with zero accepted objects are retained.

## 4. Plot signal versus background

Once the jobs finish and their completion receipts are present, point the plot
command at the final ROOT ntuples on mounted EOS:

```bash
export EGM_NTUPLES="/eos/user/${USER:0:1}/$USER/displaced_egm/phase2_barrel_1700_ntuple_v2"
python3 -m egm plot-variables --inputs "$EGM_NTUPLES"/*/*.root --config config/plots.yaml --output "$EGM_NTUPLES/plots"
```

Use the mounted path corresponding to your configured `storage.eos`; explicit
`root://` input URLs also work. Input files are buffered in local temporary
storage one at a time. The output directory must be new.

`config/plots.yaml` controls variable names, binning, labels, colors and log axes.
The command writes PNG/PDF overlays, including `s_major.png` and `s_minor.png`,
and a `distributions.json` record of bin contents, counts and provenance.
It reads the stored matching results; no training or intermediate analysis table
is required.

GMSB signal uses LLP-matched photons; H to gamma gamma uses prompt-matched photons.
Both require the stored generator fiducial flag. Background uses all selected
HLT candidates. Each sample is normalized separately with absolute generator
weights; overlapping QCD samples are not added together. Underflow/overflow are
included in the edge bins. These are shape comparisons, not cross sections or
trigger rates. Plot inputs with incompatible definitions or duplicate jobs are
rejected.
