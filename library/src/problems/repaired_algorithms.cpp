#include "graphmine/problems/repaired_algorithms.hpp"
#include "worker_process.hpp"
#include <boost/json.hpp>
#include <iomanip>
#include <regex>
#include <tuple>

namespace graphmine {
namespace {
using namespace detail::isolated;
namespace json = boost::json;
using Arc = std::pair<std::uint32_t,std::uint32_t>;

Provenance origin(const std::string& name) {
  static const std::map<std::string,std::pair<std::string,std::string>> entries{
    {"acctd",{"k_truss_decomposition","a8faa445ccb45c18383087db488eff9d1836d8d1"}},
    {"mbe-gpu",{"maximal_biclique_enumeration","4ef91a0c8fd9f756d5bb086fd11ce3e4bfff9942"}},
    {"cds",{"densest_subgraph","3e704f98cf873336e2cf789570774039c8d6f092"}},
    {"kpar",{"personalized_pagerank_rwr","v1.0:791987a738faf84d0fcab882b2f74cbb2efd4451ac9888b80e0d120ea6421916"}},
    {"gpu4gst",{"group_steiner_tree","716a19c240c480cb2d23435bbaca55163a48e174"}},
    {"superfuser",{"influence_maximization","1506d275671a456e41bbc7bcb294876615353b2d"}},
    {"gamma-butterfly",{"butterfly_counting_bipartite","3e01be68ededb8dcc4fa44bdb069a945a822232c"}}};
  const auto& entry=entries.at(name);
  return {entry.first,name,"validated repair 2026-10-04",entry.second,"isolated repaired GPU worker; canonical external IDs"};
}
bool compiled(const std::string& backend) {
  if (!GRAPHMINE_HAS_REPAIRED_WORKERS) return false;
  try {return access(worker_path(backend,{}).c_str(),X_OK)==0;} catch (...) {return false;}
}
BackendInfo info(const std::string& name,std::vector<std::string> capabilities) {
  auto p=origin(name);return {name,name,p.problem,p.source_commit,compiled(name),true,std::move(capabilities)};
}
void common(const Graph& graph,const IsolatedBackendOptions& options,const std::string& backend) {
  require(options.execution.device_ids.size()==1 && options.execution.device_ids[0]>=0,"exactly one nonnegative CUDA device id is supported");
  require(options.timeout_seconds>0 && options.timeout_seconds<=86400,"timeout_seconds must be in [1,86400]");
  require(graph.vertex_count()<=1000000 && graph.edge_count()<=10000000,"adapter limit: 1,000,000 vertices and 10,000,000 input edges");
  if (!GRAPHMINE_HAS_REPAIRED_WORKERS || access(worker_path(backend,options).c_str(),X_OK)!=0)
    throw BackendError(StatusCode::backend_unavailable,"repaired worker is not installed: "+backend);
}
template<class F> SupportReport support(F fn) {
  try {fn();return {true,{}};} catch (const std::exception& e) {return {false,e.what()};}
}
template<class Output,class F> ExecutionResult<Output> execute(const std::string& backend,F fn) {
  const auto start=Clock::now();const auto p=origin(backend);
  try {
    auto out=fn();ExecutionStatistics stats;
    stats.end_to_end_ms=std::chrono::duration<double,std::milli>(Clock::now()-start).count();
    std::vector<std::string> warnings;
    if(backend=="kpar")warnings.push_back("Approximate scores at restart probability 0.2; epsilon is a sampling parameter, not a certified per-run error bound.");
    if(backend=="superfuser")warnings.push_back("Independent-cascade heuristic; guarantee_met is false. Spread is estimated on independent holdout samples.");
    return ExecutionResult<Output>::success(std::move(out),p,stats,std::move(warnings));
  } catch(const BackendError& e){return ExecutionResult<Output>::failure({e.code,e.what()},p);}
  catch(const std::invalid_argument& e){return ExecutionResult<Output>::failure({StatusCode::unsupported,e.what()},p);}
  catch(const std::bad_alloc&){return ExecutionResult<Output>::failure({StatusCode::resource_exhausted,"host allocation failed"},p);}
  catch(const std::exception& e){return ExecutionResult<Output>::failure({StatusCode::execution_failed,e.what()},p);}
}
std::string text_file(const fs::path& path) {
  std::error_code ec;auto size=fs::file_size(path,ec);
  certify(!ec && size<=64ULL*1024*1024,"worker result is missing or exceeds 64 MiB");
  std::ifstream in(path);std::string result((std::istreambuf_iterator<char>(in)),{});
  certify(!in.bad(),"cannot read worker result");return result;
}
void write_text(const fs::path& path,const std::string& text) {
  std::ofstream out(path);out<<text;out.close();
  if(!out)throw BackendError(StatusCode::execution_failed,"cannot write worker input");
}
template<class T> void write_binary(const fs::path& path,const std::vector<T>& values) {
  std::ofstream out(path,std::ios::binary);out.write(reinterpret_cast<const char*>(values.data()),values.size()*sizeof(T));out.close();
  if(!out)throw BackendError(StatusCode::execution_failed,"cannot write worker input");
}
std::string number(double value) {std::ostringstream out;out<<std::setprecision(17)<<value;return out.str();}
json::object json_result(const std::string& output,const std::string& marker) {
  std::istringstream input(output);std::string line;json::object result;bool found=false;
  while(std::getline(input,line))if(line.rfind(marker,0)==0) {
    certify(!found,"duplicate structured worker result");found=true;
    boost::system::error_code error;auto value=json::parse(line.substr(marker.size()),error);
    certify(!error && value.is_object(),"invalid structured worker result");result=value.as_object();
  }
  certify(found,"missing structured worker result");return result;
}
std::uint64_t integer(const json::value& value) {
  certify(value.is_uint64() || (value.is_int64() && value.as_int64()>=0),"expected nonnegative worker integer");
  return value.is_uint64()?value.as_uint64():static_cast<std::uint64_t>(value.as_int64());
}
double real(const json::value& value) {
  certify(value.is_number(),"expected worker number");auto result=value.to_number<double>();
  certify(std::isfinite(result),"nonfinite worker number");return result;
}
std::vector<VertexIndex> vertices(const json::value& value,const Graph& graph) {
  certify(value.is_array(),"expected worker vertex array");std::vector<VertexIndex> result;std::set<VertexIndex> seen;
  for(const auto& item:value.as_array()) {auto v=integer(item);certify(v<graph.vertex_count() && seen.insert(v).second,"invalid or duplicate worker vertex");result.push_back(v);}
  return result;
}
void unweighted(const Graph& graph) {
  for(const auto& edge:graph.canonical().edges)require(!edge.weight || *edge.weight==1,"this profile requires unweighted edges (or unit weights)");
}
std::map<Arc,std::size_t> edge_ids(const Graph& graph) {
  std::map<Arc,std::size_t> result;
  for(std::size_t i=0;i<graph.edge_count();++i) {
    auto u=graph.dense_index(graph.canonical().edges[i].source),v=graph.dense_index(graph.canonical().edges[i].target);
    if(u==v)continue;if(u>v)std::swap(u,v);
    auto found=result.find({u,v});if(found==result.end() || graph.canonical().edges[i].id<graph.canonical().edges[found->second].id)result[{u,v}]=i;
  }
  return result;
}
struct Sides {std::vector<VertexIndex> left,right;std::vector<bool> is_left;};
Sides sides(const Graph& graph) {
  require(!graph.directed(),"bipartite counts require an undirected graph");unweighted(graph);
  Sides result;result.is_left.resize(graph.vertex_count());
  for(VertexIndex v=0;v<graph.vertex_count();++v) {
    const auto& attributes=graph.canonical().vertices[v].attributes;auto found=attributes.find("side");
    require(found!=attributes.end() && std::holds_alternative<std::string>(found->second.value()),"every vertex needs attributes.side = left or right");
    auto side=std::get<std::string>(found->second.value());require(side=="left" || side=="right","invalid bipartite side");
    result.is_left[v]=side=="left";(result.is_left[v]?result.left:result.right).push_back(v);
  }
  for(const auto& edge:graph.canonical().edges)require(result.is_left[graph.dense_index(edge.source)]!=result.is_left[graph.dense_index(edge.target)],"every edge must cross the declared bipartition");
  return result;
}
void simple_support(const Graph& graph,const IsolatedBackendOptions& options,const std::string& backend) {
  common(graph,options,backend);require(!graph.directed(),"this profile requires an undirected graph");unweighted(graph);
}
void ppr_support(const Graph& graph,const PersonalizedPageRankOptions& options) {
  common(graph,options,"kpar");require(graph.directed(),"kPAR profile requires directed outgoing edges");unweighted(graph);
  require(graph.vertex_count()>0 && options.top_k>0,"PPR needs a nonempty graph and positive top_k");
  (void)graph.dense_index(options.seed_vertex);require(std::isfinite(options.epsilon) && options.epsilon>=0.01 && options.epsilon<=0.5,"epsilon must be in the validated range [0.01,0.5]");
  require(options.random_seed<=2147483647,"kPAR random seed must be at most 2147483647");
}
void influence_support(const Graph& graph,const InfluenceMaximizationOptions& options) {
  common(graph,options,"superfuser");require(graph.directed(),"independent-cascade profile requires a directed graph");
  require(options.seed_set_size>=1 && options.seed_set_size<=graph.vertex_count(),"seed_set_size must be in [1, vertex_count]");
  require(options.sample_count>=32 && options.sample_count<=65536 && options.sample_count%32==0,"sample_count must be a multiple of 32 in [32,65536]");
  for(const auto& edge:graph.canonical().edges)require(edge.weight && std::isfinite(*edge.weight) && *edge.weight>=0 && *edge.weight<=1,"every edge weight must be an explicit activation probability in [0,1]");
}
struct WeightedGraph {
  std::map<Arc,std::pair<std::int64_t,std::size_t>> edges;
  std::vector<std::vector<VertexIndex>> groups;
};
WeightedGraph steiner_input(const Graph& graph,const GroupSteinerTreeOptions& options) {
  common(graph,options,"gpu4gst");require(!graph.directed(),"group Steiner tree requires an undirected graph");
  require(!options.groups.empty() && options.groups.size()<=16,"group count must be in [1,16]");WeightedGraph result;
  for(const auto& group:options.groups) {
    require(!group.empty(),"every group must be nonempty");std::set<VertexIndex> members;
    for(const auto& vertex:group)members.insert(graph.dense_index(vertex));result.groups.emplace_back(members.begin(),members.end());
  }
  std::int64_t maximum=0;
  for(std::size_t i=0;i<graph.edge_count();++i) {
    const auto& e=graph.canonical().edges[i];require(e.weight && std::isfinite(*e.weight) && *e.weight>=0 && *e.weight<=9007199254740991.0 && std::floor(*e.weight)==*e.weight,"GST requires explicit integer weights in [0,2^53-1]");
    auto u=graph.dense_index(e.source),v=graph.dense_index(e.target);if(u==v)continue;if(u>v)std::swap(u,v);
    auto weight=static_cast<std::int64_t>(*e.weight);maximum=std::max(maximum,weight);auto found=result.edges.find({u,v});
    if(found==result.edges.end() || weight<found->second.first || (weight==found->second.first && e.id<graph.canonical().edges[found->second.second].id))result.edges[{u,v}]={weight,i};
  }
  require(graph.vertex_count()<2 || maximum<((1LL<<58)-1)/static_cast<std::int64_t>(graph.vertex_count()-1),"GST tree cost bound must be below 2^58");return result;
}
} // namespace

SupportReport KTruss::supports(const Graph& graph)const{return support([&]{simple_support(graph,options_,"acctd");});}
ExecutionResult<KTrussOutput> KTruss::run(const Graph& graph)const {
  return execute<KTrussOutput>("acctd",[&]{
    simple_support(graph,options_,"acctd");auto csr=graph.simple_undirected().csr;auto mapping=edge_ids(graph);KTrussOutput result;
    if(mapping.empty())return result;
    TempDirectory temp;std::vector<std::uint32_t> degree{4,static_cast<std::uint32_t>(graph.vertex_count()),static_cast<std::uint32_t>(csr.neighbors.size())};
    for(std::size_t v=0;v<graph.vertex_count();++v)degree.push_back(csr.offsets[v+1]-csr.offsets[v]);
    write_binary(temp.path/"b_degree.bin",degree);write_binary(temp.path/"b_adj.bin",csr.neighbors);
    auto output=temp.path/"edges.txt";
    invoke_worker("acctd",{temp.path.string(),"org"},options_,temp,{{"ACCTD_EDGE_OUTPUT",output.string()},{"OMP_NUM_THREADS","4"}});
    std::istringstream in(text_file(output));std::uint64_t u,v,k;std::map<Arc,std::uint32_t> labels;
    while(in>>u){certify(static_cast<bool>(in>>v>>k) && u<graph.vertex_count() && v<graph.vertex_count() && u!=v && k>=2 && k<=graph.vertex_count(),"invalid truss row");if(u>v)std::swap(u,v);certify(labels.emplace(Arc{u,v},k).second,"duplicate truss row");}
    certify(in.eof() && labels.size()==mapping.size(),"incomplete truss result");
    for(const auto& [edge,index]:mapping){certify(labels.count(edge),"missing edge trussness");auto k=labels.at(edge);result.truss_number_by_edge.push_back({graph.canonical().edges[index].id,k});result.maximum_truss_number=std::max(result.maximum_truss_number,k);}
    return result;
  });
}
std::vector<BackendInfo> KTruss::backends(){return {info("acctd",{"exact full per-edge truss decomposition; single GPU","unweighted undirected; loops removed; parallel edges use smallest external edge ID"})};}

SupportReport DensestSubgraph::supports(const Graph& graph)const{return support([&]{simple_support(graph,options_,"cds");require(graph.vertex_count()>0,"densest subgraph requires a nonempty graph");});}
ExecutionResult<DensestSubgraphOutput> DensestSubgraph::run(const Graph& graph)const {
  return execute<DensestSubgraphOutput>("cds",[&]{
    simple_support(graph,options_,"cds");require(graph.vertex_count()>0,"densest subgraph requires a nonempty graph");auto csr=graph.simple_undirected().csr;TempDirectory temp;auto path=temp.path/"graph.txt";
    std::ostringstream text;text<<graph.vertex_count()<<' '<<csr.undirected_edge_count()<<'\n';
    for(std::size_t v=0;v<graph.vertex_count();++v){text<<v;for(auto e=csr.offsets[v];e<csr.offsets[v+1];++e)text<<' '<<csr.neighbors[e];text<<'\n';}write_text(path,text.str());
    auto output=json_result(invoke_worker("cds",{path.string(),"2","64","128",std::to_string(std::max<std::size_t>(1024,graph.vertex_count())),"1024","-1"},options_,temp),"CDS_RESULT ");
    auto chosen=vertices(output.at("vertices"),graph);certify(!chosen.empty() && output.at("optimal").as_bool() && integer(output.at("k"))==2,"invalid density certificate");std::set<VertexIndex> present(chosen.begin(),chosen.end());DensestSubgraphOutput result;
    for(const auto& [edge,index]:edge_ids(graph))if(present.count(edge.first) && present.count(edge.second))++result.induced_edge_value;
    result.density=static_cast<double>(result.induced_edge_value)/chosen.size();
    certify(integer(output.at("vertex_count"))==chosen.size() && integer(output.at("clique_count"))==result.induced_edge_value && std::abs(real(output.at("density"))-result.density)<=1e-12,"density disagrees with returned vertex set");
    for(auto v:chosen)result.vertices.push_back(graph.external_id(v));return result;
  });
}
std::vector<BackendInfo> DensestSubgraph::backends(){return {info("cds",{"exact unweighted edge density |E(S)|/|S| with vertex witness","single GPU; nonempty undirected graph; no cardinality or weighted objective"})};}

SupportReport MaximalBicliqueCounting::supports(const Graph& graph)const{return support([&]{common(graph,options_,"mbe-gpu");sides(graph);});}
ExecutionResult<MaximalBicliqueCountingOutput> MaximalBicliqueCounting::run(const Graph& graph)const {
  return execute<MaximalBicliqueCountingOutput>("mbe-gpu",[&]{
    common(graph,options_,"mbe-gpu");auto partition=sides(graph);MaximalBicliqueCountingOutput result;if(graph.edge_count()==0)return result;
    auto csr=graph.simple_undirected().csr;std::vector<VertexIndex> local(graph.vertex_count());for(VertexIndex i=0;i<partition.left.size();++i)local[partition.left[i]]=i;
    std::ostringstream text;for(auto v:partition.right){std::set<VertexIndex> row;for(auto e=csr.offsets[v];e<csr.offsets[v+1];++e)row.insert(local[csr.neighbors[e]]);for(auto u:row)text<<u<<' ';text<<'\n';}
    TempDirectory temp;auto path=temp.path/"graph.adj";write_text(path,text.str());
    auto output=invoke_worker("mbe-gpu",{"-i",path.string(),"-s","2","-o","1","-t","0","-f"},options_,temp);
    std::smatch match;certify(std::regex_search(output,match,std::regex(",\\s*([0-9]+)\\s*,\\s*([0-9.eE+-]+)\\s*$")),"missing complete biclique count");
    result.total_count=std::stoull(match[1]);return result;
  });
}
std::vector<BackendInfo> MaximalBicliqueCounting::backends(){return {info("mbe-gpu",{"exact nonempty maximal-biclique count; scheduled single-GPU variant","declared bipartite sides; no vertex-set listing, size filter, bitmap or multi-GPU mode"})};}

SupportReport PersonalizedPageRank::supports(const Graph& graph)const{return support([&]{ppr_support(graph,options_);});}
ExecutionResult<PersonalizedPageRankOutput> PersonalizedPageRank::run(const Graph& graph)const {
  return execute<PersonalizedPageRankOutput>("kpar",[&]{
    ppr_support(graph,options_);TempDirectory temp;auto folder=temp.path/"graph";fs::create_directory(folder);auto seed=graph.dense_index(options_.seed_vertex);
    write_text(folder/"attribute.txt","n="+std::to_string(graph.vertex_count())+"\nm="+std::to_string(graph.edge_count())+"\n");
    std::ostringstream edges;for(const auto& edge:graph.canonical().edges)edges<<graph.dense_index(edge.source)<<' '<<graph.dense_index(edge.target)<<'\n';write_text(folder/"graph.txt",edges.str());write_text(folder/"queries.txt",std::to_string(seed)+"\n");
    std::vector<std::string> args{"indexing","--prefix",temp.path.string(),"--dataset","graph","--epsilon",number(options_.epsilon),"--seed",std::to_string(options_.random_seed)};
    invoke_worker("kpar",args,options_,temp);args[0]="query";args.insert(args.end(),{"--gpu_idx","0","--query_size","1","--k",std::to_string(graph.vertex_count()),"--highrrw-size","0"});
    invoke_worker("kpar",args,options_,temp);std::istringstream in(text_file(folder/"result"/(std::to_string(seed)+".txt")));std::uint64_t v;double score;std::set<VertexIndex> seen;PersonalizedPageRankOutput result;result.epsilon_used=options_.epsilon;
    while(in>>v){certify(static_cast<bool>(in>>score) && v<graph.vertex_count() && std::isfinite(score) && score>=0 && score<=1+1e-8 && seen.insert(v).second,"invalid PPR row");result.ranked_vertices.push_back({graph.external_id(v),score,0});}
    certify(in.eof() && seen.size()==graph.vertex_count(),"incomplete PPR scores");
    std::sort(result.ranked_vertices.begin(),result.ranked_vertices.end(),[](const auto& a,const auto& b){return a.score!=b.score?a.score>b.score:a.vertex<b.vertex;});
    result.complete=options_.top_k>=graph.vertex_count();result.ranked_vertices.resize(std::min<std::size_t>(options_.top_k,graph.vertex_count()));for(std::uint32_t i=0;i<result.ranked_vertices.size();++i)result.ranked_vertices[i].rank=i+1;return result;
  });
}
std::vector<BackendInfo> PersonalizedPageRank::backends(){return {info("kpar",{"approximate top-k PPR; single seed; restart probability 0.2","directed unweighted outgoing multigraph; dangling mass returns to seed; no certified error bound"})};}

SupportReport GroupSteinerTree::supports(const Graph& graph)const{return support([&]{steiner_input(graph,options_);});}
ExecutionResult<GroupSteinerTreeOutput> GroupSteinerTree::run(const Graph& graph)const {
  return execute<GroupSteinerTreeOutput>("gpu4gst",[&]{
    auto input=steiner_input(graph,options_);TempDirectory temp;std::vector<std::vector<std::pair<VertexIndex,std::int64_t>>> adjacency(graph.vertex_count());
    for(const auto& [edge,value]:input.edges){adjacency[edge.first].emplace_back(edge.second,value.first);adjacency[edge.second].emplace_back(edge.first,value.first);}
    std::vector<std::int64_t> offsets{0},dest,weights;for(auto& row:adjacency){std::sort(row.begin(),row.end());for(auto [v,w]:row){dest.push_back(v);weights.push_back(w);}offsets.push_back(dest.size());}
    write_binary(temp.path/"graph_beg_pos.bin",offsets);write_binary(temp.path/"graph_csr.bin",dest);write_binary(temp.path/"graph_weight.bin",weights);
    std::ostringstream groups,query;for(std::size_t i=0;i<input.groups.size();++i){groups<<'g'<<i+1<<':';for(auto v:input.groups[i])groups<<' '<<v;groups<<'\n';query<<i<<' ';}query<<'\n';write_text(temp.path/"graph.g",groups.str());write_text(temp.path/("graph"+std::to_string(input.groups.size())+".csv"),query.str());
    auto output=invoke_worker("gpu4gst",{"unused",temp.path.string(),"graph",std::to_string(input.groups.size()),"0","0","--witness"},options_,temp);
    GroupSteinerTreeOutput result;if(output.find("\nmin cost infeasible\n")!=std::string::npos || output.rfind("min cost infeasible\n",0)==0)return result;
    auto tree=json_result(output,"witness ");auto chosen=vertices(tree.at("vertices"),graph);certify(!chosen.empty() && integer(tree.at("query"))==0,"invalid tree vertex certificate");std::set<VertexIndex> present(chosen.begin(),chosen.end());std::vector<VertexIndex> parent(graph.vertex_count());std::iota(parent.begin(),parent.end(),0);
    auto root=[&](VertexIndex v){while(parent[v]!=v){parent[v]=parent[parent[v]];v=parent[v];}return v;};
    const auto& tree_edges=tree.at("edges").as_array();certify(tree_edges.size()+1==chosen.size(),"tree edge count mismatch");
    for(const auto& value:tree_edges){const auto& edge=value.as_array();certify(edge.size()==3,"invalid tree edge");auto u=integer(edge[0]),v=integer(edge[1]),w=integer(edge[2]);certify(present.count(u)&&present.count(v),"tree edge outside selected vertices");if(u>v)std::swap(u,v);auto found=input.edges.find({u,v});certify(found!=input.edges.end() && static_cast<std::uint64_t>(found->second.first)==w,"tree edge is absent from the input");auto a=root(u),b=root(v);certify(a!=b,"tree certificate contains a cycle");parent[a]=b;result.tree_weight+=w;result.tree_edges.push_back(graph.canonical().edges[found->second.second].id);}
    for(const auto& group:input.groups)certify(std::any_of(group.begin(),group.end(),[&](auto v){return present.count(v);}),"tree misses a group");
    certify(integer(tree.at("cost"))==static_cast<std::uint64_t>(result.tree_weight),"tree certificate cost mismatch");
    for(auto v:chosen){certify(root(v)==root(chosen[0]),"tree certificate disconnected");result.selected_vertices.push_back(graph.external_id(v));}result.feasible=true;return result;
  });
}
std::vector<BackendInfo> GroupSteinerTree::backends(){return {info("gpu4gst",{"exact undirected group Steiner tree; 1..16 nonempty groups; full tree certificate","nonnegative integer edge weights <=2^53-1; cost bound below 2^58; single GPU"})};}

SupportReport InfluenceMaximization::supports(const Graph& graph)const{return support([&]{influence_support(graph,options_);});}
ExecutionResult<InfluenceMaximizationOutput> InfluenceMaximization::run(const Graph& graph)const {
  return execute<InfluenceMaximizationOutput>("superfuser",[&]{
    influence_support(graph,options_);TempDirectory temp;std::ostringstream text;text<<graph.vertex_count()<<' '<<graph.edge_count()<<'\n'<<std::setprecision(17);
    for(const auto& edge:graph.canonical().edges)text<<graph.dense_index(edge.source)<<' '<<graph.dense_index(edge.target)<<' '<<*edge.weight<<'\n';auto path=temp.path/"graph.txt";write_text(path,text.str());
    auto output=json_result(invoke_worker("superfuser",{"-g","1","-K",std::to_string(options_.seed_set_size),"-R",std::to_string(options_.sample_count),"--seed",std::to_string(options_.random_seed),"--json",path.string()},options_,temp),"");
    auto chosen=vertices(output.at("seed_set"),graph);certify(chosen.size()==options_.seed_set_size && !output.at("guarantee_met").as_bool() && output.at("diffusion_model").as_string()=="independent_cascade","invalid influence result contract");
    InfluenceMaximizationOutput result;result.sample_count=options_.sample_count;result.expected_spread=real(output.at("expected_spread"));for(auto v:chosen)result.seed_set.push_back(graph.external_id(v));
    for(const auto& value:output.at("prefix_spread").as_array())result.prefix_spread.push_back(real(value));certify(result.prefix_spread.size()==chosen.size(),"incomplete influence prefix estimates");
    double previous=0;for(std::size_t i=0;i<result.prefix_spread.size();++i){auto spread=result.prefix_spread[i];certify(spread>=previous && spread>=i+1 && spread<=graph.vertex_count(),"invalid influence spread range");previous=spread;}
    certify(result.expected_spread==previous && integer(output.at("sample_count"))==options_.sample_count && integer(output.at("evaluation_sample_count"))==options_.sample_count && integer(output.at("random_seed"))==options_.random_seed,"influence metadata mismatch");return result;
  });
}
std::vector<BackendInfo> InfluenceMaximization::backends(){return {info("superfuser",{"approximate independent-cascade seed selection; guarantee_met=false","explicit edge probabilities; independent holdout spread; single GPU; no linear threshold"})};}

SupportReport GammaButterflyCounting::supports(const Graph& graph)const{return support([&]{common(graph,options_,"gamma-butterfly");sides(graph);});}
ExecutionResult<ButterflyOutput> GammaButterflyCounting::run(const Graph& graph)const {
  return execute<ButterflyOutput>("gamma-butterfly",[&]{
    common(graph,options_,"gamma-butterfly");sides(graph);auto csr=graph.simple_undirected().csr;ButterflyOutput result;if(csr.undirected_edge_count()<4)return result;TempDirectory temp;auto prefix=temp.path/"graph";
    {std::ofstream out(prefix.string()+".col",std::ios::binary);auto n=static_cast<std::uint32_t>(graph.vertex_count());out.write(reinterpret_cast<const char*>(&n),sizeof(n));out.write(reinterpret_cast<const char*>(csr.offsets.data()),csr.offsets.size()*8);certify(bool(out),"cannot write GAMMA offsets");}
    {std::ofstream out(prefix.string()+".dst",std::ios::binary);std::uint64_t m=csr.neighbors.size();out.write(reinterpret_cast<const char*>(&m),sizeof(m));out.write(reinterpret_cast<const char*>(csr.neighbors.data()),csr.neighbors.size()*4);certify(bool(out),"cannot write GAMMA neighbors");}
    {std::ofstream out(prefix.string()+".vlabel",std::ios::binary);auto n=static_cast<std::uint32_t>(graph.vertex_count());std::vector<char> labels(n,0);out.write(reinterpret_cast<const char*>(&n),sizeof(n));out.write(labels.data(),labels.size());certify(bool(out),"cannot write GAMMA labels");}
    auto query=temp.path/"square.query";write_text(query,"4\n0 0 0 0\n2 1 3\n2 0 2\n2 1 3\n2 0 2\n0\n0\n0\n0\n");
    auto output=invoke_worker("gamma-butterfly",{prefix.string(),query.string(),"1"},options_,temp);std::smatch match;certify(std::regex_search(output,match,std::regex("matching_embeddings: ([0-9]+)")),"missing GAMMA count");auto count=std::stoull(match[1]);certify(count%8==0,"C4 embedding count is not divisible by its eight automorphisms");result.butterfly_count=count/8;return result;
  });
}
std::vector<BackendInfo> GammaButterflyCounting::backends(){return {info("gamma-butterfly",{"exact global butterfly count from injective unlabelled C4 embeddings / 8","declared bipartite sides; single GPU; no listing or alpha/beta cores"})};}
} // namespace graphmine
