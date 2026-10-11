#pragma once

#include <algorithm>
#include <random>

#include "exact_number.hpp"

namespace graphmine::runtime {
// Integer rejection sampling keeps every positive rational mass reachable,
// including ratios that underflow a binary64 cumulative distribution.
struct NativeRandom {
  std::uint64_t seed;
  std::mt19937_64 engine;
  explicit NativeRandom(const json::object& args) : seed(resolve(args)), engine(seed) {}
  static std::uint64_t resolve(const json::object& args) {
    if (!args.contains("random_seed") || args.at("random_seed").is_null()) {
      std::random_device device;
      return (std::uint64_t(device()) << 32) ^ device();
    }
    const auto& value = args.at("random_seed");
    require(value.is_int64() || value.is_uint64(), "random_seed must be an integer or null");
    return value.is_int64() ? static_cast<std::uint64_t>(value.as_int64()) : value.as_uint64();
  }
  Integer below(const Integer& bound, Work& work) {
    require(bound > 0, "A random integer requires a positive bound");
    if (bound == 1) {
      work.tick();
      return 0;
    }
    const auto bits = boost::multiprecision::msb(Integer(bound - 1)) + 1;
    while (true) {
      Integer value = 0;
      for (std::size_t offset = 0; offset < bits; offset += 64) {
        work.tick();
        auto word = engine();
        const auto count = std::min<std::size_t>(64, bits - offset);
        if (count < 64) word &= (UINT64_C(1) << count) - 1;
        value |= Integer(word) << offset;
      }
      if (value < bound) return value;
    }
  }
  std::size_t uniform(std::size_t bound, Work& work) {
    return below(Integer(bound), work).convert_to<std::size_t>();
  }
  template <class T>
  void shuffle(std::vector<T>& values, Work& work) {
    for (std::size_t n = values.size(); n > 1; --n)
      std::swap(values[n - 1], values[uniform(n, work)]);
  }
  std::optional<std::size_t> weighted(const std::vector<Exact>& weights, Work& work) {
    Integer common = 1;
    for (const auto& weight : weights) {
      work.tick();
      require(weight >= 0, "Sampling weights must be nonnegative");
      Integer a = common, b = denominator(weight);
      while (b != 0) {
        work.tick();
        Integer rest = a % b;
        a = b;
        b = rest;
      }
      common = common / a * denominator(weight);
    }
    Integer total = 0;
    std::vector<Integer> cumulative;
    for (const auto& weight : weights) {
      work.tick();
      total += numerator(weight) * (common / denominator(weight));
      cumulative.push_back(total);
    }
    if (total == 0) return {};
    const auto draw = below(total, work);
    return std::upper_bound(cumulative.begin(), cumulative.end(), draw) - cumulative.begin();
  }
};
}  // namespace graphmine::runtime
