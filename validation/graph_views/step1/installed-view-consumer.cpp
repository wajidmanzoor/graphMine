#include <graphmine/views.hpp>
#include <iostream>
#include <stdexcept>
int main() {
  using graphmine::ExternalId;
  auto input = graphmine::Graph::from_edges("installed-views", {ExternalId(0), ExternalId("0"), ExternalId("isolated")}, {{ExternalId(0), ExternalId("0")}});
  auto spec = graphmine::ViewSpec::from_json(R"({"kind":"csr","weights":"none"})");
  auto result = graphmine::make_view(input, spec);
  const auto& csr = std::get<graphmine::CsrView>(result->view);
  if (csr.offsets != std::vector<std::uint64_t>{0,1,2,2} || csr.indices != std::vector<graphmine::VertexIndex>{1,0} || csr.vertices.external_ids[1] != ExternalId("0") || result->normalization.edges != 2)
    throw std::runtime_error("installed public view API failed");
  std::cout << result->normalization_json() << '\n';
}
