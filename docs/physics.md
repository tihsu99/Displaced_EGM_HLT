# Physics definitions and limits

## Study scope and source

The *Phase2 HLT: Displaced photon* slides (26 pages, PDF creation metadata
2025-04-22) study Phase2Spring24 PU200 samples. Pages 3-4 name GMSB and H -> gamma
gamma as signal and inclusive, EM-enriched and bcToE QCD as background. Both prompt
and displaced photons count as signal at trigger level. Page 6 sets the initial
acceptance to |etaSC| < 1.44 and pT > 5 GeV.

Page 3 proposes removing the photon-track DeltaR veto and PFHT requirement from
a Phase-1-inspired path. Its annotation explicitly mentions allowing prompt and
slightly displaced electrons. This is not proof that a particular Phase-2 menu
already implements those changes. The path also has a 60 GeV threshold; the
5 GeV object-study denominator is not the complete trigger denominator.

Pages 7-16 show pT, shower shape, Smajor, Sminor,
(Smajor-Sminor)/(Smajor+Sminor), H/E, ECAL isolation, HCAL isolation, R9 and track
isolation. The YAML exposes their source maps and bounds; the numerical feature
definitions/units must be checked against the actual producers. `sigma_ieta_ieta`
is the intended shower-shape mapping, not a verified identification of an unknown
product. Sentinels, squared widths, full5x5 versus other widths, and R9 versus
R9-like quantities must not be silently interchanged.

The default BDT omits pT as an input to reduce kinematic sculpting; pT remains in
the plots. Add `pt` to the feature YAML if an exact ten-input comparison is wanted.
The classifier implemented here is a BDT. The slides use a 64/32/16 DNN
architecture, so their classifier results are not directly reproduced.

Page 5 quotes background efficiency 0.0029. Visual inspection of page 20 shows
the cut point labeled (0.0029, 0.1091) and a DNN comparison point labeled
(0.0009, 0.1091); the latter is not a second cut measurement. Neither value is
embedded as a reproduced reference measurement. The exact isolation formulas and complete original cut configuration
are also absent. Current cut points are freshly tuned IDs, not a claimed
reproduction of that trigger path. A lower validation loss (page 23) alone does
not establish that overtraining is absent.

## LLP electrons need different treatment

1. Do not require `isPrompt` to identify LLP daughters. CMS's generator flag is
   an origin category, not a displacement threshold. An LLP daughter can have
   prompt-like status flags. Here an ancestor with a configured LLP PDG ID takes
   precedence over the prompt flag. All final-state e/g particles and their
   vertices are saved before downstream selection.
2. Do not inherit prompt dxy/dz limits, missing-inner-hit requirements, pixel-seed
   assumptions, conversion vetoes, track matching, or PV-based isolation without
   measuring their efficiency versus displacement. The ntuplizer applies none.
3. A calorimeter candidate can recover an electron when a standard GSF track or
   electron ID is inefficient. This first implementation reads calorimeter HLT
   EGM candidates; it is not a GSF-electron reconstruction implementation.
4. A charged electron bends in the magnetic field and radiates. The photon
   straight-line ECAL projection must not be used for it. Set `selection.pdg_id:
   11` and `matching.direction: momentum` only for an explicitly preliminary
   matching study; investigate charge/helix propagation, material, track matching
   and DeltaR closure before reporting displaced-electron efficiency.
5. Supply electron signal samples and their LLP ancestor IDs. The slide's HGG
   and neutralino-to-photon samples are not automatically electron signal samples.

The need to validate electron reconstruction independently is consistent with
the CMS discussion of low-pT displaced electrons and the different efficiencies
of low-pT and standard GED reconstruction:
[CMS EXO-24-036 overview](https://cms.cern/news/chasing-dark-matter-mysterious-electron-pairs/).

## Photon truth matching

The default final-state photon matching projects a ray from the generated
production vertex to a configured cylindrical barrel ECAL surface, then compares
the direction from the detector origin to that point with the reconstructed
SuperCluster eta/phi. This addresses the geometric bias of comparing a displaced
photon's original momentum direction directly with an origin-pointing cluster.

This is a barrel geometric approximation, not material propagation or a full
detector simulation. Radius and half-length are explicit study parameters and
must match the selected geometry. Decays outside this surface and rays exiting
the longitudinal boundary are outside the generator-fiducial denominator.
Electrons cannot select this mode. Matching is deterministic greedy nearest-dR
with one reconstructed candidate per generated particle; validate ambiguity and
DeltaR dependence in dense topologies. There is no relative-pT matching cut.

## What is measured

| Quantity | Numerator | Denominator |
| --- | --- | --- |
| Signal ID efficiency | Truth-matched reconstructed signal objects passing ID | Truth-matched reconstructed signal objects in the reco acceptance and gen fiducial volume |
| Background object efficiency | QCD candidates passing ID | QCD reconstructed candidates in the reco acceptance |
| Signal reconstruction-times-ID efficiency | Fiducial generated signal particles uniquely matched to a candidate passing ID | All truth-selected fiducial generated signal particles, including unmatched ones |
| Event acceptance | Events with at least one selected candidate passing ID | All processed events, including zero-candidate events |

Signal truth categories are kept separately by sample. Prompt means `isPrompt`
with no configured LLP ancestor. LLP means a configured ancestor, without an
additional displacement cut. Non-signal matched objects in a signal sample are
excluded rather than relabeled as signal. QCD candidates follow the slide's
sample-origin background definition, including any real photons in QCD.

`gen_lxy` is sqrt(vx^2+vy^2), `gen_abs_z` is |vz|, both in cm relative to the
detector origin. They are not track dxy/dz, displacement relative to a fitted PV,
or the LLP's proper lifetime. Generator acceptance plots versus pt/eta use gen
kinematics; reconstructed-ID plots use reco kinematics. Bin overflows are not
folded into the edge bins.

## Weights and physical rates

Signed generator weights are preserved. ID training and shape/efficiency plots
use the configured absolute or unit weights. Optional equal sample balance is
learned only on the training split and reused for validation/test. Precision,
accuracy and mixture ROC depend on that choice. These are not signed-weight
cross-section estimates. Per-sample plots expose unequal prompt/displaced and
background performance; combined working points do not guarantee every sample
reaches the target.

Inclusive QCD, EM-enriched QCD and bcToE QCD overlap. They must not simply be added
as independent physical backgrounds. A rate in Hz requires a validated disjoint
sampling/stitching prescription, generator bias/filter weights, cross sections
and sum of generator weights, target luminosity or a validated rate sample, L1
seeds, trigger thresholds, full path logic and prescales. No Hz result is produced.
Reported intervals use positive-weight effective-N Wilson approximations, not
exact weighted confidence coverage or negative-weight statistical inference.
