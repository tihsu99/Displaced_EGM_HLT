# Analysis view for lxplus EL9. Override EGM_LCG_SETUP before sourcing env.sh
# when another centrally installed view has been validated for your platform.
EGM_LCG_SETUP=${EGM_LCG_SETUP:-/cvmfs/sft.cern.ch/lcg/views/LCG_107/x86_64-el9-gcc14-opt/setup.sh}
