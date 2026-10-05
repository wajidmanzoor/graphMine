#include "graphmine/problems/validated_expansion.hpp"
#include "graphmine/problems/graph_motifs.hpp"
#include "graphmine/problems/repaired_algorithms.hpp"
#include "worker_process.hpp"

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <limits>
#include <map>
#include <numeric>
#include <queue>
#include <set>
#include <sstream>
#include <stdexcept>
#include <thread>
#include <fcntl.h>
#include <signal.h>
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>

extern char** environ;

namespace graphmine {
namespace {
using namespace detail::isolated;
namespace fs = std::filesystem;
using Clock = std::chrono::steady_clock;
using Arc = std::pair<std::uint32_t, std::uint32_t>;
constexpr std::int64_t capacity_limit = 1000000000;

Provenance provenance(const std::string& name) {
  if (name == "ecl-scc") return {"connected_components",name,"ECL-SCC 1.0","8e67732687d06f75cdd602f36e1fe54429ba4f99","isolated upstream CUDA worker; canonical component labels"};
  if (name == "ecl-maxflow") return {"max_flow_min_cut",name,"ECL-MaxFlow","2aa2b9f1054b7ace6e2dc78f405fc3e9cd719a70","isolated upstream CUDA worker; checked flow and residual cut"};
  if (name == "hungarian-cuda") return {"bipartite_matching_assignment",name,"HungarianCUDA","ef841797c7b5ad9b04527d2fafc7604229c8a941","isolated upstream CUDA worker; complete square minimum-cost assignment"};
  if (name == "gdlog") return {"transitive_closure_reachability",name,"GDlog","65a6ee960ced8d04bc725ccdfa68f004f8479226","isolated upstream CUDA relational fixpoint; reflexive closure"};
  return {"butterfly_counting_bipartite","graphminer","GraphMiner/G2Miner","2a76e3f612e40e46a821d603ca11d10fcbc63ddd","validated GraphMiner square motif on a checked bipartite graph"};
}

void common_support(const Graph& graph, const IsolatedBackendOptions& options) {
  require(options.execution.device_ids.size()==1 && options.execution.device_ids[0]>=0,"exactly one nonnegative CUDA device id is supported");
  require(options.timeout_seconds>0 && options.timeout_seconds<=86400,"timeout_seconds must be in [1,86400]");
  require(graph.vertex_count()<=1000000 && graph.edge_count()<=10000000,"validated adapter limit: 1,000,000 vertices and 10,000,000 input edges");
  if (!GRAPHMINE_HAS_EXPANSION_WORKERS) throw BackendError(StatusCode::backend_unavailable,"CUDA expansion workers were not built");
}

std::vector<std::int64_t> marker(const std::string& output, const std::string& key) {
  std::istringstream stream(output);std::string line;
  while (std::getline(stream,line)) if (line==key || line.rfind(key+" ",0)==0) {
    std::istringstream row(line.substr(key.size()));std::int64_t value;std::vector<std::int64_t> result;
    while (row>>value) result.push_back(value);
    certify(row.eof(),"invalid worker result token");return result;
  }
  throw BackendError(StatusCode::correctness_mismatch,"missing worker result: "+key);
}

std::vector<Arc> arcs(const Graph& graph,bool weak=false) {
  std::set<Arc> values;
  for (const auto& edge:graph.canonical().edges) {
    auto u=graph.dense_index(edge.source),v=graph.dense_index(edge.target);
    if (u==v) continue;
    values.emplace(u,v);if (!graph.directed() || weak) values.emplace(v,u);
  }
  return {values.begin(),values.end()};
}

void write_ecl(const fs::path& path,std::size_t n,const std::vector<Arc>& edges,const std::vector<std::int64_t>& weights={}) {
  require(edges.size()<=static_cast<std::size_t>(std::numeric_limits<std::int32_t>::max()),"ECL CSR exceeds signed 32-bit indexing");
  std::vector<std::int32_t> data{static_cast<std::int32_t>(n),static_cast<std::int32_t>(edges.size())};
  std::size_t edge=0;
  for (std::size_t vertex=0;vertex<=n;++vertex) {
    while (edge<edges.size() && edges[edge].first<vertex) ++edge;
    data.push_back(static_cast<std::int32_t>(edge));
  }
  for (const auto& pair:edges) data.push_back(static_cast<std::int32_t>(pair.second));
  for (auto weight:weights) data.push_back(static_cast<std::int32_t>(weight));
  std::ofstream file(path,std::ios::binary);file.write(reinterpret_cast<const char*>(data.data()),data.size()*sizeof(std::int32_t));
  if (!file) throw BackendError(StatusCode::execution_failed,"cannot write worker input");
}

template<class Function> SupportReport support(Function fn) {
  try {fn();return {true,{}};} catch(const std::exception& e) {return {false,e.what()};}
}
template<class Output,class Function>
ExecutionResult<Output> execute(const std::string& backend,Function fn) {
  const auto start=Clock::now();auto origin=provenance(backend);
  try {
    Output value=fn();ExecutionStatistics statistics;
    statistics.end_to_end_ms=std::chrono::duration<double,std::milli>(Clock::now()-start).count();
    return ExecutionResult<Output>::success(std::move(value),std::move(origin),statistics);
  } catch(const BackendError& e) {return ExecutionResult<Output>::failure({e.code,e.what()},origin);}
  catch(const std::bad_alloc&) {return ExecutionResult<Output>::failure({StatusCode::resource_exhausted,"host allocation failed"},origin);}
  catch(const std::invalid_argument& e) {return ExecutionResult<Output>::failure({StatusCode::unsupported,e.what()},origin);}
  catch(const std::exception& e) {return ExecutionResult<Output>::failure({StatusCode::execution_failed,e.what()},origin);}
}

struct Network {
  std::vector<Arc> edges;
  std::vector<std::int64_t> capacities;
  std::map<Arc,std::size_t> indices;
  std::vector<std::int64_t> original_capacities;
};
Network network(const Graph& graph,const MaxFlowOptions& options) {
  common_support(graph,options);require(graph.directed(),"ECL-MaxFlow adapter requires a directed graph");
  require(options.source!=options.sink,"source and sink must differ");
  (void)graph.dense_index(options.source);(void)graph.dense_index(options.sink);
  Network result;std::map<Arc,std::int64_t> merged;std::int64_t total=0;
  for (const auto& edge:graph.canonical().edges) {
    require(options.unit_capacity || edge.weight.has_value(),"edge_weight capacity mode requires every edge weight");
    double weight=options.unit_capacity?1:*edge.weight;
    require(std::isfinite(weight) && weight>=0 && weight<=capacity_limit && std::floor(weight)==weight,"ECL-MaxFlow supports nonnegative integer capacities only");
    auto capacity=static_cast<std::int64_t>(weight);result.original_capacities.push_back(capacity);
    const auto u=graph.dense_index(edge.source),v=graph.dense_index(edge.target);
    if (u==v) continue;
    total+=capacity;require(total<=capacity_limit,"sum of non-loop capacities must be <= 1,000,000,000 to prevent upstream int overflow");
    merged[{u,v}]+=capacity;
  }
  for (const auto& entry:merged) {result.indices[entry.first]=result.edges.size();result.edges.push_back(entry.first);result.capacities.push_back(entry.second);}
  return result;
}

struct Assignment {
  std::vector<VertexIndex> left,right;
  std::vector<std::vector<std::size_t>> edges;
  std::vector<std::vector<int>> costs;
};
Assignment assignment(const Graph& graph,const LinearAssignmentOptions& options) {
  common_support(graph,options);require(!graph.directed(),"linear assignment requires an undirected bipartite graph");
  Assignment data;std::vector<int> side(graph.vertex_count(),-1);
  for (VertexIndex v=0;v<graph.vertex_count();++v) {
    const auto& attributes=graph.canonical().vertices[v].attributes;auto it=attributes.find("side");
    require(it!=attributes.end() && std::holds_alternative<std::string>(it->second.value()),"every vertex requires attributes.side = left or right");
    auto label=std::get<std::string>(it->second.value());require(label=="left" || label=="right","side must be left or right");
    side[v]=label=="left"?0:1;(side[v]==0?data.left:data.right).push_back(v);
  }
  require(data.left.size()==data.right.size() && data.left.size()<=64,"validated assignment requires equal sides with at most 64 vertices each");
  auto order=[&](auto a,auto b){return graph.external_id(a)<graph.external_id(b);};
  std::sort(data.left.begin(),data.left.end(),order);std::sort(data.right.begin(),data.right.end(),order);
  std::vector<std::size_t> row(graph.vertex_count());
  for (std::size_t i=0;i<data.left.size();++i) {row[data.left[i]]=i;row[data.right[i]]=i;}
  const auto n=data.left.size();data.edges.assign(n,std::vector<std::size_t>(n,graph.edge_count()));data.costs.assign(n,std::vector<int>(n,1000));
  for (std::size_t index=0;index<graph.edge_count();++index) {
    const auto& edge=graph.canonical().edges[index];auto u=graph.dense_index(edge.source),v=graph.dense_index(edge.target);
    require(side[u]!=side[v],"assignment edge must cross declared sides");if (side[u]) std::swap(u,v);
    require(edge.weight && std::isfinite(*edge.weight) && *edge.weight>=0 && *edge.weight<=999 && std::floor(*edge.weight)==*edge.weight,"validated Hungarian costs must be integers in [0,999]");
    const auto r=row[u],c=row[v];if (*edge.weight<data.costs[r][c]) {data.costs[r][c]=static_cast<int>(*edge.weight);data.edges[r][c]=index;}
  }
  for (const auto& values:data.edges) for(auto edge:values) require(edge<graph.edge_count(),"validated assignment requires a complete bipartite graph");
  return data;
}

void bipartite(const Graph& graph) {
  require(!graph.directed(),"butterfly counting requires an undirected bipartite graph");
  std::vector<std::string> declared;
  for(const auto& vertex:graph.canonical().vertices) {
    auto it=vertex.attributes.find("side");
    require(it!=vertex.attributes.end() && std::holds_alternative<std::string>(it->second.value()),"every vertex requires attributes.side = left or right");
    auto side=std::get<std::string>(it->second.value());require(side=="left" || side=="right","side must be left or right");declared.push_back(side);
  }
  for(const auto& edge:graph.canonical().edges)
    require(declared[graph.dense_index(edge.source)]!=declared[graph.dense_index(edge.target)],"butterfly edges must cross declared sides");
  for(const auto& edge:graph.canonical().edges) require(edge.source!=edge.target,"bipartite input cannot have self-loops");
  const auto normalized=graph.simple_undirected();const auto& csr=normalized.csr;
  std::vector<int> side(graph.vertex_count(),-1);std::queue<VertexIndex> pending;
  for(VertexIndex start=0;start<graph.vertex_count();++start) if(side[start]<0) {
    side[start]=0;pending.push(start);
    while(!pending.empty()) {auto u=pending.front();pending.pop();for(auto i=csr.offsets[u];i<csr.offsets[u+1];++i) {
      auto v=csr.neighbors[i];if(side[v]<0){side[v]=1-side[u];pending.push(v);}else require(side[v]!=side[u],"graph is not bipartite");
    }}
  }
}
Graph square() {return Graph::from_edges("butterfly",{0,1,2,3},{{0,1},{1,2},{2,3},{3,0}});}
GraphMotifOptions motif_options(const ButterflyOptions& options) {
  GraphMotifOptions result;result.backend=GraphMotifBackend::graphminer;result.induced=true;result.execution=options.execution;return result;
}
BackendInfo info(const std::string& backend,std::vector<std::string> capabilities,bool compiled=GRAPHMINE_HAS_EXPANSION_WORKERS) {
  auto p=provenance(backend);return {p.backend,p.backend_version,p.problem,p.source_commit,compiled,true,std::move(capabilities)};
}
} // namespace

SupportReport ConnectedComponents::supports(const Graph& graph) const {
  return support([&]{common_support(graph,options_);require(options_.connectivity_mode==ConnectivityMode::weakly_connected || options_.connectivity_mode==ConnectivityMode::strongly_connected,"unknown connectivity mode");});
}
ExecutionResult<ConnectedComponentsOutput> ConnectedComponents::run(const Graph& graph) const {
  return execute<ConnectedComponentsOutput>("ecl-scc",[&]{
    common_support(graph,options_);require(options_.connectivity_mode==ConnectivityMode::weakly_connected || options_.connectivity_mode==ConnectivityMode::strongly_connected,"unknown connectivity mode");
    auto edges=arcs(graph,options_.connectivity_mode==ConnectivityMode::weakly_connected);
    std::vector<std::int64_t> labels(graph.vertex_count());std::iota(labels.begin(),labels.end(),0);
    if(!edges.empty()) {TempDirectory temp;auto path=temp.path/"graph.egr";write_ecl(path,graph.vertex_count(),edges);labels=marker(invoke_worker("ecl-scc",{path.string()},options_,temp),"GRAPHMINE_COMPONENTS");}
    certify(labels.size()==graph.vertex_count(),"wrong number of component labels");
    std::map<std::int64_t,std::vector<VertexIndex>> groups;
    for(VertexIndex v=0;v<labels.size();++v){certify(labels[v]>=0 && labels[v]<static_cast<std::int64_t>(labels.size()),"invalid component label");groups[labels[v]].push_back(v);}
    std::vector<std::vector<VertexIndex>> sorted;
    for(auto& entry:groups){auto& members=entry.second;std::sort(members.begin(),members.end(),[&](auto a,auto b){return graph.external_id(a)<graph.external_id(b);});sorted.push_back(std::move(members));}
    std::sort(sorted.begin(),sorted.end(),[&](const auto& a,const auto& b){return graph.external_id(a[0])<graph.external_id(b[0]);});
    ConnectedComponentsOutput result;result.component_count=sorted.size();
    for(std::size_t i=0;i<sorted.size();++i){result.component_sizes.push_back(sorted[i].size());for(auto v:sorted[i])result.component_assignment.push_back({graph.external_id(v),static_cast<std::uint32_t>(i)});}
    std::sort(result.component_assignment.begin(),result.component_assignment.end(),[](const auto& a,const auto& b){return a.vertex<b.vertex;});return result;
  });
}
std::vector<BackendInfo> ConnectedComponents::backends(){return {info("ecl-scc",{"exact weak/strong components; loops removed; parallel edges collapsed","at most 1M vertices/10M input edges; isolated CUDA worker"})};}

SupportReport MaxFlowMinCut::supports(const Graph& graph) const{return support([&]{network(graph,options_);});}
ExecutionResult<MaxFlowOutput> MaxFlowMinCut::run(const Graph& graph) const {
  return execute<MaxFlowOutput>("ecl-maxflow",[&]{
    auto net=network(graph,options_);auto s=graph.dense_index(options_.source),t=graph.dense_index(options_.sink);std::vector<std::int64_t> flows(net.edges.size(),0);
    // Upstream launches a zero-sized grid on edgeless input. The exact zero
    // solution avoids that launch and still goes through all certificate checks.
    if(!net.edges.empty() && std::any_of(net.capacities.begin(),net.capacities.end(),[](auto c){return c>0;})) {
      TempDirectory temp;auto path=temp.path/"graph.egr";write_ecl(path,graph.vertex_count(),net.edges,net.capacities);
      flows=marker(invoke_worker("ecl-maxflow",{path.string(),std::to_string(s),std::to_string(t),"1"},options_,temp),"GRAPHMINE_FLOW");
    }
    certify(flows.size()==net.edges.size(),"wrong flow vector length");std::vector<std::int64_t> balance(graph.vertex_count(),0);std::vector<std::vector<VertexIndex>> residual(graph.vertex_count());
    for(std::size_t i=0;i<flows.size();++i) {auto [u,v]=net.edges[i];auto f=flows[i];certify(f>=0 && f<=net.capacities[i],"flow violates capacity");balance[u]-=f;balance[v]+=f;if(f<net.capacities[i])residual[u].push_back(v);if(f>0)residual[v].push_back(u);}
    for(VertexIndex v=0;v<balance.size();++v)if(v!=s && v!=t)certify(balance[v]==0,"flow violates conservation");
    std::vector<bool> side(graph.vertex_count(),false);std::queue<VertexIndex> queue;side[s]=true;queue.push(s);
    while(!queue.empty()){auto u=queue.front();queue.pop();for(auto v:residual[u])if(!side[v]){side[v]=true;queue.push(v);}}
    certify(!side[t],"augmenting path remains in residual graph");MaxFlowOutput result;result.max_flow_value=balance[t];
    for(std::size_t i=0;i<net.edges.size();++i)if(side[net.edges[i].first] && !side[net.edges[i].second])result.min_cut_value+=net.capacities[i];
    certify(result.max_flow_value>=0 && result.max_flow_value==result.min_cut_value && balance[s]==-balance[t],"flow and cut certificates disagree");
    for(VertexIndex v=0;v<side.size();++v)if(side[v])result.source_side_vertices.push_back(graph.external_id(v));
    for(std::size_t i=0;i<graph.edge_count();++i){const auto& edge=graph.canonical().edges[i];auto u=graph.dense_index(edge.source),v=graph.dense_index(edge.target);std::int64_t f=0;
      if(u!=v){auto index=net.indices.at({u,v});f=std::min(flows[index],net.original_capacities[i]);flows[index]-=f;if(side[u]&&!side[v])result.min_cut_edges.push_back(edge.id);}
      result.flow_assignment.push_back({edge.id,f});
    }
    result.optimal=true;return result;
  });
}
std::vector<BackendInfo> MaxFlowMinCut::backends(){return {info("ecl-maxflow",{"directed edge capacities: nonnegative integers; unit_capacity supported","total capacity <= 1e9; no vertex capacities; exact flow/cut certificate","parallel capacities summed; original edge flows restored; bounded worker"})};}

SupportReport LinearAssignment::supports(const Graph& graph) const{return support([&]{assignment(graph,options_);});}
ExecutionResult<LinearAssignmentOutput> LinearAssignment::run(const Graph& graph) const {
  return execute<LinearAssignmentOutput>("hungarian-cuda",[&]{
    auto data=assignment(graph,options_);LinearAssignmentOutput result;const auto n=data.left.size();if(!n)return result;
    TempDirectory temp;auto path=temp.path/"matrix.txt";
    {std::ofstream file(path);file<<n<<'\n';for(const auto& row:data.costs){for(auto value:row)file<<value<<' ';file<<'\n';}if(!file)throw BackendError(StatusCode::execution_failed,"cannot write assignment matrix");}
    auto selected=marker(invoke_worker("hungarian-cuda",{path.string()},options_,temp),"GRAPHMINE_ASSIGNMENT");certify(selected.size()==n,"wrong assignment size");std::set<std::int64_t> used;
    for(std::size_t r=0;r<n;++r){auto c=selected[r];certify(c>=0 && c<static_cast<std::int64_t>(n) && used.insert(c).second,"assignment is not a permutation");result.matching_edges.push_back(graph.canonical().edges[data.edges[r][c]].id);result.objective_value+=data.costs[r][c];}
    result.matching_size=n;return result;
  });
}
std::vector<BackendInfo> LinearAssignment::backends(){return {info("hungarian-cuda",{"minimum-cost perfect assignment only; complete square graph; at most 64 per side","integer costs [0,999]; attributes.side = left|right; no general matching modes"})};}

SupportReport TransitiveClosure::supports(const Graph& graph) const{return support([&]{common_support(graph,options_);require(graph.directed(),"transitive closure requires directed input");require(graph.vertex_count()<=1024,"materialized GDlog closure is limited to 1024 vertices (at most 1,048,576 pairs)");});}
ExecutionResult<ReachabilityOutput> TransitiveClosure::run(const Graph& graph) const {
  return execute<ReachabilityOutput>("gdlog",[&]{
    common_support(graph,options_);require(graph.directed(),"transitive closure requires directed input");require(graph.vertex_count()<=1024,"materialized GDlog closure is limited to 1024 vertices (at most 1,048,576 pairs)");ReachabilityOutput result;if(!graph.vertex_count())return result;
    auto edges=arcs(graph);TempDirectory temp;auto path=temp.path/"edges.tsv";
    {std::ofstream file(path);for(auto [u,v]:edges)file<<u<<'\t'<<v<<'\n';for(VertexIndex v=0;v<graph.vertex_count();++v)file<<v<<'\t'<<v<<'\n';if(!file)throw BackendError(StatusCode::execution_failed,"cannot write closure input");}
    auto output=invoke_worker("gdlog",{path.string(),"1"},options_,temp);const auto begin=output.find("GRAPHMINE_PAIRS ");certify(begin!=std::string::npos,"missing closure output");
    std::istringstream stream(output.substr(begin+16));std::uint64_t count;certify(static_cast<bool>(stream>>count) && count<=graph.vertex_count()*graph.vertex_count(),"invalid closure count");std::set<Arc> pairs;
    for(std::uint64_t i=0;i<count;++i){std::uint32_t u,v;certify(static_cast<bool>(stream>>u>>v) && u<graph.vertex_count() && v<graph.vertex_count(),"invalid closure pair");certify(pairs.emplace(u,v).second,"duplicate closure pair");}
    std::string end;certify(static_cast<bool>(stream>>end) && end=="GRAPHMINE_END","incomplete closure output");
    for(VertexIndex v=0;v<graph.vertex_count();++v)certify(pairs.count({v,v}),"closure must be reflexive");
    for(auto [u,v]:pairs)result.reachable_pairs.push_back({graph.external_id(u),graph.external_id(v)});
    result.reachable_pair_count=result.reachable_pairs.size();return result;
  });
}
std::vector<BackendInfo> TransitiveClosure::backends(){return {info("gdlog",{"exact reflexive transitive closure; directed input; loops/duplicates normalized","complete pair materialization, at most 1024 vertices; no persistent reachability index"})};}

SupportReport ButterflyCounting::supports(const Graph& graph) const {
  if(options_.backend=="gamma-butterfly")return GammaButterflyCounting(options_).supports(graph);
  if(options_.backend!="graphminer" && options_.backend!="auto")return {false,"unknown butterfly backend"};
  return support([&]{bipartite(graph);require(options_.execution.device_ids.size()==1 && options_.execution.device_ids[0]>=0,"exactly one nonnegative CUDA device id is supported");auto s=GraphMotifs(motif_options(options_)).supports(graph,{square()});require(s.supported,s.reason);});
}
ExecutionResult<ButterflyOutput> ButterflyCounting::run(const Graph& graph) const {
  if(options_.backend=="gamma-butterfly")return GammaButterflyCounting(options_).run(graph);
  if(options_.backend!="graphminer" && options_.backend!="auto")return ExecutionResult<ButterflyOutput>::failure({StatusCode::unsupported,"unknown butterfly backend"});
  return execute<ButterflyOutput>("graphminer",[&]{bipartite(graph);require(options_.execution.device_ids.size()==1 && options_.execution.device_ids[0]>=0,"exactly one nonnegative CUDA device id is supported");auto counted=GraphMotifs(motif_options(options_)).run(graph,{square()});if(!counted.ok())throw BackendError(counted.status().code(),counted.status().message());certify(counted.value().motifs.size()==1,"missing butterfly count");return ButterflyOutput{counted.value().motifs[0].count};});
}
std::vector<BackendInfo> ButterflyCounting::backends(){bool compiled=false;for(const auto& backend:GraphMotifs::backends())if(backend.id=="graphminer")compiled=backend.compiled;auto result=GammaButterflyCounting::backends();result.insert(result.begin(),info("graphminer",{"exact global butterfly count on checked bipartite topology","reuses existing GraphMiner square kernel; no alpha/beta core or listing modes"},compiled));return result;}
} // namespace graphmine
