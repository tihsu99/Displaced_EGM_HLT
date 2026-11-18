#include <algorithm>
#include <cmath>
#include <map>
#include <set>
#include <string>
#include <vector>

#include "CommonTools/UtilAlgos/interface/TFileService.h"
#include "DataFormats/EgammaReco/interface/SuperCluster.h"
#include "DataFormats/HepMCCandidate/interface/GenParticle.h"
#include "DataFormats/RecoCandidate/interface/RecoEcalCandidate.h"
#include "DataFormats/RecoCandidate/interface/RecoEcalCandidateIsolation.h"
#include "FWCore/Framework/interface/Event.h"
#include "FWCore/Framework/interface/MakerMacros.h"
#include "FWCore/Framework/interface/one/EDAnalyzer.h"
#include "FWCore/ParameterSet/interface/ParameterSet.h"
#include "FWCore/ServiceRegistry/interface/Service.h"
#include "FWCore/Utilities/interface/Exception.h"
#include "SimDataFormats/GeneratorProducts/interface/GenEventInfoProduct.h"
#include "TTree.h"

class EGMNtuplizer : public edm::one::EDAnalyzer<edm::one::SharedResources> {
public:
  explicit EGMNtuplizer(const edm::ParameterSet& cfg)
      : candidates_(consumes<reco::RecoEcalCandidateCollection>(cfg.getParameter<edm::InputTag>("candidates"))),
        particles_(consumes<reco::GenParticleCollection>(cfg.getParameter<edm::InputTag>("genParticles"))),
        generator_(consumes<GenEventInfoProduct>(cfg.getParameter<edm::InputTag>("generator"))),
        pdgIds_(cfg.getParameter<std::vector<int>>("pdgIds")),
        llpIds_(cfg.getParameter<std::vector<int>>("llpPdgIds")),
        invalidValues_(cfg.getParameter<std::vector<double>>("invalidMapValues")),
        divideByEnergy_(cfg.getParameter<std::vector<std::string>>("divideByCandidateEnergy")) {
    usesResource(TFileService::kSharedResource);
    edm::Service<TFileService> fs;
    tree_ = fs->make<TTree>("Events", "Unfiltered EGM candidates and generator denominators");
    tree_->Branch("run", &run_, "run/i");
    tree_->Branch("lumi", &lumi_, "lumi/i");
    tree_->Branch("event", &event_, "event/l");
    tree_->Branch("gen_weight", &weight_, "gen_weight/D");
    for (const auto& name : {"pt", "eta", "phi", "sc_eta", "sc_phi", "gen_pt", "gen_eta", "gen_phi",
                             "gen_vx", "gen_vy", "gen_vz"}) {
      floats_[name] = {};
      tree_->Branch(name, &floats_.at(name));
    }
    for (const auto& name : {"gen_pdg_id", "gen_prompt", "gen_llp"}) {
      ints_[name] = {};
      tree_->Branch(name, &ints_.at(name));
    }
    for (const auto& entry : cfg.getParameter<std::vector<edm::ParameterSet>>("maps")) {
      auto name = entry.getParameter<std::string>("name");
      if (floats_.count(name) || ints_.count(name))
        throw cms::Exception("Configuration") << "Reserved branch name: " << name;
      maps_[name] = consumes<reco::RecoEcalCandidateIsolationMap>(entry.getParameter<edm::InputTag>("src"));
      floats_[name] = {};
      tree_->Branch(name.c_str(), &floats_.at(name));
    }
    for (const auto& name : divideByEnergy_)
      if (!maps_.count(name)) throw cms::Exception("Configuration") << "Unknown normalized map: " << name;
  }

private:
  bool hasLLPAncestor(const reco::Candidate& particle) const {
    std::vector<const reco::Candidate*> pending;
    std::set<const reco::Candidate*> seen;
    for (size_t i = 0; i < particle.numberOfMothers(); ++i) pending.push_back(particle.mother(i));
    while (!pending.empty()) {
      auto ancestor = pending.back();
      pending.pop_back();
      if (!ancestor || !seen.insert(ancestor).second) continue;
      if (std::find(llpIds_.begin(), llpIds_.end(), std::abs(ancestor->pdgId())) != llpIds_.end()) return true;
      for (size_t i = 0; i < ancestor->numberOfMothers(); ++i) pending.push_back(ancestor->mother(i));
    }
    return false;
  }

  void analyze(const edm::Event& event, const edm::EventSetup&) override {
    for (auto& entry : floats_) entry.second.clear();
    for (auto& entry : ints_) entry.second.clear();
    run_ = event.id().run();
    lumi_ = event.luminosityBlock();
    event_ = event.id().event();
    weight_ = event.get(generator_).weight();
    const auto candidates = event.getHandle(candidates_);
    if (!candidates.isValid()) throw cms::Exception("ProductNotFound") << "Missing EGM candidate collection";
    std::map<std::string, edm::Handle<reco::RecoEcalCandidateIsolationMap>> maps;
    for (const auto& entry : maps_) {
      maps[entry.first] = event.getHandle(entry.second);
      if (!maps.at(entry.first).isValid())
        throw cms::Exception("ProductNotFound") << "Missing required feature: " << entry.first;
    }
    for (size_t i = 0; i < candidates->size(); ++i) {
      const auto& c = candidates->at(i);
      const auto sc = c.superCluster();
      if (sc.isNull() || !sc.isAvailable())
        throw cms::Exception("ProductNotFound") << "SuperCluster references were dropped from the input";
      floats_["pt"].push_back(c.pt());
      floats_["eta"].push_back(c.eta());
      floats_["phi"].push_back(c.phi());
      floats_["sc_eta"].push_back(sc->eta());
      floats_["sc_phi"].push_back(sc->phi());
      const reco::RecoEcalCandidateRef ref(candidates, i);
      for (const auto& entry : maps) {
        const auto found = entry.second->find(ref);
        if (found == entry.second->end() || !std::isfinite(found->val) ||
            std::find(invalidValues_.begin(), invalidValues_.end(), found->val) != invalidValues_.end())
          throw cms::Exception("InvalidFeature") << "Missing/nonfinite map entry: " << entry.first;
        float value = found->val;
        if (std::find(divideByEnergy_.begin(), divideByEnergy_.end(), entry.first) != divideByEnergy_.end()) {
          if (!std::isfinite(c.energy()) || c.energy() <= 0.)
            throw cms::Exception("InvalidFeature") << "Invalid candidate energy for: " << entry.first;
          value /= c.energy();
        }
        if (!std::isfinite(value)) throw cms::Exception("InvalidFeature") << "Nonfinite transformed feature: " << entry.first;
        floats_[entry.first].push_back(value);
      }
    }
    // Keep all final-state particles of interest, including those with no reconstructed match.
    for (const auto& g : event.get(particles_)) {
      if (g.status() != 1 || std::find(pdgIds_.begin(), pdgIds_.end(), std::abs(g.pdgId())) == pdgIds_.end()) continue;
      floats_["gen_pt"].push_back(g.pt());
      floats_["gen_eta"].push_back(g.eta());
      floats_["gen_phi"].push_back(g.phi());
      floats_["gen_vx"].push_back(g.vx());
      floats_["gen_vy"].push_back(g.vy());
      floats_["gen_vz"].push_back(g.vz());
      ints_["gen_pdg_id"].push_back(g.pdgId());
      ints_["gen_prompt"].push_back(g.statusFlags().isPrompt());
      ints_["gen_llp"].push_back(hasLLPAncestor(g));
    }
    tree_->Fill();  // Events without candidates are part of the normalization denominator.
  }

  edm::EDGetTokenT<reco::RecoEcalCandidateCollection> candidates_;
  edm::EDGetTokenT<reco::GenParticleCollection> particles_;
  edm::EDGetTokenT<GenEventInfoProduct> generator_;
  std::map<std::string, edm::EDGetTokenT<reco::RecoEcalCandidateIsolationMap>> maps_;
  std::vector<int> pdgIds_, llpIds_;
  std::vector<double> invalidValues_;
  std::vector<std::string> divideByEnergy_;
  std::map<std::string, std::vector<float>> floats_;
  std::map<std::string, std::vector<int>> ints_;
  TTree* tree_;
  unsigned int run_, lumi_;
  unsigned long long event_;
  double weight_;
};

DEFINE_FWK_MODULE(EGMNtuplizer);
