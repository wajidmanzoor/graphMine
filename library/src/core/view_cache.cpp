#include "../../runtime/views_internal.hpp"
#include "representation_store.hpp"
namespace graphmine::view_detail {
std::shared_ptr<const ViewResult> cached_view(const std::string& snapshot,
    const std::string& canonical, const ViewBuildOptions& options,
    const std::function<ViewResult()>& build) {
  // One process contains one implementation. This version also separates the
  // typed native snapshot key from other immutable representations in the pool.
  const auto key = snapshot + ":standard-view-v2:" + canonical;
  if (const auto found = representation_store::lookup(key)) {
    auto result = std::static_pointer_cast<const ViewResult>(found->value);
    if (options.charge_original_edges) options.charge_original_edges(result->original_edge_work);
    if (options.charge) options.charge(result->build_work);
    if (options.observe) options.observe(*result, true, true);
    return result;
  }
  auto result = std::make_shared<const ViewResult>(build());
  const auto bytes = result->accounted_bytes();
  const auto accounted = key.size() > (SIZE_MAX - bytes) / 2 ? SIZE_MAX : bytes + 2*key.size();
  std::shared_ptr<const void> winner;
  const bool retained = representation_store::insert(key, result, accounted, result->build_work, &winner);
  if (winner) result = std::static_pointer_cast<const ViewResult>(winner);
  if (options.observe) options.observe(*result, false, retained);
  return result;
}
}  // namespace graphmine::view_detail
