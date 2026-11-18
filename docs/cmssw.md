# CMSSW profile and implementation

## Candidate release: sample compatibility unverified

The default is **CMSSW_20_1_0_pre5** with **el9_amd64_gcc14**, checked on
2026-11-18 against the [release list](https://github.com/cms-sw/cmssw/releases).
It is the newest standard prerelease listed, published on 2026-10-30; special
builds such as `_PY314` and integration builds are excluded from this choice.
The [build request](https://github.com/cms-sw/cmssw/issues/52339) records completion
for EL9 GCC14, and the [release notes](https://github.com/cms-sw/cmssw/releases/tag/CMSSW_20_1_0_pre5)
identify the same architecture. This is a candidate for testing, not a verified
working release for the configured 140X samples. A successful build record or
campaign recipe does not establish that the exact GMSB file can be processed.

## Input campaign and reconstruction settings

| Setting | Value |
| --- | --- |
| Input campaign | Phase2Spring24DIGIRECOMiniAOD, PU200 |
| Input data tier | GEN-SIM-DIGI-RAW-MINIAOD |
| Input conditions | `140X_mcRun4_realistic_v4` |
| Replay geometry | `ExtendedRun4D110` |
| Replay era | `Phase2C17I13M9` |
| Replay conditions | `auto:phase2_realistic_T35` |
| HLT menu / process | `75e33` / `HLTX` |
| Aging customization | `customise_aging_1000` |

The release's [recipe for 14X inputs](https://github.com/cms-sw/cmssw/blob/CMSSW_20_1_0_pre5/DPGAnalysis/Phase2L1TNanoAOD/README.md)
specifies D110, this era, T35 conditions and the aging customization for
Phase2Spring24. Its L1/NanoAOD steps are not part of this ID extraction path.
The [geometry registry](https://github.com/cms-sw/cmssw/blob/CMSSW_20_1_0_pre5/Configuration/StandardSequences/python/GeometryConf.py)
retains D110; the [geometry description](https://github.com/cms-sw/cmssw/blob/CMSSW_20_1_0_pre5/Configuration/Geometry/README.md)
identifies its tracker as T35.

The [autoCond base](https://github.com/cms-sw/cmssw/blob/CMSSW_20_1_0_pre5/Configuration/AlCa/python/autoCond.py)
is `200X_mcRun4_realistic_v1`, with tracker-specific overrides from
[autoCondPhase2](https://github.com/cms-sw/cmssw/blob/CMSSW_20_1_0_pre5/Configuration/AlCa/python/autoCondPhase2.py).
Use the complete `auto:phase2_realistic_T35` setting: the base tag alone omits
those overrides. The worker records the resolved tag and `toGet` entries.

These are campaign-based defaults. The worker saves `edmProvDump` and
`edmDumpEventContent` for the actual file. Confirm its geometry and available RAW,
tracker/HGCal digis and generator ancestry against those records. The dataset
name's 140X tag does not identify its exact producer patch release.

## Inclusive feature reconstruction

`cmssw/replay_cfg.py` invokes `cmsDriver.py --no_exec` with the YAML's conditions,
geometry, era and HLT menu. It replaces the generated schedule with
`cmssw.replay.sequence` and one output path. The sequence uses the release's
[unseeded photon producers](https://github.com/cms-sw/cmssw/blob/CMSSW_20_1_0_pre5/HLTrigger/Configuration/python/HLT_75e33/sequences/HLTPhoton108EBTightIDTightIsoUnseededSequence_cfi.py),
plus R9 and track isolation. It rejects EDFilter modules, and applies no L1
decision, ID filter, pixel match or `SelectEvents` skim. Zero-candidate events
remain in the denominator. Track isolation requires the
[HLT tracking sequence](https://github.com/cms-sw/cmssw/blob/CMSSW_20_1_0_pre5/HLTrigger/Configuration/python/HLT_75e33/sequences/HLTTrackingSequence_cfi.py).

The default [ECAL supercluster producer](https://github.com/cms-sw/cmssw/blob/CMSSW_20_1_0_pre5/HLTrigger/Configuration/python/HLT_75e33/modules/hltParticleFlowSuperClusterECALUnseeded_cfi.py)
has `thresh_SCEt = 10.0`. The YAML overrides this to 0.0 before the 5 GeV analysis
selection. Other clustering thresholds remain those of the release. This is an
inclusive ID study, not the acceptance or rate of the original photon path.

HGCal reconstruction is scheduled because the standard candidate producer
consumes barrel and endcap superclusters; analysis retains the configured barrel
acceptance. Old HLT products are dropped on input. New `HLTX` products and generator
collections are kept in the temporary replay file, which stays in job scratch.

## Feature definitions

All maps are keyed to `hltEgammaCandidatesUnseeded::HLTX`. The YAML specifies
module, instance and process explicitly.

| Branch | Module / instance in `HLTX` | Stored quantity |
| --- | --- | --- |
| `sigma_ieta_ieta` | `hltEgammaClusterShapeUnseeded:sigmaIEtaIEta5x5` | Square root of noZS 5x5 local eta covariance |
| `s_major` | `hltEgammaClusterShapeUnseeded:sMajor` | Seed-cluster second-moment major component |
| `s_minor` | `hltEgammaClusterShapeUnseeded:sMinor` | Seed-cluster second-moment minor component |
| `hoe` | `hltEgammaHoverEUnseeded` | Map's hadronic energy divided by candidate energy |
| `ecal_iso` | `hltEgammaEcalPFClusterIsoUnseeded` | Release-defined ECAL PF-cluster isolation, without rho correction |
| `hcal_iso` | `hltEgammaHcalPFClusterIsoUnseeded` | HCAL PF-cluster ET isolation, without rho correction |
| `r9` | `hltEgammaR9Unseeded` (empty instance) | Standard e3x3 / raw supercluster energy |
| `track_iso` | `hltEgammaHollowTrackIsoUnseeded` | Scalar track-pT isolation from `hltGeneralTracks` |

The [cluster-shape implementation](https://github.com/cms-sw/cmssw/blob/CMSSW_20_1_0_pre5/RecoEgamma/EgammaHLTProducers/plugins/EgammaHLTClusterShapeProducer.cc)
defines the shape instances. The [R9 implementation](https://github.com/cms-sw/cmssw/blob/CMSSW_20_1_0_pre5/RecoEgamma/EgammaHLTProducers/plugins/EgammaHLTR9IDProducer.cc)
also supplies `r95x5`, a different instance from the selected standard R9.
The [HCAL producer](https://github.com/cms-sw/cmssw/blob/CMSSW_20_1_0_pre5/RecoEgamma/EgammaHLTProducers/plugins/EgammaHLTHcalVarProducerFromRecHit.cc)
stores H, despite its label containing `HoverE`.
`ntuplizer.divide_by_candidate_energy: [hoe]` supplies the division explicitly.
Nonpositive or nonfinite normalization energy fails event processing.

The [ECAL isolation config](https://github.com/cms-sw/cmssw/blob/CMSSW_20_1_0_pre5/HLTrigger/Configuration/python/HLT_75e33/modules/hltEgammaEcalPFClusterIsoUnseeded_cfi.py),
[HCAL isolation config](https://github.com/cms-sw/cmssw/blob/CMSSW_20_1_0_pre5/HLTrigger/Configuration/python/HLT_75e33/modules/hltEgammaHcalPFClusterIsoUnseeded_cfi.py),
and [track isolation config](https://github.com/cms-sw/cmssw/blob/CMSSW_20_1_0_pre5/HLTrigger/Configuration/python/HLT_75e33/modules/hltEgammaHollowTrackIsoUnseeded_cfi.py)
provide the cones, thresholds and footprint rules. These definitions must stay
consistent between training and inference. Equivalence to every original slide
observable has not been established.

## Runtime and validation

The `prebuilt` runtime compiles once with `cmsrel`, `cmsenv` and `scram b`.
Workers activate that area with `scram runtime -sh` and return to scratch.
`prepare` snapshots the ntuplizer source/library checksums; changes invalidate
the farm and local-test receipts. Keep custom CMSSW dependencies unchanged too.

Inspect these artifacts after the README's local test:

- `input_provenance.txt`, `event_content.txt`: input history and products.
- `replay_base.py`, `replay_config.py`: generated and final configurations.
- `replay_metadata.json`: resolved GlobalTag, overrides and feature modules.
- `worker.log`, `ReplayJobReport.xml`, `FrameworkJobReport.xml`: processing evidence.
- `inspection.json`, `ntuple.root`: event/candidate counts and checked branches.

A clean local run checks the exercised file and events. Compare multiplicities,
feature distributions, matching and prompt/LLP efficiencies before interpreting
a release change. Require a Condor pilot with ROOT, provenance and receipt on EOS
before full production. This release has not yet been built or run on these
samples by this project.

## Other input profiles

Use a separate YAML and campaign for another release/menu. `cmssw.mode: existing`
consumes persisted candidates/maps without reconstruction. A newer reader alone
does not update their algorithms. Plain MiniAOD or NanoAOD cannot replace missing
HLT products or the RAW/digi inputs needed for this replay.

Custom `replay_pset` files must accept `inputFiles`, `outputFile` and `maxEvents`
through `VarParsing('analysis')`. The bundled pset also reads `resolved.json`.
Keep referenced products and generator ancestry; avoid trigger-dependent output
selection. Optional `cmssw.runtime: scratch` builds a separate area for each job.
