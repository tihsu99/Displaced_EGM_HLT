# CMSSW and old-sample compatibility

Select the CMSSW release, SCRAM_ARCH, geometry and GlobalTag from the input
campaign and HLT menu requirements. The production template leaves these fields
unset until the configuration has been identified and tested.
Use separate production YAML files/farms for samples that require different
release/menu/product configurations; never silently mix those environments.

Sources: [official releases](https://github.com/cms-sw/cmssw/releases),
[CMS software documentation](https://cms-sw.github.io/),
[Phase-2 L1 instructions and explicit geometry/era examples](https://twiki.cern.ch/twiki/bin/view/CMSPublic/SWGuideL1TPhase2Instructions).

## Where this project calls CMSSW

The setup follows the ordinary `cmsrel -> cmsenv -> install package -> scram b`
workflow in the README. `cmsrel` creates a SCRAM project; the worker's Bash
`eval "$(scram runtime -sh)"` activates the environment as `cmsenv` does.
See the [CMS workbook](https://twiki.cern.ch/twiki/bin/view/CMSPublic/WorkBookChapter1).

| File | Interaction |
| --- | --- |
| `cmssw/DisplacedEGM/Ntuplizer/plugins/EGMNtuplizer.cc` | Actual C++ EDAnalyzer, installed under `$CMSSW_BASE/src/DisplacedEGM/Ntuplizer` and compiled by SCRAM |
| `cmssw/activate.sh` | Activate the already compiled `cmssw.base`; return to job scratch |
| `cmssw/run_job.py` | Run EDM inspection commands, optional HLT replay, `edmConfigDump`, and `cmsRun` |
| `cmssw/ntuple_cfg.py` | Configure `cms.Process`, EDM input, the analyzer's InputTags, and `TFileService` |
| `cmssw/read_test_cfg.py` | A standalone ten-event EDM I/O probe, without the analyzer or HLT |
| `egm/cmssw.py` | Check the prebuilt package and compiled library against the saved farm |

Steps 2-4 read ordinary ROOT/Parquet using the CVMFS LCG view selected by
`source env.sh` in a separate shell. They neither import CMSSW nor modify its
area. No virtual environment is created. The ntuplizer worker uses the compiled
area's own Python and ROOT after `cmsenv`/`scram runtime -sh` activation.

## GMSB input: 140X versus 16_X

The default production YAML enables this dataset:

```text
/GMSB_L-100TeV_Ctau-1000cm_TuneCP5_14TeV-pythia8/Phase2Spring24DIGIRECOMiniAOD-PU200_Trk1GeV_140X_mcRun4_realistic_v4-v1/GEN-SIM-DIGI-RAW-MINIAOD
```

Its processing name identifies the campaign, PU200 setting and
`140X_mcRun4_realistic_v4` condition tag. It does not identify an exact
`CMSSW_14_0_N[_patchM]` release or geometry. Record the producer release and
geometry from the production recipe/process history. `samples.gmsb.input_global_tag`
records the input tag; it does not set the conditions of a 16_X replay.
This is a combined RAW/MiniAOD tier, not plain MiniAOD. Actual retained RAW,
digis and HLT feature products still require inspection.

There are two different compatibility questions:

- **Read existing products with 16_X:** test the same file with the producing
  14_X release and the intended exact 16_X release. First inspect product types
  and perform the forced read/write probe below; then test the actual analyzer.
  A successful probe demonstrates only that the exercised persisted products
  can be read. It does not create a new HLT reconstruction or prove feature
  equivalence. Changing the reader release alone does not update stored features.
- **Rerun HLT with 16_X:** select a compatible Phase-2 menu, geometry, era, raw/digi
  input sequence, and conditions. Do not substitute a Run-3 GRun menu or blindly
  combine the old GlobalTag with new algorithms. The official HLT guide explicitly
  ties menus to releases/conditions and does not guarantee old-menu compatibility
  in a newer release: [Getting and Running the HLT](https://twiki.cern.ch/twiki/bin/view/CMSPublic/SWGuideGlobalHLT).

A concrete source-level migration detail: the inspected 14_0_X geometry registry
has `Extended2026D98`, whereas 16_0_X has `ExtendedRun4D98`. This shows why an old
configuration may need adaptation; it **does not establish that this dataset uses
D98** or that changing a name proves compatibility. Sources:
[14_0_X GeometryConf](https://github.com/cms-sw/cmssw/blob/CMSSW_14_0_X/Configuration/StandardSequences/python/GeometryConf.py),
[16_0_X GeometryConf](https://github.com/cms-sw/cmssw/blob/CMSSW_16_0_X/Configuration/StandardSequences/python/GeometryConf.py).

Use 14_X with the known campaign recipe as the baseline, and validate 16_X on
the same input/events before choosing it for production. No exact 14_X patch,
16_X compatibility result, HLT menu or geometry is inferred from the dataset name.

### A small I/O test before product labels are known

In a CMS shell with a valid proxy, resolve and stage one file. Keep it on the
same lxplus host for both release tests:

```bash
export EGM_DATASET=/GMSB_L-100TeV_Ctau-1000cm_TuneCP5_14TeV-pythia8/Phase2Spring24DIGIRECOMiniAOD-PU200_Trk1GeV_140X_mcRun4_realistic_v4-v1/GEN-SIM-DIGI-RAW-MINIAOD
dasgoclient --query="file dataset=$EGM_DATASET" > /tmp/gmsb-files.txt
EGM_LFN=$(head -n 1 /tmp/gmsb-files.txt)
test -n "$EGM_LFN"
export EGM_INPUT=/tmp/gmsb-input.root
xrdcp --cksum adler32 "root://cms-xrd-global.cern.ch/$EGM_LFN" "$EGM_INPUT"
```

For each release, start a **fresh shell**, activate that area with `cmsenv`, and
set `EGM_REPO` to your checkout and `EGM_INPUT` to the same staged file:

```bash
EGM_CHECK_DIR=$(mktemp -d /tmp/egm-read-XXXXXX)
printf '%s\n' "$CMSSW_VERSION" "$SCRAM_ARCH" > "$EGM_CHECK_DIR/runtime.txt"
edmProvDump "file:$EGM_INPUT" > "$EGM_CHECK_DIR/provenance.txt"
edmDumpEventContent "file:$EGM_INPUT" > "$EGM_CHECK_DIR/products.txt"
cmsRun -j "$EGM_CHECK_DIR/FrameworkJobReport.xml" \
    "$EGM_REPO/cmssw/read_test_cfg.py" \
    inputFiles="file:$EGM_INPUT" outputFile="$EGM_CHECK_DIR/read_test.root" \
    maxEvents=10 > "$EGM_CHECK_DIR/read_test.log" 2>&1
```

The pset disables fast cloning and writes all retained products for ten events;
it is a stronger I/O check than listing branch names. It requires no ntuplizer
plugin, feature labels or guessed GlobalTag. All output stays under `/tmp`.
It does not rerun reconstruction, validate RAW unpacking, or prove a later event
will be readable. Follow with the actual HLT/analyzer local test.

## The two supported input routes

| Available input | Route | Required evidence |
| --- | --- | --- |
| EDM with pre-ID RecoEcalCandidates, SuperClusters and the feature maps | `mode: existing` | Products, references and map keys are readable by the chosen release |
| RAW-capable EDM / suitable simulation output for a known HLT menu | `mode: rerun` | Replay pset runs the matching geometry, era, conditions, L1 and HLT sequences and persists all necessary products |
| MiniAOD with only slimmed offline electrons/photons | Neither automatically | Find a suitable parent tier or validate a separate offline study; do not call offline quantities HLT quantities |
| NanoAOD | Unsupported | It cannot regenerate dropped HLT EDM products or RAW input |

The data tier name alone is insufficient: an EDM file can be readable while
missing the maps needed for this study. This project does not silently substitute
offline photon features or Run-3 scouting quantities.

## One-file compatibility procedure

1. Resolve the complete dataset and its parentage with DAS. Record the campaign,
   PU conditions, tier and exact file list. Use full dataset names or explicit
   file lists for every enabled sample.
2. In a clean CMS environment, stage one file into `/tmp` and run:

   ```bash
   edmProvDump file:/tmp/input.root > /tmp/input_provenance.txt
   edmDumpEventContent file:/tmp/input.root > /tmp/event_content.txt
   ```

3. Read the producing release and process history. Start from the production/menu
   recipe maintained for that campaign, then test any newer candidate release.
   Confirm the release/architecture exists on the worker OS. This worker assumes
   native compatible CMSSW; historical architectures requiring a container need
   a separately validated container wrapper.
4. Verify geometry, era, GlobalTag and HLT menu against production provenance.
   The YAML provenance fields are records supplied by the analyst, **not** switches
   that magically configure a replay pset. Configure them inside the replay pset.
5. Inspect the actual product type, module, instance and process. `candidates`
   must refer to a `reco::RecoEcalCandidateCollection`; each configured feature is
   a `reco::RecoEcalCandidateIsolationMap` keyed to that exact collection. If the
   menu uses a different type, write a small explicit adapter and test it.
6. Check the candidates/maps are calculated **before** the ID cuts under study.
   A product produced only after a restrictive path filter biases the denominator
   and can be absent for failing events. Rerun an inclusive producer sequence or
   use a validated menu customization rather than dropping those events.
7. Run `egm local-test`. Inspect the saved event content, provenance, resolved
   pset, gen-weight sums, event/candidate counts, and feature distributions.
8. Compare old/new release outputs on the **same file and event range**: event
   identities, candidate multiplicities, each feature, gen labels and ID efficiency.
   Reading without an exception is only the first check, not physics equivalence.

The default worker reuses the already compiled `cmssw.base`; it does not call
`cmsrel`, copy packages into that area or run `scram b`. The source/library
snapshot is checked before submission and before/after the CMSSW worker run.
Keep the entire shared area unchanged during production, including any custom
HLT dependencies not covered by the ntuplizer checksums. The optional
`cmssw.runtime: scratch` mode builds a separate CMSSW area for each worker.

## Replay pset contract

`cmssw.replay_pset` points to a self-contained Python file. The farm copies it to
`cmssw/replay_cfg.py`. It must support standard `VarParsing('analysis')` options:
`inputFiles=...`, `outputFile=replayed.root`, `maxEvents=N`. It must process all
events needed for the denominator, with no output `SelectEvents` trigger skim.
It must persist candidates, referenced SuperClusters/clusters, all configured
feature maps, generator particles (with ancestry), and `GenEventInfoProduct`.

Start from an official campaign-compatible HLT configuration and add the
VarParsing interface and required output commands. An arbitrary generic
`cmsDriver` command would hide the essential menu/geometry decisions, so none is
presented as a ready-to-run physics recipe. In prebuilt mode, imported custom
modules may live in your compiled area, which must remain unchanged. In scratch
mode, they must be provided by the selected release or made self-contained in
the replay pset before preparing the farm.

The extractor only consumes persisted products and needs no geometry or
conditions itself. It fails on missing required products, dropped SuperCluster
references, invalid map keys, nonfinite features and configured sentinel values
(`ntuplizer.invalid_map_values`). It stores both photons and
electrons at generator level; downstream YAML selects the target species.

API references inspected for the plugin:
[RecoEcalCandidateIsolationMap](https://github.com/cms-sw/cmssw/blob/CMSSW_17_0_0/DataFormats/RecoCandidate/interface/RecoEcalCandidateIsolation.h),
[GenParticle status flags](https://github.com/cms-sw/cmssw/blob/CMSSW_17_0_0/DataFormats/HepMCCandidate/interface/GenParticle.h).
Header inspection does not replace compiling the plugin on lxplus.

## Storage contract

HTCondor supplies `_CONDOR_SCRATCH_DIR` for temporary job data, which can disappear
when the job ends: [HTCondor job environment](https://htcondor.readthedocs.io/en/v25_x-branch/users-manual/env-of-job.html).
The worker stages inputs there, writes all intermediates locally, uploads a
checksum-verified temporary EOS object and renames it. The receipt is published
last. A ROOT file alone is not a completed job. Large outputs are excluded from
Condor's automatic transfer to the submit directory; only stdout/stderr and
submission metadata remain there.
