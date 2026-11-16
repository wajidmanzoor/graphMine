#pragma once
#include "graphmine/views.hpp"
#include <boost/json.hpp>
namespace graphmine::view_detail {
using Number = HypergraphView::SourceNumber;
struct Weight { double f64 = 0; std::int64_t integer = 0; };
void check(bool, const std::string&);
bool one_of(const std::string&, std::initializer_list<const char*>);
std::uint64_t add_count(std::uint64_t, std::uint64_t);
std::size_t cells(std::uint64_t, std::uint64_t, const ViewSpec&);
Number numeric(const boost::json::value&);
Weight cast_weight(const Number&, const ViewSpec&, NormalizationSummary&);
ViewWeights weight_column(const ViewSpec&);
void append_weight(ViewWeights&, const Weight&);
ViewResult build_graph(const Graph&, const ViewSpec&, const ViewBuildOptions&);
std::string graph_hash(const Graph&);
std::shared_ptr<const ViewResult> cached_view(const std::string&, const std::string&,
    const ViewBuildOptions&, const std::function<ViewResult()>&);
}  // namespace graphmine::view_detail
