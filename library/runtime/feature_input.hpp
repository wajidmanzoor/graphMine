#pragma once
#include "structured_input.hpp"

namespace graphmine::runtime {
inline FeatureInput feature_view_input(const json::value& input, const ViewProfile& profile, Work& work) {
  // Keep the existing structured common-front validation and allocation budget.
  // Backend identities and cells then come only from the declared dense view.
  FeatureInput result(input,work);
  const auto built = consume_view(input,profile,work);
  const auto& view = std::get<DenseView>(built->view);
  const auto& values = std::get<std::vector<double>>(view.values);
  result.ids = view.row_ids;
  result.indices.clear();
  for (VertexIndex v=0; v<result.ids.size(); ++v) result.indices.emplace(result.ids[v],v);
  for (std::size_t r=0; r<result.vectors.rows; ++r)
    for (std::size_t c=0; c<result.vectors.cols; ++c)
      result.vectors(r,c) = values[r*view.columns+c]; // Row-major to column-major layout only.
  return result;
}
}
