#pragma once
#include <cstdint>
#include <list>
#include <memory>
#include <optional>
#include <string>
namespace graphmine::representation_store {
struct Entry {
  std::shared_ptr<const void> value;
  std::size_t bytes;
  std::uint64_t work;
  std::list<std::string>::iterator position;
};
struct Stats {
  std::size_t limit, bytes, entries;
  std::uint64_t hits, misses, evictions;
};
std::optional<Entry> lookup(const std::string&);
bool insert(const std::string&, std::shared_ptr<const void>, std::size_t, std::uint64_t,
            std::shared_ptr<const void>* winner = nullptr);
Stats control(std::optional<std::size_t> limit = {}, bool clear = false);
}  // namespace graphmine::representation_store
