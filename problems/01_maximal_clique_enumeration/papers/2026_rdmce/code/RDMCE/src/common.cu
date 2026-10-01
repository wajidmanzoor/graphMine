#include "common.cuh"
HOST std::string ExtractName(const std::string &path)
{
  auto lastSlash = path.find_last_of("/\\");
  if (lastSlash != std::string::npos)
  {
    std::string filename = path.substr(lastSlash + 1);
    auto lastDot = filename.find_last_of('.');
    if (lastDot != std::string::npos)
      return filename.substr(0, lastDot);
    return filename;
  }

  auto lastDot = path.find_last_of('.');
  if (lastDot != std::string::npos)
    return path.substr(0, lastDot);
  return path;
}

HOST size_t SetIntersectionCount(const vlist_t &a, const vlist_t &b)
{
  size_t count = 0;
  size_t i = 0, j = 0;
  while (i < a.size() && j < b.size())
  {
    if (a[i] == b[j])
    {
      count++;
      i++;
      j++;
    }
    else if (a[i] < b[j])
    {
      i++;
    }
    else
    {
      j++;
    }
  }
  return count;
}

HOST size_t CountBit(uint64_t x)
{
  return __builtin_popcountll(x);
}