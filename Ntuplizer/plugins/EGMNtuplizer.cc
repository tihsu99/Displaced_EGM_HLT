#include <algorithm>
#include <cmath>
#include <map>
#include <set>
#include <string>
#include <vector>

#include "CommonTools/UtilAlgos/interface/TFileService.h"
#include "DataFormats/EgammaReco/interface/SuperCluster.h"
#include "DataFormats/HepMCCandidate/interface/GenParticle.h"
#include "DataFormats/HLTReco/interface/EgammaObject.h"
#include "DataFormats/HLTReco/interface/EgammaObjectFwd.h"
#include "Displaced_EGM_HLT/Ntuplizer/interface/PhotonMatching.h"
#include "FWCore/Framework/interface/Event.h"
#include "FWCore/Framework/interface/MakerMacros.h"
#include "FWCore/Framework/interface/one/EDAnalyzer.h"
#include "FWCore/ParameterSet/interface/ConfigurationDescriptions.h"
#include "FWCore/ParameterSet/interface/ParameterSet.h"
#include "FWCore/ParameterSet/interface/ParameterSetDescription.h"
#include "FWCore/ServiceRegistry/interface/Service.h"
#include "FWCore/Utilities/interface/Exception.h"
#include "FWCore/Utilities/interface/InputTag.h"
#include "SimDataFormats/GeneratorProducts/interface/GenEventInfoProduct.h"
#include "TTree.h"
#include "TNamed.h"

class EGMNtuplizer : public edm::one::EDAnalyzer<edm::one::SharedResources> {
public:
  static void fillDescriptions(edm::ConfigurationDescriptions& descriptions) {
    // Require explicit values so the production YAML remains the source of physics settings.
    edm::ParameterSetDescription desc;
    desc.add<edm::InputTag>("objects");
    desc.add<edm::InputTag>("genParticles");
    desc.add<edm::InputTag>("generator");
    desc.add<std::vector<int>>("pdgIds");
    desc.add<std::vector<int>>("llpPdgIds");
    desc.add<std::vector<double>>("invalidMapValues");
    desc.add<std::vector<std::string>>("divideByCandidateEnergy");
    desc.add<double>("ptMin");
    desc.add<double>("absEtaMax");
    desc.add<int>("matchingPdgId");
    desc.add<std::string>("matchingDirection");
    desc.add<double>("maxDR");
    desc.add<double>("ecalRadius");
    desc.add<double>("ecalHalfLength");
    desc.add<std::string>("metadata");
    edm::ParameterSetDescription map;
    map.add<std::string>("name");
    map.add<edm::InputTag>("src");
    desc.addVPSet("maps", map);
    descriptions.add("egmNtuplizer", desc);
  }

  explicit EGMNtuplizer(const edm::ParameterSet& cfg)
      : objects_(consumes<trigger::EgammaObjectCollection>(cfg.getParameter<edm::InputTag>("objects"))),
        particles_(consumes<reco::GenParticleCollection>(cfg.getParameter<edm::InputTag>("genParticles"))),
        generator_(consumes<GenEventInfoProduct>(cfg.getParameter<edm::InputTag>("generator"))),
        pdgIds_(cfg.getParameter<std::vector<int>>("pdgIds")),
        llpIds_(cfg.getParameter<std::vector<int>>("llpPdgIds")),
        invalidValues_(cfg.getParameter<std::vector<double>>("invalidMapValues")),
        divideByEnergy_(cfg.getParameter<std::vector<std::string>>("divideByCandidateEnergy")),
        ptMin_(cfg.getParameter<double>("ptMin")), absEtaMax_(cfg.getParameter<double>("absEtaMax")),
        matchingPdgId_(cfg.getParameter<int>("matchingPdgId")),
        matchingDirection_(cfg.getParameter<std::string>("matchingDirection")),
        maxDR_(cfg.getParameter<double>("maxDR")), radius_(cfg.getParameter<double>("ecalRadius")),
        halfLength_(cfg.getParameter<double>("ecalHalfLength")) {
    if (matchingDirection_ != "ecal_barrel" && matchingDirection_ != "momentum")
      throw cms::Exception("Configuration") << "Unknown matching direction";
    if (matchingDirection_ == "ecal_barrel" && matchingPdgId_ != 22)
      throw cms::Exception("Configuration") << "Straight ECAL propagation is only supported for photons";
    usesResource(TFileService::kSharedResource);
    edm::Service<TFileService> fs;
    fs->make<TNamed>("metadata", cfg.getParameter<std::string>("metadata").c_str());
    tree_ = fs->make<TTree>("Events", "HLTX EGM variables and generator matching");
    tree_->Branch("run", &run_, "run/i");
    tree_->Branch("lumi", &lumi_, "lumi/i");
    tree_->Branch("event", &event_, "event/l");
    tree_->Branch("gen_weight", &weight_, "gen_weight/D");
    for (const auto& name : {"pt", "eta", "phi", "sc_eta", "sc_phi", "match_dr", "gen_pt", "gen_eta", "gen_phi",
                             "gen_vx", "gen_vy", "gen_vz"}) {
      floats_[name] = {};
      tree_->Branch(name, &floats_.at(name));
    }
    for (const auto& name : {"gen_pdg_id", "gen_prompt", "gen_llp", "gen_fiducial", "matched_gen_index",
                             "match_pdg_id", "match_prompt", "match_llp", "match_gen_fiducial"}) {
      ints_[name] = {};
      tree_->Branch(name, &ints_.at(name));
    }
    for (const auto& entry : cfg.getParameter<std::vector<edm::ParameterSet>>("maps")) {
      auto name = entry.getParameter<std::string>("name");
      if (floats_.count(name) || ints_.count(name))
        throw cms::Exception("Configuration") << "Reserved branch name: " << name;
      const auto tag = entry.getParameter<edm::InputTag>("src");
      variables_[name] = tag.label() + (tag.instance().empty() ? "" : "_" + tag.instance());
      floats_[name] = {};
      tree_->Branch(name.c_str(), &floats_.at(name));
    }
    for (const auto& name : divideByEnergy_)
      if (!variables_.count(name)) throw cms::Exception("Configuration") << "Unknown normalized map: " << name;
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
    if (!std::isfinite(weight_)) throw cms::Exception("InvalidFeature") << "Nonfinite generator weight";
    const auto objects = event.getHandle(objects_);
    if (!objects.isValid()) throw cms::Exception("ProductNotFound") << "Missing configured EgammaObject collection";
    std::vector<displacedegm::Direction> recoDirections, genDirections;
    for (const auto& c : *objects) {
      const auto sc = c.superCluster();
      if (sc.isNull() || !sc.isAvailable())
        throw cms::Exception("ProductNotFound") << "SuperCluster references were dropped from the input";
      if (!std::isfinite(c.pt()) || !std::isfinite(c.eta()) || !std::isfinite(c.phi()) ||
          !std::isfinite(sc->eta()) || !std::isfinite(sc->phi()))
        throw cms::Exception("InvalidFeature") << "Nonfinite candidate kinematics";
      if (c.pt() <= ptMin_ || std::abs(sc->eta()) >= absEtaMax_) continue;
      floats_["pt"].push_back(c.pt());
      floats_["eta"].push_back(c.eta());
      floats_["phi"].push_back(c.phi());
      floats_["sc_eta"].push_back(sc->eta());
      floats_["sc_phi"].push_back(sc->phi());
      recoDirections.push_back(matchingDirection_ == "ecal_barrel"
                                   ? displacedegm::Direction{sc->eta(), sc->phi(), true}
                                   : displacedegm::Direction{c.eta(), c.phi(), true});
      for (const auto& entry : variables_) {
        if (!c.hasVar(entry.second))
          throw cms::Exception("InvalidFeature") << "Missing EgammaObject variable: " << entry.second;
        float value = c.var(entry.second);
        if (!std::isfinite(value) || std::find(invalidValues_.begin(), invalidValues_.end(), value) != invalidValues_.end())
          throw cms::Exception("InvalidFeature") << "Invalid EgammaObject variable: " << entry.second;
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
      if (!std::isfinite(g.pt()) || !std::isfinite(g.eta()) || !std::isfinite(g.phi()) ||
          !std::isfinite(g.vx()) || !std::isfinite(g.vy()) || !std::isfinite(g.vz()))
        throw cms::Exception("InvalidFeature") << "Nonfinite generator kinematics";
      floats_["gen_pt"].push_back(g.pt());
      floats_["gen_eta"].push_back(g.eta());
      floats_["gen_phi"].push_back(g.phi());
      floats_["gen_vx"].push_back(g.vx());
      floats_["gen_vy"].push_back(g.vy());
      floats_["gen_vz"].push_back(g.vz());
      ints_["gen_pdg_id"].push_back(g.pdgId());
      ints_["gen_prompt"].push_back(g.statusFlags().isPrompt());
      ints_["gen_llp"].push_back(hasLLPAncestor(g));
      auto direction = matchingDirection_ == "ecal_barrel"
                           ? displacedegm::atBarrel(g.vx(), g.vy(), g.vz(), g.eta(), g.phi(), radius_, halfLength_)
                           : displacedegm::Direction{g.eta(), g.phi(), true};
      direction.valid = direction.valid && std::abs(g.pdgId()) == matchingPdgId_;
      genDirections.push_back(direction);
      ints_["gen_fiducial"].push_back(direction.valid && g.pt() > ptMin_ && std::abs(direction.eta) < absEtaMax_);
    }
    for (const auto& [gi, dr] : displacedegm::matchUnique(recoDirections, genDirections, maxDR_)) {
      ints_["matched_gen_index"].push_back(gi);
      floats_["match_dr"].push_back(dr);
      for (const auto& name : {"pdg_id", "prompt", "llp"})
        ints_[std::string("match_") + name].push_back(gi < 0 ? 0 : ints_.at(std::string("gen_") + name).at(gi));
      ints_["match_gen_fiducial"].push_back(gi < 0 ? 0 : ints_.at("gen_fiducial").at(gi));
    }
    tree_->Fill();  // Events without candidates are part of the normalization denominator.
  }

  edm::EDGetTokenT<trigger::EgammaObjectCollection> objects_;
  edm::EDGetTokenT<reco::GenParticleCollection> particles_;
  edm::EDGetTokenT<GenEventInfoProduct> generator_;
  std::map<std::string, std::string> variables_;
  std::vector<int> pdgIds_, llpIds_;
  std::vector<double> invalidValues_;
  std::vector<std::string> divideByEnergy_;
  double ptMin_, absEtaMax_;
  int matchingPdgId_;
  std::string matchingDirection_;
  double maxDR_, radius_, halfLength_;
  std::map<std::string, std::vector<float>> floats_;
  std::map<std::string, std::vector<int>> ints_;
  TTree* tree_;
  unsigned int run_, lumi_;
  unsigned long long event_;
  double weight_;
};

DEFINE_FWK_MODULE(EGMNtuplizer);
