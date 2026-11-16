#include "../../runtime/views_internal.hpp"
#include <openssl/evp.h>
#include <cstring>
#include <stdexcept>

namespace graphmine::view_detail {
namespace {
// Length-delimited, type-tagged native records. Floating values retain their
// bits; the hash never interprets an ignored weight or property as an edge rule.
class Fingerprint {
  std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)> ctx{EVP_MD_CTX_new(), EVP_MD_CTX_free};
  void bytes(const void* data, std::size_t size) {
    if (EVP_DigestUpdate(ctx.get(), data, size) != 1) throw std::runtime_error("Graph fingerprint failed");
  }
 public:
  Fingerprint() {
    if (!ctx || EVP_DigestInit_ex(ctx.get(), EVP_sha256(), nullptr) != 1)
      throw std::runtime_error("Graph fingerprint initialization failed");
  }
  void put(std::uint64_t value) {
    unsigned char raw[8];
    for (int i = 0; i < 8; ++i) raw[i] = (value >> (8*i)) & 255;
    bytes(raw, sizeof(raw));
  }
  void put(std::int64_t value) { put(static_cast<std::uint64_t>(value)); }
  void put(bool value) { put(std::uint64_t(value)); }
  void put(std::nullptr_t) {}
  void put(double value) { std::uint64_t bits; std::memcpy(&bits, &value, sizeof(bits)); put(bits); }
  void put(const std::string& value) { put(std::uint64_t(value.size())); bytes(value.data(), value.size()); }
  template<class... T> void put(const std::variant<T...>& value) {
    put(std::uint64_t(value.index()));
    std::visit([&](const auto& item) { put(item); }, value);
  }
  template<class T> void put(const std::optional<T>& value) { put(value.has_value()); if (value) put(*value); }
  template<class T> void put(const std::vector<T>& values) {
    put(std::uint64_t(values.size())); for (const auto& value : values) put(value);
  }
  void put(const Attributes& values) {
    put(std::uint64_t(values.size())); for (const auto& [key, value] : values) { put(key); put(value); }
  }
  void put(const PropertyValue& value) { put(value.value()); }
  void put(const ExternalId& value) { put(value.value()); }
  std::string finish() {
    unsigned char digest[EVP_MAX_MD_SIZE]; unsigned int size = 0;
    if (EVP_DigestFinal_ex(ctx.get(), digest, &size) != 1) throw std::runtime_error("Graph fingerprint failed");
    constexpr char hex[] = "0123456789abcdef";
    std::string result;
    for (unsigned int i = 0; i < size; ++i) { result += hex[digest[i] >> 4]; result += hex[digest[i] & 15]; }
    return result;
  }
};
}  // namespace
std::string graph_hash(const Graph& graph) {
  Fingerprint hash;
  const auto& input = graph.canonical(); const auto& g = input.graph;
  hash.put(std::string("graphmine-native-records-v2"));
  hash.put(g.id); hash.put(g.directed); hash.put(g.allows_self_loops); hash.put(g.allows_parallel_edges);
  hash.put(g.attributes_present); hash.put(g.attributes);
  hash.put(std::uint64_t(input.vertices.size()));
  for (const auto& v : input.vertices) {
    hash.put(v.id); hash.put(v.label); hash.put(v.type); hash.put(v.attributes_present); hash.put(v.attributes);
  }
  hash.put(std::uint64_t(input.edges.size()));
  for (const auto& e : input.edges) {
    hash.put(e.id); hash.put(e.source); hash.put(e.target); hash.put(e.weight); hash.put(e.original_weight);
    hash.put(e.timestamp); hash.put(e.type); hash.put(e.attributes_present); hash.put(e.attributes);
  }
  return hash.finish();
}
}  // namespace graphmine::view_detail
