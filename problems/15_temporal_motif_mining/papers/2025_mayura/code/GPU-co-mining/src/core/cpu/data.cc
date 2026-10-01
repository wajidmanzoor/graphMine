#include "data.h"
#include <numeric>
#include <iostream>
#include <cstring>
#include <chrono>
#include <range/v3/all.hpp>
#include <dlfcn.h>
#include <random>
#include <thread>
#include <functional>
#include <fmt/ranges.h>

#include "Graph.h" // for now

const bool DEBUG_ENABLE = false;

namespace corelib {

constexpr const int NUMTHREADS = 64;

}

namespace corelib::util {
  void generateRandToFile(size_t N, std::filesystem::path pathToFile) {
    std::vector<int> rands(N);

    std::vector<size_t> beg(NUMTHREADS), end(NUMTHREADS);
    size_t chunk = N / NUMTHREADS;
    for (size_t i = 0; i < NUMTHREADS; i++) {
      beg[i] = i * chunk;
      end[i] = (i + 1) * chunk;
    }
    end[NUMTHREADS - 1] = N;

    std::vector<std::thread> ts;
    for (size_t i = 0; i < NUMTHREADS; i++) {
      ts.push_back(std::thread([&, i]{
        std::mt19937 gen;
        std::random_device rd;
        gen.seed(rd());
        std::uniform_int_distribution<> dist(0, 1000000000);
        for (size_t j = beg[i]; j < end[i]; j++) {
          rands[j] = dist(gen);
        }
      }));
    }

    std::for_each(ts.begin(), ts.end(), std::mem_fn(&std::thread::join));

    fmt::print("[generateRandToFile] finish generation\n");
    fmt::print("[generateRandToFile] first 5 numbers: {} {} {} {} {}\n", rands[0], rands[1], rands[2], rands[3], rands[4]);

    data::MappedFileSinkMemory sink(pathToFile, sizeof(int) * N);
    memcpy(sink.data(), rands.data(), sizeof(int) * N);
  }

  void memcpyPar(void *dst, const void *src, size_t count) {
    const size_t chunk = count / NUMTHREADS;

    std::vector<std::thread> ts;
    for (int tid = 0; tid < NUMTHREADS; tid++) {
      ts.push_back(std::thread([&, tid]{
        size_t start = chunk * tid, end = chunk * (tid + 1);
        if (tid == NUMTHREADS - 1) {
          end = count;
        }

        void *dstl = ((char *) dst) + start;
        const void *srcl = ((const char *) src) + start;
        size_t countl = end - start;
        memcpy(dstl, srcl, countl);
      }));
    }
    std::for_each(ts.begin(), ts.end(), std::mem_fn(&std::thread::join));
  }
}

namespace corelib {

bool operator==(const TemporalEdge &lhs, const TemporalEdge &rhs) {
  return (lhs.u == rhs.u) && (lhs.v == rhs.v) && (lhs.t == rhs.t);
}

std::ostream &operator<<(std::ostream &o, const MotifEdgeInfoV1 &obj) {
  o << fmt::format("bN: {}, cN: {}, mN: {}, arrR: {}, arrV: {}, io: {}, newNode: {}",
    obj.baseNode, obj.constraintNode, obj.mappedNodes, fmt::ptr(obj.arrR), fmt::ptr(obj.arrV), obj.io, obj.newNode   
  );
  return o;
}


}

namespace corelib::data {

template<int N = 9>
struct Record {
  // parse N integers from str
  Record(const char *str) {
    auto beg = str;
    for (int i = 0; i < N - 1; i++) {
      while (*beg == ' ') beg++;
      fs[i] = std::atoi(beg);
      while (*beg != ' ') beg++;
    }
    while (*beg != ' ') beg++;
    fs[N - 1] = std::atoi(beg);
  }
  
  Record() {}

  // 9 features
  int fs[N] = {0};
};

// scan every line in a mapped_file file
class LineScanner {
  boost::iostreams::mapped_file &file_;
  int t_;

public:
  LineScanner(boost::iostreams::mapped_file &file, int t)
    : file_(file), t_(t) {}

  template <typename Func>
  void scan(Func func, size_t beg, size_t end) {
    auto f = file_.const_data() + beg;
    auto l = f + (end - beg);
    uint64_t num_bytes = (l - f) / t_;

    std::vector<std::thread> ts;
    for (int tid = 0; tid < t_; tid++) {
      ts.push_back(std::thread([&, tid]{
        auto start = tid * num_bytes + f;
        auto end = start + num_bytes;

        if (tid == t_ - 1) {
          end = l;
        } else {
          end = static_cast<const char *>(memchr(end, '\n', l - end));
        }
        
        if (tid == 0) {
          start = f;
        } else {
          start = static_cast<const char *>(memchr(start, '\n', l - start));
          start++;
        }

        do {
          func(tid, start);
          start = static_cast<const char *>(memchr(start, '\n', l-start));
          if (start) start++;
        } while (start && start < end);
      }));
    }
    std::for_each(ts.begin(), ts.end(), std::mem_fn(&std::thread::join));
  } 
};

CacheDirectoryAccess::CacheDirectoryAccess(std::filesystem::path pathToGraph)
  : name_(pathToGraph.stem()), graphPath_(pathToGraph),
  cacheDir_(pathToGraph.parent_path() / pathToGraph.stem())
   {
  if (!std::filesystem::exists(cacheDir_)) {
    std::filesystem::create_directory(cacheDir_);
  }
}

bool EdgeListLoader::shouldInit() const {
  bool existU = std::filesystem::exists(cacheUPath());
  bool existV = std::filesystem::exists(cacheVPath());
  bool existT = std::filesystem::exists(cacheTPath());
  bool existIDS = std::filesystem::exists(cacheIDSPath());
  return !(existU && existV && existT && existIDS);
}

void EdgeListLoader::createEdgeListCache() {
  auto start = std::chrono::high_resolution_clock::now();
  auto end = start;
  time_t time;
  boost::iostreams::mapped_file mfile(graphPath_, boost::iostreams::mapped_file::readonly);
  const auto num_threads = (mfile.size() <= (1024 * 1024)) ? 1 : thread_; // Use 1 thread for small files.
  corelib::data::LineScanner lscan(mfile, num_threads);

  std::vector<int> count(num_threads); 
  std::vector<std::vector<int>> Us(num_threads), Vs(num_threads), Ts(num_threads);
  lscan.scan([&](int tid, const char *start) { 
    Record<3> r(start);
    auto &U = Us[tid];
    auto &V = Vs[tid];
    auto &T = Ts[tid];
    if (DEBUG_ENABLE) {
      std::stringstream ss;
      ss << "tid: " << tid << " " << r.fs[0] << " " << r.fs[1] << " " << r.fs[2] << '\n';
      std::cout << ss.str();
    }
    U.push_back(r.fs[0]);
    V.push_back(r.fs[1]);
    T.push_back(r.fs[2]);
    count[tid]++;
  }, 0, mfile.size());

  for (int i = 1; i < num_threads; i++) {
    count[i] += count[i - 1];
  }
  int total = count.back();

  end = std::chrono::high_resolution_clock::now();
  time = std::chrono::duration_cast<std::chrono::milliseconds, time_t>(end - start).count();
  start = end;

  size_t arrSize = total * sizeof(int);
  std::vector<int> UVec(total);
  std::vector<int> VVec(total);
  std::vector<int> TVec(total);
  std::vector<int> IDS(total); // edge real index

  std::thread populateIDS([&] {
    for (int i = 0; i < total; i++) {
      IDS[i] = i;
    }
  });

  std::vector<std::thread> ts;
  for (int i = 0; i < num_threads; i++) {
    ts.push_back(std::thread([&, i]{
      size_t offset = i ? count[i - 1] : 0;
      offset *= sizeof(int);
      auto Udst = ((char *) UVec.data()) + offset;
      auto Vdst = ((char *) VVec.data()) + offset;
      auto Tdst = ((char *) TVec.data()) + offset;

      auto Usrc = Us[i].data();
      auto Vsrc = Vs[i].data();
      auto Tsrc = Ts[i].data();

      auto bytes = Us[i].size() * sizeof(int);

      std::memcpy(Udst, Usrc, bytes);
      std::memcpy(Vdst, Vsrc, bytes);
      std::memcpy(Tdst, Tsrc, bytes);
    }));
  }

  std::for_each(ts.begin(), ts.end(), std::mem_fn(&std::thread::join));
  populateIDS.join();


  end = std::chrono::high_resolution_clock::now();
  time = std::chrono::duration_cast<std::chrono::milliseconds, time_t>(end - start).count();
  start = end;
  fmt::print("# [EdgeListLoader] Edge List Parsing (combining) for {}, takes {} ms for {} records\n", name_, time, total);

  auto zip_view = ranges::view::zip(UVec, VVec, TVec, IDS);
  ranges::stable_sort(zip_view, std::less<>{},
             [](const auto& t) { return std::get<2>(t);}); // Projection
  end = std::chrono::high_resolution_clock::now();
  time = std::chrono::duration_cast<std::chrono::milliseconds, time_t>(end - start).count();
  start = end;
  // ~17 sec for 64M records
  fmt::print("# [EdgeListLoader] Edge List Parsing (serial stable sort) for {}, takes {} ms for {} records\n", name_, time, total);
  
  MappedFileSinkMemory Ufile(cacheUPath(), arrSize);
  MappedFileSinkMemory Vfile(cacheVPath(), arrSize);
  MappedFileSinkMemory Tfile(cacheTPath(), arrSize);
  MappedFileSinkMemory IDSfile(cacheIDSPath(), arrSize);

  ts.clear();
  for (int i = 0; i < num_threads; i++) {
    ts.push_back(std::thread([&, i]{
      size_t offset = i ? count[i - 1] : 0;
      offset *= sizeof(int);
      auto Udst = (char *) Ufile.data() + offset;
      auto Vdst = (char *) Vfile.data() + offset;
      auto Tdst = (char *) Tfile.data() + offset;
      auto IDSdst = (char *) IDSfile.data() + offset;

      auto Usrc = (char *) UVec.data() + offset;
      auto Vsrc = (char *) VVec.data() + offset;
      auto Tsrc = (char *) TVec.data() + offset;
      auto IDSsrc = (char *) IDS.data() + offset;

      auto bytes = Us[i].size() * sizeof(int);

      std::memcpy(Udst, Usrc, bytes);
      std::memcpy(Vdst, Vsrc, bytes);
      std::memcpy(Tdst, Tsrc, bytes);
      std::memcpy(IDSdst, IDSsrc, bytes);
    }));
  }

  std::for_each(ts.begin(), ts.end(), std::mem_fn(&std::thread::join));

  end = std::chrono::high_resolution_clock::now();
  time = std::chrono::duration_cast<std::chrono::milliseconds, time_t>(end - start).count();
  start = end;
  fmt::print("# [EdgeListLoader] Edge List Parsing (dump to file) for {}, takes {} ms for {} records\n", name_, time, total);
}

void EdgeListLoader::loadEdgeListCache() {
  auto start = std::chrono::high_resolution_clock::now();
  auto end = start;
  U_.reset(new MappedFileSourceMemory(cacheUPath()));
  V_.reset(new MappedFileSourceMemory(cacheVPath()));
  T_.reset(new MappedFileSourceMemory(cacheTPath()));
  IDS_.reset(new MappedFileSourceMemory(cacheIDSPath()));
  end = std::chrono::high_resolution_clock::now();
  time_t time = std::chrono::duration_cast<std::chrono::milliseconds, time_t>(end - start).count();
  fmt::print("# [EdgeListLoader] Edge List Loading takes {} ms for {} records\n", time, edgeListLength());
  if (DEBUG_ENABLE) {
    const auto L = edgeListLength();
    auto* U_ptr = (int*) U_->data();
    auto* V_ptr = (int*) V_->data();
    auto* T_ptr = (int*) T_->data();
    auto* IDS_ptr = (int*) IDS_->data();
    std::stringstream ss;
    for (size_t i = 0; i < L; i++) {
      ss << "U: " << U_ptr[i] << " V: " << V_ptr[i] << " T: " << T_ptr[i] << " IDS: " << IDS_ptr[i] << '\n';
    }
    std::cout << ss.str() << std::endl;
  }
}

EdgeListLoader::EdgeListLoader(std::filesystem::path pathToGraph)
  : CacheDirectoryAccess(pathToGraph) { 
  if (shouldInit()) {
    // Create cache if it doesn't exist.
    createEdgeListCache();
  }
  loadEdgeListCache();
}

size_t EdgeListLoader::edgeListLength() const {
  return U_->size() / sizeof(int);
}

bool FeatureLoader::shouldInit() const {
  bool existFE = std::filesystem::exists(cacheFEPath());
  bool existFVV = std::filesystem::exists(cacheFVVPath());
  bool existFVM = std::filesystem::exists(cacheFVMPath());
  return !(existFE && existFVV && existFVM);
}

void FeatureLoader::loadFeatureCache() {
  edgeFeatures_.reset(new MappedFileSourceMemory(cacheFEPath()));
  verticesFeatures_.reset(new MappedFileSourceMemory(cacheFVVPath()));
  verticesMap_.reset(new MappedFileSourceMemory(cacheFVMPath()));
}

FeatureLoader::FeatureLoader(const EdgeListLoader *eloader, std::filesystem::path pathToRands)
  : CacheDirectoryAccess(eloader->graphPath_), pathToRands_(pathToRands), eloader_(eloader) {
  if (shouldInit()) {
    createFeatureCache();
  }
  loadFeatureCache();
}

size_t FeatureLoader::edgeFeaturesLength() const {
  return edgeFeatures_->size() / sizeof(int);
}

size_t FeatureLoader::verticesFeaturesLength() const {
  return verticesFeatures_->size() / sizeof(int);
}

std::vector<SubPartition> divideList(const data::EdgeListLoader &eloader, int delta, int num) {
  const int *time = (const int *) eloader.getTPtr()->data();
  size_t size = eloader.edgeListLength();
  std::vector<SubPartition> res(num * 2 - 1);
  auto chunk = size / num;
  for (int i = 0; i < num; i++) {
    res[i].beg = i * chunk;
    res[i].end = (i + 1) * chunk;
  }
  res[num - 1].end = size;
  res[num - 1].n = res[num - 1].end - res[num - 1].beg;

  for (int i = 0; i < num - 1; i++) {
    auto p = res[i].end;
    auto t = time[p];
    auto lo = t - delta, hi = t + delta;
    auto loId = std::distance(time, std::lower_bound(time, time + size, lo)) - 1; 
    auto hiId = std::distance(time, std::lower_bound(time, time + size, hi)) + 1;
    res[i + num].beg = loId;
    res[i + num].end = hiId;
    res[i + num].n = p - loId;
    res[i].n = loId - res[i].beg;
  }
  return res;
}

void removeMinor(HostGraphDataList &complete) {
  size_t n = (complete.size() + 1) / 2;
  complete.resize(n);
}

void includeMinor(HostGraphDataList &major, HostGraphDataList &minor) {
  std::move(minor.begin(), minor.end(), std::back_inserter(major));
  minor.clear();
}

HostGraphDataList
GraphDataLoader::createPartitionsData(const SubPartitionList &partitions) const {
  HostGraphDataList major = createPartitionsDataMajor(partitions);
  HostGraphDataList minor = createPartitionsDataMinor(partitions);
  includeMinor(major, minor);
  return major;
}

HostGraphDataList
GraphDataLoader::createPartitionsDataMajor(const SubPartitionList &partitions) const {
  std::vector<HostGraphData> res;
  size_t major = (partitions.size() + 1) / 2;
  for (size_t i = 0; i < major; i++) {
    auto &p = partitions[i];
    res.push_back(createGraphData(p.beg, p.end, true));
  }
  return res;
}

HostGraphDataList
GraphDataLoader::createPartitionsDataMinor(const SubPartitionList &partitions) const {
  std::vector<HostGraphData> res;
  size_t major = (partitions.size() + 1) / 2;
  for (size_t i = major; i < partitions.size(); i++) {
    auto &p = partitions[i];
    res.push_back(createGraphData(p.beg, p.end, false));
  }
  return res;
}

void HostMotifData::constructSingleMinfo(const std::filesystem::path &pathToMotif) {
  minfo.clear();
  edges.clear();

  auto M = TemporalGraph::ReadGraph(pathToMotif);
  auto me = M->edges();
  for (auto &e: me) {
    edges.push_back({e.u, e.v, e.t});
  }
  name = pathToMotif.stem();
  numEdges = M->num_edges();
  numVertices = M->num_nodes();

  int nodeMax = 1; // Num nodes till now.
  if (DEBUG_ENABLE) std::cout << "\nReporting Construction of minfo.";
  for (size_t i = 1; i < numEdges; i++) {
    if (DEBUG_ENABLE) {
      std::cout << "\ni: " << i
        << " Edge: " << edges[i].v << ":" << edges[i].u << "@" << edges[i].t;
    }
    auto &e = edges[i];
    MotifEdgeInfoV1 mi;
    if (e.u > nodeMax) {
      mi.baseNode = e.v; // Already matched node.
      mi.constraintNode = -e.u; // +ve existing matched node, -ve new unique node.
      mi.io = 0; // Which list to search: in or out or dynamic decision.
      mi.mappedNodes = nodeMax + 1; // How many nodes are mapped till now.
      mi.newNode = true; // Trying to find a new & unique node.
      nodeMax++;
    } else if (e.v > nodeMax) {
      mi.baseNode = e.u;
      mi.constraintNode = -e.v;
      mi.io = 1;
      mi.mappedNodes = nodeMax + 1;
      mi.newNode = true;
      nodeMax++;
    } else {
      mi.baseNode = e.v;
      mi.constraintNode = e.u;
      mi.io = -1; // Dynamic Decision. For Optimization.
      mi.mappedNodes = nodeMax + 1;
      mi.newNode = false;
    }
    // Default-scenario: single-mining.
    mi.motif_ID = 1;
    mi.numem = numEdges;
    if ((i+1) == numEdges) {
      // Last edge.
      mi.count_IDX = 1;
    }
    minfo.push_back(mi);
  }
}

HostMotifData::HostMotifData(const std::filesystem::path &pathToMotif) {
  // ** Temporally implement in this way
  
  // Get file name from path && chop off the extension.
  const auto file_name = pathToMotif.stem().string();
  const auto dir = pathToMotif.parent_path();
  std::cout << "File Name: " << file_name << std::endl;
  if (!(file_name[0] == 'M' && file_name[1] == 'G')) {
    constructSingleMinfo(pathToMotif);
    for (size_t iter = 0; iter < numEdges-1; iter++) {
      auto &mi = minfo[iter];
      std::cout << "\nmotif_ID: " << int(mi.motif_ID) << " parent_ID: " << int(mi.parent_ID)
        << " child_ID_beg: " << int(mi.child_ID_beg) << " child_ID_end: " << int(mi.child_ID_end)
        << " last_sib_ID: " << int(mi.last_sib_ID) << " count_IDX: " << int(mi.count_IDX)
        << " | "
        << " numem: " << int(mi.numem)
        << " baseNode: " << int(mi.baseNode) << " constraintNode: " << int(mi.constraintNode)
        << " mappedNodes: " << int(mi.mappedNodes) << " io: " << int(mi.io)
        << " newNode: " << int(mi.newNode);
    }
    std::cout << std::endl;
    return;
  }
  std::cout << "Taking new path: " << pathToMotif << std::endl;
  name = file_name;
  const auto final_numEdges = numEdges;
  const auto final_numVertices = numVertices;

  std::map<
    // name of motif
    std::string,
    std::pair<
                // File name, is_motif
      std::pair<std::string, bool>,
      // Children
      std::vector<std::string>
    >
  > MG_info;

  // Load-up for m1-m6
  MG_info["m1"] = {{"m1", true}, {}};
  MG_info["m2"] = {{"m2", true}, {}};
  MG_info["m3"] = {{"m3", true}, {}};
  MG_info["m4"] = {{"m4", true}, {}};
  MG_info["m5"] = {{"m5", true}, {}};
  MG_info["m6"] = {{"m6", true}, {}};

  // Load-up for M1-M14
  MG_info["M1"] = {{"M1", true}, {}};
  MG_info["M2"] = {{"M2", true}, {}};
  MG_info["M3"] = {{"M3", true}, {}};
  MG_info["M4"] = {{"M4", true}, {}};
  MG_info["M5"] = {{"M5", true}, {}};
  MG_info["M6"] = {{"M6", true}, {}};
  MG_info["M7"] = {{"M7", true}, {}};
  MG_info["M8"] = {{"M8", true}, {}};
  MG_info["M9"] = {{"M9", true}, {}};
  MG_info["M10"] = {{"M10", true}, {}};
  MG_info["M11"] = {{"M11", true}, {}};
  MG_info["M12"] = {{"M12", true}, {}};
  MG_info["M13"] = {{"M13", true}, {}};
  MG_info["M14"] = {{"M14", true}, {}};

  // 3 & 4 cycle
  MG_info["cyc3"] = {{"cyc3", true}, {}};
  MG_info["cyc4"] = {{"cyc4", true}, {}};

  // MG3 is a motif & motif group with children m1 and m3
  MG_info["MG3"] = {{"MG3", true}, {"m1", "m3"}};

  // MG2 is a motif group with children m4, m5 and MG3
  MG_info["MG2"] = {{"MG2", false}, {"m4", /*"m5",*/ "MG3"}};

  // MG1 is a motif group with children m6 and MG2
  MG_info["MG1"] = {{"MG1", false}, {"m6", "MG2"}};

  // MG_34cyc is a motif group with children 3cyc and 4cyc
  MG_info["MG34cyc"] = {{"MG34cyc", false}, {"cyc3", "cyc4"}};

  MG_info["MGDEPTH_2"] = {{"M3", true}, {"M13"}};
  MG_info["MGDEPTH_3"] = {{"M1", true}, {"MGDEPTH_2"}};

  MG_info["MG_FANOUT_2"] = {{"M1", true}, {"M3"}};
  MG_info["MG_FANOUT_3"] = {{"M1", true}, {"M3", "M4"}};
  MG_info["MG_FANOUT_4"] = {{"M1", true}, {"M3", "M4", "M9"}};

  MG_info["MG_CMPLX_1_1"] = {{"MG_CMPLX_1_1", false}, {"M7", "M2"}};
  MG_info["MG_CMPLX_1_2"] = {{"MG_CMPLX_1_2", false}, {"M6", "M8"}};

  MG_info["MG_CMPLX_2_1"] = {{"M3", true}, {"M13"}};
  MG_info["MG_CMPLX_2"] = {{"M1", false}, {"MG_CMPLX_2_1", "M4", "M9"}};

  MG_info["MG_CMPLX_3_1"] = {{"M14", true}, {"M10"}};
  MG_info["MG_CMPLX_3_2"] = {{"M1", true}, {"MG_CMPLX_2_1", "M4", "M5", "M9"}};
  MG_info["MG_CMPLX_3"] = {{"MG34cyc", false}, {"MG_CMPLX_3_1", "MG_CMPLX_3_2"}};

  std::cout << "Setup MG_info" << std::endl;

  size_t maxEdges = 0;
  uint8_t motif_ID = 1, count_IDX = 1;
  std::map<std::string, std::pair<
                          std::vector<MotifEdgeInfoV1>,
                          std::vector<TemporalEdge>
                          >
    > minfo_map;

  std::function<void(const std::string &, const uint8_t, const uint8_t, const uint8_t,
    const uint8_t)> constructMinfo;
  constructMinfo = [&](const std::string &my_name, const uint8_t my_motif_ID, const uint8_t my_parent_ID,
    const uint8_t my_last_sib_ID, const uint8_t sib_level) {
    // Load minfo
    auto it_MG_info = MG_info.find(my_name);
    if (it_MG_info == MG_info.end()) {
      std::cout << "Motif " << my_name << " not found" << std::endl;
      throw std::runtime_error("Motif " + my_name + " not found");
    }
    auto &info = it_MG_info->second;
    auto &file = info.first.first;
    auto my_motif_path = dir / (file + ".txt");
    constructSingleMinfo(my_motif_path);
    auto my_minfo = std::move(minfo);
    auto my_edges = std::move(edges);
    
    // Record minfo
    auto it = minfo_map.find(my_name);
    if (it != minfo_map.end()) {
      throw std::runtime_error("Motif " + my_name + " already exists");
    }
    maxEdges = std::max(maxEdges, my_edges.size());

    uint8_t my_count_IDX = 0;
    if (info.first.second) {
      my_count_IDX = count_IDX++;
    }

    // Calculate motif ID range for children
    auto& my_children = info.second;
    const uint8_t my_children_ID_beg = motif_ID,
      my_children_ID_end = motif_ID + (my_children.size() > 0 ? my_children.size() - 1 : 0);
    // Update to next available range.
    motif_ID += my_children.size();

    // Record metadata in minfo.
    for(auto&mi : my_minfo) {
      mi.motif_ID = my_motif_ID;
      mi.parent_ID = my_parent_ID;
      mi.count_IDX = my_count_IDX;
      mi.numem = my_edges.size();
      if (my_children.size() > 0) {
        mi.child_ID_beg = my_children_ID_beg;
        mi.child_ID_end = my_children_ID_end;
      }
    }
    if (sib_level > 0) {
      if (sib_level == 1) {
        std::cerr << "sib_level == 1, this might not work." << std::endl;
        exit(1);
      }
      my_minfo[sib_level-1].last_sib_ID = my_last_sib_ID;
      for (int mi_iter=0; mi_iter<my_minfo.size(); ++mi_iter) {
        auto &mi = my_minfo[mi_iter];
        if (mi_iter != (sib_level-1)) {
          mi.last_sib_ID = -(sib_level-1);
        }
      }
    }
    minfo_map[my_name] = {my_minfo,my_edges};
    
    // Populate children
    auto child_motif_ID = my_children_ID_beg;
    for (auto &child: info.second) {
      constructMinfo(child, child_motif_ID++, my_motif_ID, my_children_ID_end,
        my_edges.size());
    }
  };
  constructMinfo(name, motif_ID++, 0, 0, 0);
  std::cout << std::flush;

  // Construct minfo for Motif Group

  minfo.resize(minfo_map.size() * (maxEdges-1));
  edges.resize(minfo_map.size() * maxEdges);
  std::unordered_map<uint8_t, std::string> motif_ID_to_name;
  for (auto &[my_name, my_pair]: minfo_map) {
    auto& my_minfo = my_pair.first;
    auto& my_edges = my_pair.second;
    auto my_motif_ID = my_minfo[0].motif_ID;
    motif_ID_to_name[my_motif_ID] = my_name;
    for(size_t iter=0; iter<my_minfo.size(); iter++) {
      minfo[(my_motif_ID-1) * (maxEdges-1) + iter] = my_minfo[iter];
    }
    for(size_t iter=0; iter<my_edges.size(); iter++) {
      edges[(my_motif_ID-1) * (maxEdges+0) + iter] = my_edges[iter];
    }
  }
  std::cout << std::flush;

  name = file_name;
  numEdges = final_numEdges;
  numVertices = final_numVertices;

  if (DEBUG_ENABLE || true) {
    std::cout << "\nReporting Construction of minfo.";
    for (size_t motif_ID = 0; motif_ID < minfo_map.size(); motif_ID++) {
      std::cout << "\nMotif ID: " << motif_ID+1 << ", Name: " << motif_ID_to_name.at(motif_ID+1);
      for (size_t iter = 0; iter < (maxEdges-1); iter++) {
        auto &mi = minfo[motif_ID * (maxEdges-1) + iter];
        std::cout << "\nmotif_ID: " << int(mi.motif_ID) << " parent_ID: " << int(mi.parent_ID)
          << " child_ID_beg: " << int(mi.child_ID_beg) << " child_ID_end: " << int(mi.child_ID_end)
          << " last_sib_ID: " << int(mi.last_sib_ID) << " count_IDX: " << int(mi.count_IDX)
          << " | "
          << " numem: " << int(mi.numem)
          << " baseNode: " << int(mi.baseNode) << " constraintNode: " << int(mi.constraintNode)
          << " mappedNodes: " << int(mi.mappedNodes) << " io: " << int(mi.io)
          << " newNode: " << int(mi.newNode);
      }
    }
    std::cout << std::endl;
  }
}


MineJob::MineJob(const DeviceJobData *_data, int _delta, int _beg, int _end) 
  : device(_data->device), beg(_beg), end(_end), delta(_delta), data(_data) {
  if (end == -1) {
    end = _data->graphNumEdges - _data->motifNumEdges + 1; 
  }
}

std::tuple<int, int> MineJob::getWork() const {
  return {beg, end};
}

void MineJob::setWork(int _beg, int _end) {
  beg = _beg;
  end = _end;
}

std::ostream &operator<<(std::ostream &o, const HostGraphData &obj) {
  o << fmt::format("name: {}\n", obj.name);
  o << fmt::format("beg: {}, end: {}\n", obj.beg, obj.end);
  o << fmt::format("numEdges: {}, numVertices: {}, totalBytes: {}", obj.numEdges, obj.numVertices, obj.totalBytes);
  return o;
}

std::ostream &operator<<(std::ostream &o, const DeviceGraphData &obj) {
  o << fmt::format("device: {}, name: {}\n", obj.device, obj.name);
  o << fmt::format("beg: {}, end: {}\n", obj.beg, obj.end);
  o << fmt::format("numEdges: {}, numVertices: {}, totalBytes: {}\n", obj.numEdges, obj.numVertices, obj.totalBytes);
  o << fmt::format("Eg_d: {}, inEdgesV_d: {}, outEdgesV_d: {}\n", 
    fmt::ptr(obj.Eg_d.get()), fmt::ptr(obj.inEdgesV_d.get()), fmt::ptr(obj.outEdgesV_d.get()));
  o << fmt::format("inEdgesR_d: {}, outEdgesR_d: {}\n", 
    fmt::ptr(obj.inEdgesR_d.get()), fmt::ptr(obj.outEdgesR_d.get()));
  o << fmt::format("edgeFeatures: {}, verticesFeatures: {}", 
    fmt::ptr(obj.edgeFeatures.get()), fmt::ptr(obj.verticesFeatures.get()));
  return o;
}

std::ostream &operator<<(std::ostream &o, const HostMotifData &obj) {
  o << fmt::format("name: {}, numEdges: {}, numVertices: {}\n", obj.name, obj.numEdges, obj.numVertices);
  o << fmt::format("Edges:\n");
  for (auto &e: obj.edges) {
    o << fmt::format("{} {} {}\n", e.u, e.v, e.t);
  }
  o << fmt::format("minfo:\n");
  std::string t;
  for (auto &mi: obj.minfo) {
    t += fmt::format("{}\n", mi);
  }
  t.pop_back();
  o << t;
  return o;
}

std::ostream &operator<<(std::ostream &o, const DeviceJobData &obj) {
  o << fmt::format("device: {}\n", obj.device);
  o << "[Graph]\n";
  o << fmt::format("numEdges: {}, numVertices: {}\n", obj.graphNumEdges, obj.graphNumVertices);
  o << fmt::format("Eg_d: {}, inEdgesV_d: {}, outEdgesV_d: {}\n", 
    fmt::ptr(obj.Eg_d), fmt::ptr(obj.inEdgesV_d), fmt::ptr(obj.outEdgesV_d));
  o << fmt::format("inEdgesR_d: {}, outEdgesR_d: {}\n", 
    fmt::ptr(obj.inEdgesR_d), fmt::ptr(obj.outEdgesR_d));
  o << fmt::format("edgeFeatures: {}, verticesFeatures: {}\n", 
    fmt::ptr(obj.edgefeatures_d), fmt::ptr(obj.nodefeatures_d));
  o << "[Motif]\n";
  o << fmt::format("numEdges: {}, numVertices: {}\n", obj.motifNumEdges, obj.motifNumVertices);
  std::string t;
  for (auto &mi: obj.minfol_) {
    t += fmt::format("{}\n", mi);
  }
  t.pop_back();
  o << t;
  return o;
}

}

namespace corelib {

GPUWorker::GPUWorker(std::string type, int gpu, int sizeBlock) : 
type_(type), gpu_(gpu), time_(0), sizeBlock_(sizeBlock) {}

GPUWorker::~GPUWorker() {}

unsigned long long GPUWorker::timed_run() {
  using namespace std::chrono;
  auto st = high_resolution_clock::now();
  auto res = run();
  auto ed = high_resolution_clock::now();
  auto stept = duration_cast<duration<unsigned long long, std::micro>>(ed - st).count();
  time_ += stept;
  return res;
}

void GPUWorker::take(data::MineJob &job) {
  job_ = &job;
}

unsigned long long GPUWorker::time() {
  return time_;
}

unsigned long long GPUWorker::count() {
  return count_;
}

void GPUWorker::clear_time() {
  time_ = 0;
}


int GPUWorker::numBlocks() {
  if (!job_) {
    return -1;
  } else {
    return (job_->end + sizeBlock_ - 1) / sizeBlock_;
  }
}

std::vector<int> GPUWorker::printEnum(int) { return {}; }

LibHandle::LibHandle(void *h, FactoryType f) : handle(h), getWorker(f) {};

LibHandle::LibHandle(const std::string &libpath) {
  handle = dlopen(libpath.c_str(), RTLD_LAZY);
  if (!handle) {
    std::cerr << "Load Lib Error: " << dlerror() << std::endl;
    exit(-1);
  }

  getWorker = (LibHandle::FactoryType) dlsym(handle, "getWorker");
  if (!getWorker) {
    dlclose(handle);
    std::cerr << "query func Error: " << dlerror() << std::endl;
    exit(-1);
  }
}

LibHandle::LibHandle(LibHandle &&rhs) {
  (*this) = std::move(rhs);
}

LibHandle &LibHandle::operator=(LibHandle &&rhs) {
  if (this != &rhs) {
    handle = rhs.handle;
    getWorker = rhs.getWorker;
    rhs.handle = nullptr;
    rhs.getWorker = nullptr;
  }
  return rhs;
}

std::string LibHandle::toString() const {
  std::stringstream s;
  s << "handle: " << (void *) (handle)
    << ", factory: " << (void *) (getWorker) ;
  return s.str();
}

LibHandle::~LibHandle() { dlclose(handle); }

void GPUWorkerLibManager::openLib(const std::string &libpath) {
  std::string name;
  std::size_t pos = libpath.find_last_of("/");
  if (pos != std::string::npos) {
      name = libpath.substr(pos + 4, libpath.length() - pos - 7); // Extract libpathrary name from path with directory information
  } else {
      name = libpath.substr(3, libpath.length() - 6); // Extract libpathrary name from path without directory information
  }

  if (table_.find(name) != table_.end()) {
    unloadLib(name);
  } 
  table_.emplace(name, libpath);
  std::cout << "#" << name << " is opened" << std::endl;
}

void GPUWorkerLibManager::unloadLib(const std::string &lib) {
  table_.erase(lib);
  std::cout << "#" << lib << " is unloaded" << std::endl;
}

std::string GPUWorkerLibManager::toString() const {
  std::stringstream s;
  for (auto &e: table_) {
    s << e.first << ": " << e.second.toString() << std::endl;
  }
  auto str = s.str();
  if (!table_.empty()) str.pop_back();
  return str;
}

SingleGPUExecution::SingleGPUExecution(const data::GraphDataManager *dataManager, int device)
  : device_(device), dataManager_(dataManager) {}


void SingleGPUExecution::formJobData() {
  if (hostGraph_ && hostMotif_) {
    jobData_ = data::DeviceJobData(deviceGraph_, *hostMotif_);
  }
}


void SingleGPUExecution::setHostGraph(const data::HostGraphData *hostGraph, int n) {
  n_ = n;
  hostGraph_ = hostGraph;
  std::vector<const data::HostGraphData *> targ = {hostGraph_};
  deviceGraph_ = dataManager_->alloc(device_, hostGraph_);
  // deviceGraph_ = std::move(dataManager_->allocBatch(1, targ).front());
  dataManager_->moveAsync(deviceGraph_, *hostGraph_, device_);
  dataManager_->waitMove(device_);
  formJobData();
}

void SingleGPUExecution::setHostMotif(const data::HostMotifData *hostMotif) {
  hostMotif_ = hostMotif;
  formJobData();
}

void SingleGPUExecution::setWorker(GPUWorker *w) {
  w_ = w;
}

unsigned long long SingleGPUExecution::run(int delta) {
  fmt::print("[SingleGPUExecution] delta: {}\n", delta);
  job_ = data::MineJob(&jobData_, delta, 0, n_);
  w_->take(job_);
  return w_->timed_run();
}

SingleGPUExecutionDiv::SingleGPUExecutionDiv(const data::GraphDataManager *dataManager, int device, int div)
  : SingleGPUExecution(dataManager, device), div_(div) {}

void SingleGPUExecutionDiv::formJobData() {
  if (hostGraph_ && hostMotif_) {
    jobData_ = data::DeviceJobData(deviceGraph_, *hostMotif_);

    int chunk = n_ / div_;
    for (int i = 0; i < div_; i++) {
      queue_.push_back(Task{i * chunk, (i + 1) * chunk});
    }
    queue_.back().end = n_;
  }
}

unsigned long long SingleGPUExecutionDiv::run(int delta) {
  fmt::print("[SingleGPUExecutionDiv] div: {}\n", queue_.size());
  unsigned long long res = 0;
  for (auto &t : queue_) {
    job_ = data::MineJob(&jobData_, delta, t.beg, t.end);
    w_->take(job_);
    res += w_->timed_run();
  }
  return res;
}

void SingleGPURunBatch(const data::GraphDataManager *dataManager, data::HostGraphDataList &hostGraphs, 
  const data::HostMotifData *hostMotif, GPUWorker *w, int delta) {
  for (auto &hostGraph: hostGraphs) {
    SingleGPUExecution exec(dataManager);
    exec.setHostGraph(&hostGraph);
    exec.setHostMotif(hostMotif);
    exec.setWorker(w);
    exec.run(delta);
  }
}

MultiGPUExecution::MultiGPUExecution(const data::GraphDataManager *dataManager, int deviceNum)
  : deviceNum_(deviceNum), dataManager_(dataManager) {}

void MultiGPUExecution::loadGraph(int start, int n) {
  for (int d = 0; d < n; d++) {
    int t = start + d;
    dataManager_->moveAsync(deviceGraphs_[d], *hostGraphs_[t], d);
    deviceNs_[d] = ns_[t];
  }
  for (int d = 0; d < n; d++) {
    dataManager_->waitMove(d);
  }
}

void MultiGPUExecution::formJobData() {
  if (!deviceGraphs_.empty() && hostMotif_) {
    jobsData_.resize(deviceNum_);
    for (int d = 0; d < deviceNum_; d++) {
      jobsData_[d] = data::DeviceJobData(deviceGraphs_[d], *hostMotif_);
    }
  }
}

void MultiGPUExecution::setHostGraphs(const data::HostGraphDataList &hostGraphs, 
  const data::SubPartitionList &ps) {
  hostGraphs_.clear();
  std::transform(hostGraphs.begin(), hostGraphs.end(), std::back_inserter(hostGraphs_),
    [] (const data::HostGraphData &hg) { return &hg; });
  ns_.clear();
  std::transform(ps.begin(), ps.end(), std::back_inserter(ns_), 
    [] (const data::SubPartition &p) { return p.n; });
  
  deviceGraphs_ = dataManager_->allocBatch(deviceNum_, hostGraphs_); // alloc & transfer the first deviceNum_ graph
  deviceNs_.resize(deviceNum_);
  loadGraph(0, deviceNum_);
  formJobData();
}

void MultiGPUExecution::setHostMotif(const data::HostMotifData *hostMotif) {
  hostMotif_ = hostMotif;
  formJobData();
}

void MultiGPUExecution::setWorkers(std::vector<GPUWorker *> &ws) {
  ws_ = ws;
}


int MultiGPUExecution::numDevice() const {
  return deviceNum_;
}

void MultiGPUExecution::lanuch(int n, int delta) {
  for (int d = 0; d < n; d++) {
    jobs_[d] = data::MineJob(&jobsData_[d], delta, 0, deviceNs_[d]);
  }

  std::vector<std::thread> ts;
  for (int d = 0; d < n; d++) {
    ts.push_back(std::thread([d, delta, this]{
      auto &w = ws_[d];
      auto &j = jobs_[d];
      w->take(j);
      w->timed_run();
    }));
  }
  std::for_each(ts.begin(), ts.end(), std::mem_fn(&std::thread::join));
}

MultiGPUExecutionNaive::MultiGPUExecutionNaive(const data::GraphDataManager *dataManager, int deviceNum)
  : MultiGPUExecution(dataManager, deviceNum) {}

void MultiGPUExecutionNaive::run(int delta) {
  jobs_.resize(deviceNum_);
  lanuch(deviceNum_, delta);
  loadGraph(deviceNum_, deviceNum_ - 1);
  formJobData();
  lanuch(deviceNum_ - 1, delta);
}

MultiGPUExecutionDyn::MultiGPUExecutionDyn(const data::GraphDataManager *dataManager, int deviceNum)
  : MultiGPUExecution(dataManager, deviceNum) {}

void MultiGPUExecutionDyn::formQueue() {
  if (!deviceGraphs_.empty() && hostMotif_) {
    taskQueues_.clear();
    for (int d = 0; d < deviceNum_; d++) {
      TaskQueue q(N);
      size_t chunk = deviceNs_[d] / N;
      for (int i = 0; i < N - 1; i++) {
        int beg = i * chunk;
        int end = (i + 1) * chunk;
        q[i] = Task{beg, end};
      }
      q[N - 1] = Task{(int) ((N - 1) * chunk), ns_[d]};
      taskQueues_.push_back(q);
    }
  }
  qMtxes_ = std::vector<std::mutex>(deviceNum_);
  atQueue_.reserve(deviceNum_);
  for (int d = 0; d < deviceNum_; d++) {
    atQueue_[d] = d;
  }
}

int MultiGPUExecutionDyn::whichLeft() {
  int which = -1;
  size_t maxSize = 0;
  for (int d = 0; d < deviceNum_; d++) {
    std::lock_guard<std::mutex> lg(qMtxes_[d]);
    if (taskQueues_[d].size() > maxSize) {
      which = d;
    }
  }
  return which;
}

auto MultiGPUExecutionDyn::getTask(int d) -> Task {
  int q = atQueue_[d];
  std::lock_guard<std::mutex> lg(qMtxes_[q]);
  if (taskQueues_[q].empty()) {
    return Task{-1, -1};
  } else {
    Task res = taskQueues_[q].back();
    taskQueues_[q].pop_back();
    return res;
  }
}

void MultiGPUExecutionDyn::threadFn(int d, int delta) {
  auto &w = ws_[d];
  while (true) {
    auto task = getTask(d);
    if (task.beg >= 0) {
      jobs_[d] = data::MineJob(&jobsData_[d], delta, task.beg, task.end);
      // fmt::print("# [Dyn exec] start task {}\n", d);
      w->take(jobs_[d]);
      // fmt::print("# [Dyn exec] start run {}\n", d);
      w->timed_run();
      // fmt::print("# [Dyn exec] finish run {}\n", d);
    } else {
      // fmt::print("# [Dyn exec] {} start switching\n", d);
      int which = this->whichLeft();
      if (which != -1) {
        // [NOTE] a bug if we use lanuchDyn twice
        fmt::print("# [Dyn exec] swtich {} -> {}\n", d, which);
        dataManager_->moveAsync(deviceGraphs_[d], *hostGraphs_[which], d);
        dataManager_->waitMove(d);
        jobsData_[d] = data::DeviceJobData(deviceGraphs_[d], *hostMotif_);
        atQueue_[d] = which;
        fmt::print("# [Dyn exec] swtich {} -> {} over\n", d, which);
      } else {
        fmt::print("# [Dyn exec] {} return\n", d);
        return;
      }
    }
  }
}

void MultiGPUExecutionDyn::launchDyn(int n, int delta) {
  formQueue();

  std::vector<std::thread> ts;
  for (int d = 0; d < n; d++) {
    ts.push_back(std::thread(
      std::bind(&MultiGPUExecutionDyn::threadFn, this, d, delta)
    ));
  }
  std::for_each(ts.begin(), ts.end(), std::mem_fn(&std::thread::join));
}

void MultiGPUExecutionDyn::run(int delta) {
  jobs_.resize(deviceNum_);
  launchDyn(deviceNum_, delta);
  loadGraph(deviceNum_, deviceNum_ - 1);
  formJobData();
  lanuch(deviceNum_ - 1, delta);
}

// [Reserved] should not be used

SingleGPUExecutionPause::SingleGPUExecutionPause(const data::GraphDataManager *dataManager, int device)
  : SingleGPUExecution(dataManager, device) {}

unsigned long long SingleGPUExecutionPause::run(int delta) {
  using namespace std::literals::chrono_literals;
  std::pair<int, int> j = {0, n_};
  unsigned long long res = 0;
  do {
    fmt::print("[SingleGPUExecutionPause] {} {}\n", j.first, j.second);
    job_ = data::MineJob(&jobData_, delta, j.first, j.second);
    std::thread t([&] { 
      w_->take(job_);
      res += w_->timed_run();
    });
    std::this_thread::sleep_for(500ms);
    j = w_->pause();
    t.join();
  } while (j.first < j.second); 
  
  return res;
  
}


MultiGPUExecutionDynPause::MultiGPUExecutionDynPause(const data::GraphDataManager *dataManager, int deviceNum) 
  : MultiGPUExecutionDyn(dataManager, deviceNum) {}

void MultiGPUExecutionDynPause::preempt() {
  fmt::print("preempt called\n");
  std::lock_guard<std::mutex> lg(pmtx_);
  for (int d = 0; d < deviceNum_; d++) {
    fmt::print("preempt {}\n", d);
    if (!done_[d]) {
      fmt::print("preempt {} called\n", d);
      auto r = ws_[d]->pause();
      fmt::print("preempt {} {}\n", r.first, r.second);
    }
  }
}

void MultiGPUExecutionDynPause::threadFnSignal(int d, int delta) {
  auto &w = ws_[d];
  while (true) {
    auto task = getTask(d);
    if (task.beg >= 0) {
      jobs_[d] = data::MineJob(&jobsData_[d], delta, task.beg, task.end);
      w->take(jobs_[d]);
      w->timed_run();
    } else {
      int which = this->whichLeft();
      if (which != -1) {
        fmt::print("# [Dyn exec] swtich {} -> {}\n", d, which);
        dataManager_->moveAsync(deviceGraphs_[d], *hostGraphs_[which], d);
        dataManager_->waitMove(d);
        jobsData_[d] = data::DeviceJobData(deviceGraphs_[d], *hostMotif_);
        atQueue_[d] = which;
        fmt::print("# [Dyn exec] swtich {} -> {} over\n", d, which);
      } else {
        fmt::print("# [Dyn exec] {} return\n", d);
        { // signal and exit
          std::lock_guard<std::mutex> lg(pmtx_);
          done_[d] = true;
        }
        pcv_.notify_all();
        return;
      }
    }
  }

}

void MultiGPUExecutionDynPause::launchDynPause(int n, int delta) {
  done_ = std::vector<bool>(deviceNum_, false);
  formQueue();
  std::vector<std::thread> ts;
  for (int d = 0; d < n; d++) {
    ts.push_back(std::thread(
      std::bind(&MultiGPUExecutionDynPause::threadFnSignal, this, d, delta)
    ));
  }

  {
    std::unique_lock uq(pmtx_);
    pcv_.wait(uq, [this]{
      for (auto b : done_) {
        if (b) return true;
      }
      return false;
    });
  }
  preempt();
  fmt::print("preempt finishes\n");

  std::for_each(ts.begin(), ts.end(), std::mem_fn(&std::thread::join));
}

void MultiGPUExecutionDynPause::run(int delta) {
  jobs_.resize(deviceNum_);
  launchDynPause(deviceNum_, delta);
  loadGraph(deviceNum_, deviceNum_ - 1);
  formJobData();
  lanuch(deviceNum_ - 1, delta);
}

unsigned long long allCount(std::vector<GPUWorker *> &ws) {
  unsigned long long res = 0;
  for (auto &w: ws) {
    res += w->count();
  }
  return res;
}

std::ostream &operator<<(std::ostream &o, const GPUWorker &w) {
  fmt::print(o, "type: {}, gpu: {}, job:{}\n", w.type_, w.gpu_, fmt::ptr(w.job_));
  return o;
}

std::ostream &operator<<(std::ostream &o, const LibHandle &obj) {
  o << obj.toString();
  return o;
}

std::ostream &operator<<(std::ostream &o, const GPUWorkerLibManager &obj) {
  o << obj.toString();
  return o;
}
}