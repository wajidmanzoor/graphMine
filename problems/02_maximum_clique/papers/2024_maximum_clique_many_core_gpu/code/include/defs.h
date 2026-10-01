#pragma once

using uint64 = unsigned long long int;
using uint = unsigned int;
using PeelType = int;
using BCTYPE = bool;
template <typename NodeTy>
using EdgeTy = std::pair<NodeTy, NodeTy>;

using DataType = uint;

enum MAINTASK
{
  MAINTASK_UNKNOWN,
  CONVERT,
  MCP,
  MCP_EVAL
};

enum COLORALG
{
  COLORALG_UNKNOWN,
  PSANSE,
  NUMBER,
  RECOLOR,
  RENUMBER,
  REDUCE
};

enum LogPriorityEnum
{
  critical,
  warn,
  error,
  info,
  debug,
  none
};

enum AllocationTypeEnum
{
  cpuonly,
  gpu,
  unified,
  zerocopy,
  noalloc
};