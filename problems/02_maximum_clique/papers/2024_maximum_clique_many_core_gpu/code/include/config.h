#pragma once
#include "defs.h"
#include <unistd.h>
#include <vector>
#include <cctype>
using namespace std;

struct Config
{
  string srcGraph;
  string dstGraph;
  MAINTASK mt;
  int deviceId;
  unsigned int block_size;
  bool warp_parallel;
  vector<int> gpus;
  unsigned int lb;
  bool verbose;
  COLORALG colorAlg;
};

static MAINTASK parseMainTask(const string &s)
{
  if (s == "convert")
    return MAINTASK::CONVERT;
  if (s == "mcp")
    return MAINTASK::MCP;
  if (s == "mcp-eval")
    return MAINTASK::MCP_EVAL;
  fprintf(stderr, "Unrecognized -m option (Main Task): %s\n", s.c_str());
  exit(0);
  return MAINTASK::MAINTASK_UNKNOWN;
}

static string asString(const MAINTASK &mt)
{
  if (mt == MAINTASK::CONVERT)
    return "convert";
  if (mt == MAINTASK::MCP)
    return "mcp";
  if (mt == MAINTASK::MCP_EVAL)
    return "mcp-eval";
  return "unknown";
}

static unsigned int parseUInt(const string &s)
{
  return (unsigned)atoi(s.c_str());
}

static std::vector<int> parseDevice(const string &s)
{
  std::vector<int> res;
  const int lim = s.size();
  for (int i = 0; i < lim; i++)
  {
    if (!isdigit(s[i]))
      continue;
    int cur = s[i] - '0', j = i;
    while (j + 1 < lim && isdigit(s[j + 1]))
      cur = cur * 10 + s[++j] - '0';
    res.emplace_back(cur);
    i = j + 1;
  }
  return res;
}

static string asString(const vector<int> &v)
{
  string res = "";
  for (int i = 0; i < v.size(); i++)
  {
    if (i != 0)
      res += ",";
    res += to_string(v[i]);
  }
  return res;
}


static COLORALG parseColorAlg(const string& s)
{
  if (s == "psanse")
    return COLORALG::PSANSE;
  if (s == "number")
    return COLORALG::NUMBER;
  if (s == "recolor")
    return COLORALG::RECOLOR;
  if (s == "renumber")
    return COLORALG::RENUMBER;
  if (s== "reduce")
    return COLORALG::REDUCE;

  return COLORALG::COLORALG_UNKNOWN;
}

static string asString(const COLORALG& c)
{
  if(c == COLORALG::PSANSE)
    return "San Segundo";
  if(c == COLORALG::NUMBER)
    return "NUMBER";
  if(c == COLORALG::RECOLOR)
    return "Re-Color";
  if(c == COLORALG::RENUMBER)
    return "Re-NUMBER";
  if(c == COLORALG::REDUCE)
    return "Reduce";

  return "Unrecognized coloring algorithm";
}

static void usage()
{
  fprintf(stderr,
          "\nUsage:  ./parallel_mcp_on_gpus [options]"
          "\n"
          "\nOptions:"
          "\n    -g <Src graph FileName>       Name of file with source graph"
          "\n    -r <Dst graph FileName>       Name of file with destination graph only for conversion"
          "\n    -d <Device Id(s)>             GPU Device Id(s) separated by commas without spaces"
          "\n    -m <Main Task>                Name of the task to perform"
          "\n                                     <convert: graph conversion>"
          "\n                                     <mcp>"
          "\n                                     <mcp-eval: clique evaluation only work with psanse coloring>"
          "\n    -c <Coloring Algorithm>       Specify the pruning strategy"
          "\n                                     <psanse: uses Pablo San Segundo's algorithm>"
          "\n                                     <number: uses NUMBER Tomita's Algorithm>"
          "\n                                     <recolor: Re-Color San Segundo's Algorithm>"
          "\n                                     <renumber: Re-NUMBER Tomita's Algorithm>"
          "\n                                     <reduce: Partial MC-BRB reduce technique>"
          "\n    -l <Lower Bound Max Clique>   Known lower bound of the dimension of the maximum clique, used just for task mcp"  
          "\n    -b <Block Size>               Block Size: <128, 256, 512, 1024>"
          "\n    -x <Warp-Parallel>            Execute the program warp parallel"
          "\n    -v <Verbose>                  Prints statistics"  
          "\n    -h                            Help"
          "\n"
          "\n");
}

static Config parseArgs(int argc, char **argv)
{
  Config config;
  config.srcGraph = "";
  config.dstGraph = "";
  config.mt = MAINTASK::MAINTASK_UNKNOWN;
  config.deviceId = 0;
  config.gpus = std::vector<int>();
  config.lb = 0;
  config.block_size = 64;
  config.colorAlg = COLORALG::COLORALG_UNKNOWN;
  config.verbose = false;
  config.warp_parallel = false;

  int opt;

  while ((opt = getopt(argc, argv, "g:r:d:m:c:l:b:xvh")) >= 0)
  {
    switch (opt)
    {
    case 'g':
      config.srcGraph = optarg;
      break;
    case 'r':
      config.dstGraph = optarg;
      break;
    case 'd':
      config.gpus = parseDevice(optarg), config.deviceId = config.gpus[0];
      break;
    case 'm':
      config.mt = parseMainTask(optarg);
      break;
    case 'l':
      config.lb = parseUInt(optarg);
      break;
    case 'c':
      config.colorAlg = parseColorAlg(optarg);
      break;
    case 'b':
      config.block_size = parseUInt(optarg);
      break;
    case 'v':
      config.verbose = true;
      break;
    case 'x':
      config.warp_parallel = true;
      break;
    case 'h':
      usage();
      exit(0);
      break;
    default:
      fprintf(stderr, "\nUnrecognized option!\n");
      usage();
      exit(0);
    }
  }

  if (config.mt == MAINTASK::MAINTASK_UNKNOWN)
  {
    fprintf(stderr, "Must specify -m option (Main Task)\n");
    usage();
    exit(0);
  }
  else if (config.mt == MAINTASK::CONVERT)
  {
    if (config.srcGraph == "")
    {
      fprintf(stderr, "Must specify -g option (Src graph FileName)\n");
      exit(0);
    }
    if (config.dstGraph == "")
    {
      fprintf(stderr, "Must specify -r option (Dst graph FileName)\n");
      exit(0);
    }
  }
  else
  {
    if (config.srcGraph == "")
    {
      fprintf(stderr, "Must specify -g option (Src graph FileName)\n");
      exit(0);
    }
    if (config.gpus.size() == 0)
    {
      fprintf(stderr, "Must specify -d option (Device Ids)\n");
      exit(0);
    }
    if (config.mt == MAINTASK::MCP && config.colorAlg == COLORALG::COLORALG_UNKNOWN)
    {
      fprintf(stderr, "Must specify -c option (Coloring Algorithm)\n");
      exit(0);
    }
  }

  return config;
}

static void printConfig(Config config)
{
  printf("    Main Task = %s\n", asString(config.mt).c_str());
  printf("    Source Graph = %s\n", config.srcGraph.c_str());
  if (config.mt == MAINTASK::CONVERT)
  {
    printf("    Destination Graph = %s\n", config.dstGraph.c_str());
  }
  else
  {
    printf("    Device ID(s) = %s\n", asString(config.gpus).c_str());
    if (config.mt == MAINTASK::MCP || config.mt == MAINTASK::MCP_EVAL)
    {
      printf("    Coloring Algorithm = %s\n", asString(config.colorAlg).c_str());
      printf("    Lower Bound Max Clique = %u\n", config.lb);
      printf("    Parallelism = %s\n", config.warp_parallel ? "Warps" : "Blocks");
    }
  }
  printf("-----------------------------\n");
}
