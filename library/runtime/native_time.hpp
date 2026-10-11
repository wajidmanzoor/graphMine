#pragma once

#include "exact_number.hpp"

namespace graphmine::runtime {
// Integer epochs are seconds. RFC 3339 fractions and timezone offsets are
// converted exactly; timestamps beyond binary64's integer range stay ordered.
inline Exact timestamp_seconds(const std::optional<Timestamp>& time, Work& work) {
  require(time.has_value(), "Temporal sampling requires every edge timestamp");
  if (std::holds_alternative<std::int64_t>(*time)) return Exact(std::get<std::int64_t>(*time));
  const auto& text = std::get<std::string>(*time);
  work.tick(text.size());
  auto digits = [&](std::size_t at, std::size_t length) {
    require(at + length <= text.size(), "Invalid RFC 3339 timestamp");
    int value = 0;
    for (std::size_t i = at; i < at + length; ++i) {
      require(text[i] >= '0' && text[i] <= '9', "Invalid RFC 3339 timestamp");
      value = value * 10 + text[i] - '0';
    }
    return value;
  };
  require(text.size() >= 20 && text[4] == '-' && text[7] == '-' &&
              (text[10] == 'T' || text[10] == 't') && text[13] == ':' && text[16] == ':',
          "Use a timezone-aware RFC 3339 timestamp");
  const int year = digits(0, 4), month = digits(5, 2), day = digits(8, 2), hour = digits(11, 2),
            minute = digits(14, 2), second = digits(17, 2);
  const bool leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
  const int month_days[] = {0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
  require(year >= 1 && month >= 1 && month <= 12 && day >= 1 &&
              day <= month_days[month] + (month == 2 && leap) && hour < 24 && minute < 60 &&
              second < 60,
          "Invalid Gregorian date/time; leap-second timestamps are not supported");
  const auto days_before_year = [](std::int64_t y) {
    --y;
    return 365 * y + y / 4 - y / 100 + y / 400;
  };
  std::int64_t days = days_before_year(year) - days_before_year(1970) + day - 1;
  for (int m = 1; m < month; ++m) days += month_days[m] + (m == 2 && leap);
  Exact result = Exact(days * 86400 + hour * 3600 + minute * 60 + second);
  std::size_t at = 19;
  if (text[at] == '.') {
    ++at;
    const auto begin = at;
    Integer numerator = 0, denominator = 1;
    while (at < text.size() && text[at] >= '0' && text[at] <= '9') {
      work.tick();
      numerator = numerator * 10 + text[at++] - '0';
      denominator *= 10;
    }
    require(at > begin, "Timestamp fraction is empty");
    result += Exact(numerator) / denominator;
  }
  require(at < text.size(), "Timestamp timezone is missing");
  if (text[at] == 'Z' || text[at] == 'z') {
    require(at + 1 == text.size(), "Trailing timestamp data");
    return result;
  }
  require((text[at] == '+' || text[at] == '-') && at + 6 == text.size() && text[at + 3] == ':',
          "Invalid timestamp timezone offset");
  const auto hours = digits(at + 1, 2), minutes = digits(at + 4, 2);
  require(hours < 24 && minutes < 60, "Invalid timestamp timezone offset");
  const auto offset = hours * 3600 + minutes * 60;
  return result + (text[at] == '+' ? -offset : offset);
}
}  // namespace graphmine::runtime
