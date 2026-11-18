#ifndef Displaced_EGM_HLT_Ntuplizer_PhotonMatching_h
#define Displaced_EGM_HLT_Ntuplizer_PhotonMatching_h

#include <algorithm>
#include <cmath>
#include <tuple>
#include <utility>
#include <vector>

namespace displacedegm {
struct Direction {
  double eta = 0., phi = 0.;
  bool valid = false;
};

inline Direction atBarrel(double x, double y, double z, double eta, double phi,
                          double radius, double halfLength) {
  if (std::hypot(x, y) >= radius || std::abs(z) >= halfLength) return {};
  const double ux = std::cos(phi), uy = std::sin(phi), dot = x * ux + y * uy;
  const double distance = -dot + std::sqrt(dot * dot + radius * radius - x * x - y * y);
  const double hitZ = z + distance * std::sinh(eta);
  if (std::abs(hitZ) >= halfLength) return {};
  return {std::asinh(hitZ / radius), std::atan2(y + distance * uy, x + distance * ux), true};
}

// Greedy nearest-dR matching, with each candidate and generator used at most once.
inline std::vector<std::pair<int, double>> matchUnique(const std::vector<Direction>& reco,
                                                      const std::vector<Direction>& gen,
                                                      double maxDR) {
  std::vector<std::tuple<double, unsigned, unsigned>> pairs;
  for (unsigned ci = 0; ci < reco.size(); ++ci) {
    for (unsigned gi = 0; gi < gen.size(); ++gi) {
      if (!reco[ci].valid || !gen[gi].valid) continue;
      const double dr = std::hypot(reco[ci].eta - gen[gi].eta,
                                   std::remainder(reco[ci].phi - gen[gi].phi, 2. * std::acos(-1.)));
      if (dr < maxDR) pairs.emplace_back(dr, ci, gi);
    }
  }
  std::sort(pairs.begin(), pairs.end());
  std::vector<std::pair<int, double>> result(reco.size(), {-1, -1.});
  std::vector<bool> used(gen.size(), false);
  for (const auto& [dr, ci, gi] : pairs) {
    if (result[ci].first < 0 && !used[gi]) {
      result[ci] = {static_cast<int>(gi), dr};
      used[gi] = true;
    }
  }
  return result;
}
}  // namespace displacedegm
#endif
