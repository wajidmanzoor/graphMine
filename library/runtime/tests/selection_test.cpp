#include "graphmine/runtime.hpp"
#include <boost/json.hpp>
#include <algorithm>
#include <cmath>
#include <iostream>
#include <limits>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

namespace json = boost::json;
namespace {
std::size_t calls = 0;
std::string backend = "cpp";
int device = 0;
void check(bool test, const std::string& message) { if (!test) throw std::runtime_error(message); }
json::value id(int v) { return v == 0 ? json::value(0) : v == 1 ? json::value("0") : json::value(INT64_C(9007199254740991)+v); }
int index(const json::value& value, int n) { for (int i = 0; i < n; ++i) if (value == id(i)) return i; throw std::runtime_error("Changed typed identity"); }
json::object fixture(int n, bool directed, unsigned bits) {
  json::array vertices, edges;
  for (int v = 0; v < n; ++v) vertices.push_back(json::object{{"id",id(v)},{"label","label"},{"type","vertex"},{"attributes",{{"nested",json::array{nullptr,true,INT64_MAX,"payload",json::object{{"x",1.5}}}}}}});
  unsigned bit = 0;
  for (int u = 0; u < n; ++u) for (int v = directed ? 0 : u+1; v < n; ++v,++bit) if (bits & (1U<<bit)) {
    edges.push_back(json::object{{"id",bit%2 ? json::value(std::to_string(bit)) : json::value(bit)},{"source",id(u)},{"target",id(v)},
                                {"weight",1},{"type",bit%2?"blue":"red"},{"timestamp",static_cast<int>(bit)},{"attributes",{{"a",json::array{false,3.5}}}}});
  }
  if (!edges.empty() && bits%7 == 0) { auto extra = edges.front().as_object(); extra["id"] = "parallel"; edges.push_back(extra); }
  if (!directed && n && bits%11 == 0) edges.push_back(json::object{{"id","loop"},{"source",id(0)},{"target",id(0)},{"weight",1},{"type","red"},{"timestamp",0}});
  return {{"graph",{{"id","selection-oracle"},{"directed",directed},{"allows_self_loops",true},{"allows_parallel_edges",true},{"attributes",{{"source","preserved"}}}}},{"vertices",vertices},{"edges",edges}};
}
json::object request(const char* op, const json::object& graph, json::object args = {}) {
  return {{"command","run"},{"operation",op},{"graph",graph},{"parameters",args},{"backend",backend},{"device",backend=="cpp"?"cpu":"gpu"},{"gpu_device",device}};
}
json::object invoke(const json::object& req, const char* error = nullptr) {
  const auto out = json::parse(graphmine::runtime::request(json::serialize(req))).as_object(); ++calls;
  if (calls%500 == 0) std::cerr << "Validated " << calls << " selection requests\n";
  if (error) { check(out.contains("error") && out.at("error").as_object().at("code") == error,"Wrong error: "+json::serialize(out)); return out; }
  check(!out.contains("error"),"Native failure: "+json::serialize(out));
  if (req.at("backend") != "auto") check(out.at("backend").as_object().at("id") == req.at("backend"),"Wrong backend");
  check(out.at("complete").as_bool(),"Incomplete output"); return out;
}
std::vector<std::vector<int>> distances(const json::object& graph, int n, const std::string& direction = "outgoing") {
  std::vector<std::vector<int>> d(n,std::vector<int>(n,10000)); for (int v = 0; v < n; ++v) d[v][v] = 0;
  for (const auto& raw : graph.at("edges").as_array()) {
    const auto& e = raw.as_object(); auto u=index(e.at("source"),n), v=index(e.at("target"),n);
    if (direction == "incoming") std::swap(u,v); if (u!=v) d[u][v] = 1;
    if (!graph.at("graph").as_object().at("directed").as_bool() || direction=="undirected_projection") if (u!=v) d[v][u] = 1;
  }
  for (int k=0;k<n;++k) for(int u=0;u<n;++u) for(int v=0;v<n;++v) d[u][v]=std::min(d[u][v],d[u][k]+d[k][v]); return d;
}
void independent() {
  for (int n=0;n<=5;++n) for(unsigned bits=0;bits<(1U<<(n*(n-1)/2));++bits) {
    const auto graph=fixture(n,false,bits); const auto d=distances(graph,n);
    for (const int seed : {0,97}) {
      const auto out=invoke(request("maximal-independent-set",graph,{{"random_seed",seed}})); const auto& result=out.at("result").as_object();
      std::set<int> selected; for(const auto& v:result.at("vertices").as_array()) check(selected.insert(index(v,n)).second,"Duplicate MIS vertex");
      for(int u=0;u<n;++u) {
        bool covered=selected.count(u); for(const auto v:selected) { if(selected.count(u)) check(u==v || d[u][v]!=1,"Non-independent set"); else covered |= d[u][v]==1; }
        check(covered,"Non-maximal independent set");
      }
      check(result.at("size").to_number<std::size_t>()==selected.size() && result.at("maximal")==true,"Invalid MIS summary");
      if(backend=="cpp" && bits%29==0) check(invoke(request("maximal-independent-set",graph,{{"random_seed",seed}})).at("result")==result,"CPU seed replay changed MIS");
    }
  }
}
void coloring() {
  for(int n=0;n<=5;++n) for(unsigned bits=0;bits<(1U<<(n*(n-1)/2));++bits) {
    const auto graph=fixture(n,false,bits); const auto d=distances(graph,n);
    for(const int radius:{1,2}) {
      const auto out=invoke(request("vertex-coloring",graph,{{"distance",radius},{"random_seed",bits}})); const auto& r=out.at("result").as_object();
      std::map<int,int> colors; std::set<int> used;
      for(const auto& raw:r.at("colors").as_array()) { const auto& row=raw.as_object(); const int v=index(row.at("vertex"),n), c=row.at("color").to_number<int>(); check(c>=0 && colors.emplace(v,c).second,"Invalid color mapping"); used.insert(c); }
      check(colors.size()==static_cast<std::size_t>(n),"Coloring lost isolates");
      for(int u=0;u<n;++u) for(int v=u+1;v<n;++v) if(d[u][v]<=radius) check(colors[u]!=colors[v],"Distance coloring conflict");
      check(r.at("color_count").to_number<std::size_t>()==used.size(),"Wrong color count");
    }
  }
}
void subgraph_case(const json::object& graph,int n,const char* mode,json::array seeds,int radius,const char* direction) {
  const auto d=distances(graph,n,direction); std::set<int> chosen;
  for(const auto& raw:seeds) { const int u=index(raw,n); chosen.insert(u); if(std::string(mode)=="ego") for(int v=0;v<n;++v) if(d[u][v]<=radius) chosen.insert(v); }
  const auto out=invoke(request("induced-subgraph",graph,{{"mode",mode},{"vertices_or_seeds",seeds},{"radius",radius},{"direction_mode",direction}}));
  auto expected=graph; json::array vertices,edges,ids;
  for(int v=0;v<n;++v) if(chosen.count(v)) { vertices.push_back(graph.at("vertices").as_array()[v]); ids.push_back(id(v)); }
  for(const auto& raw:graph.at("edges").as_array()) { const auto& e=raw.as_object(); if(chosen.count(index(e.at("source"),n)) && chosen.count(index(e.at("target"),n))) edges.push_back(raw); }
  expected["vertices"]=vertices; expected["edges"]=edges;
  const auto& result=out.at("result").as_object(); check(result.at("subgraph")==expected && result.at("graph")==expected,"Subgraph selection/properties differ");
  const auto& mapping=result.at("vertex_mapping").as_object(); check(mapping.at("local_to_original")==ids,"Missing vertex mapping");
  for(std::size_t v=0;v<ids.size();++v) { const auto& row=mapping.at("original_to_local").as_array()[v].as_object(); check(row.at("vertex")==ids[v] && row.at("local_index").to_number<std::size_t>()==v && row.at("input_index").to_number<int>()==index(ids[v],n),"Invalid reverse vertex mapping"); }
  const auto& port=out.at("ports").as_object().at("graph").as_object(); check(port.at("value")==expected && port.at("input_fingerprint")==out.at("input_fingerprint"),"Graph port lost provenance");
  if(!ids.empty() && radius==0) {
    auto next=request("breadth-first-search",expected,{{"sources",json::array{ids.front()}}}); next["backend"]="cpp";next["device"]="cpu";
    check(invoke(next).at("graph_fingerprint")==port.at("graph_fingerprint"),"Derived graph fingerprint cannot be chained");
  }
}
void subgraphs() {
  for(const bool directed:{false,true}) {
    const int n=directed?3:4; const unsigned end=directed?512:64;
    for(unsigned bits=0;bits<end;++bits) {
      const auto graph=fixture(n,directed,bits);
      for(const char* direction:{"outgoing","incoming","undirected_projection"}) for(int radius:{0,1,2,4})
        subgraph_case(graph,n,"ego",bits%2?json::array{id(0)}:json::array{id(0),id(n-1),id(0)},radius,direction);
      if(backend=="cpp") for(unsigned subset=0;subset<(1U<<n);++subset) { json::array vertices;for(int v=0;v<n;++v) if(subset&(1U<<v)) vertices.push_back(id(v));subgraph_case(graph,n,"induced",vertices,1,"outgoing"); }
    }
  }
  subgraph_case(fixture(0,false,0),0,"ego",{},0,"incoming");
  subgraph_case(fixture(3,true,7),3,"ego",{},3,"outgoing");
}
void walks() {
  for(bool directed:{false,true}) {
    const int n=directed?3:4; const unsigned end=directed?512:64;
    for(unsigned bits=0;bits<end;++bits) {
      auto graph=fixture(n,directed,bits);
      for(auto& raw:graph.at("edges").as_array()) raw.as_object()["weight"]=static_cast<int>(bits%4);
      for(const char* model:{"uniform","weighted","node2vec"}) {
        if(backend!="cpp" && std::string(model)=="node2vec") continue;
        json::array starts{id(0),id(0),id(n-1)};
        auto req=request("random-walks",graph,{{"start_vertices",starts},{"length",7},{"walk_model",model},{"random_seed",bits}});
        if(std::string(model)=="node2vec") { req.at("parameters").as_object()["p"]=0.25;req.at("parameters").as_object()["q"]=2; }
        const auto out=invoke(req); const auto& r=out.at("result").as_object(); check(r.at("walks").as_array().size()==starts.size(),"Lost repeated walk starts");
        for(std::size_t i=0;i<starts.size();++i) {
          const auto& path=r.at("walks").as_array()[i].as_array(); check(!path.empty() && path.front()==starts[i] && path.size()<=8 && r.at("lengths").as_array()[i].to_number<std::size_t>()==path.size()-1,"Invalid walk layout");
          for(std::size_t j=1;j<path.size();++j) { bool found=false; for(const auto& raw:graph.at("edges").as_array()) { const auto& e=raw.as_object(); if(std::string(model)!="uniform" && e.at("weight")==0) continue;found |= (e.at("source")==path[j-1] && e.at("target")==path[j]) || (!directed && e.at("source")==path[j] && e.at("target")==path[j-1]); } check(found,"Ineligible walk transition"); }
          if(path.size()<8) for(const auto& raw:graph.at("edges").as_array()) { const auto& e=raw.as_object(); if(std::string(model)!="uniform" && e.at("weight")==0) continue;check(e.at("source")!=path.back() && (directed || e.at("target")!=path.back()),"Walk ended before sink"); }
        }
        if(bits%31==0) check(invoke(req).at("result")==r,"Seeded walk replay differs");
      }
    }
  }
}
using Sample = std::tuple<int,int,std::string,int,int>;
std::multiset<Sample> sample_rows(const json::array& rows,int n) {
  std::multiset<Sample> result; for(const auto& raw:rows) { const auto& r=raw.as_object(); const auto batch=r.at("batch").to_number<int>(); check(r.at("seed")==id(batch==1?n-1:0),"Lost seed batch identity"); result.emplace(batch,r.at("hop").to_number<int>(),json::serialize(r.at("edge_id")),index(r.at("source"),n),index(r.at("target"),n)); } return result;
}
void sampling() {
  check(backend=="cpp","Neighborhood sampling currently has a native CPU profile");
  for(bool directed:{false,true}) for(unsigned bits=0;bits<(directed?512U:64U);++bits) {
    const int n=directed?3:4;auto graph=fixture(n,directed,bits);
    for(bool typed:{false,true}) for(bool weighted:{false,true}) {
      json::object args{{"seeds",json::array{id(0),id(n-1),id(0)}},{"fanouts",json::array{-1,-1}},{"sampling_model",weighted?"weighted":"uniform"},{"random_seed",bits}};
      if(typed) args["edge_type_fanouts"]=json::object{{"blue",json::array{0,-1}}};
      if(bits%3==0) args["time_cutoff"]=3;
      if(weighted) for(auto& raw:graph.at("edges").as_array()) raw.as_object()["weight"]=0;
      const auto out=invoke(request("neighborhood-sampling",graph,args));std::multiset<Sample> expected; std::set<int> seen{0,n-1};
      for(int batch=0;batch<3;++batch) { std::set<int> frontier{batch==1?n-1:0};for(int hop=1;hop<=2;++hop) { std::set<int> next;
        for(const auto u:frontier) for(const auto& raw:graph.at("edges").as_array()) {
          const auto& e=raw.as_object();if(bits%3==0 && e.at("timestamp").to_number<int>()>3) continue;if(typed && hop==1 && e.at("type")=="blue") continue;
          auto a=index(e.at("source"),n),b=index(e.at("target"),n);if(!directed && b==u) std::swap(a,b);if(a!=u) continue;
          expected.emplace(batch,hop,json::serialize(e.at("id")),a,b);next.insert(b);seen.insert(b);
        } frontier=next;
      }}
      const auto& r=out.at("result").as_object();check(sample_rows(r.at("sampled_edges").as_array(),n)==expected,"Neighborhood all-edge oracle mismatch");std::set<int> selected;for(const auto& v:r.at("sampled_vertices").as_array())selected.insert(index(v,n));check(selected==seen,"Sample lost seeds or vertices");
    }
  }
}
void probability() {
  auto graph=fixture(3,true,0);graph["edges"]=json::array{
    json::object{{"id",0},{"source",id(0)},{"target",id(1)},{"weight",1}},
    json::object{{"id",1},{"source",id(0)},{"target",id(2)},{"weight",2}},
    json::object{{"id",2},{"source",id(0)},{"target",id(2)},{"weight",1}}};
  json::array starts;for(int i=0;i<12000;++i)starts.push_back(id(0));
  for(const char* model:{"uniform","weighted"}) {
    const auto req=request("random-walks",graph,{{"start_vertices",starts},{"length",1},{"walk_model",model},{"random_seed",8712}});
    const auto result=invoke(req).at("result").as_object();int one=0;for(const auto& raw:result.at("walks").as_array()) one+=raw.as_array()[1]==id(1);
    check(std::abs(one/12000.0-(std::string(model)=="uniform"?0.5:0.25))<0.03,"Walk empirical distribution violates parallel-edge policy");
  }
  if(backend!="cpp") return;
  for(const char* model:{"uniform","weighted"}) for(bool replacement:{false,true}) {
    const auto out=invoke(request("neighborhood-sampling",graph,{{"seeds",json::array{id(0)}},{"fanouts",json::array{replacement?12000:20}},{"replacement",replacement},{"sampling_model",model},{"random_seed",89}}));
    const auto& rows=out.at("result").as_object().at("sampled_edges").as_array();check(rows.size()==(replacement?12000U:3U),"Wrong replacement sample size");
    if(replacement) {int one=0;for(const auto& raw:rows)one+=raw.as_object().at("edge_id")==0;check(std::abs(one/12000.0-(std::string(model)=="uniform"?1.0/3:0.25))<0.03,"Edge-instance sample distribution mismatch");}
    else {std::set<std::string> unique;for(const auto& raw:rows)unique.insert(json::serialize(raw.as_object().at("edge_id")));check(unique.size()==3,"Repeated edge without replacement");}
  }
  // After deterministic 0->1, weighted node2vec choices are return 0 with
  // mass 2/p and outward 2 with mass 3/q. q/p=2 makes P(return)=4/7.
  graph["edges"]=json::array{json::object{{"id",0},{"source",id(0)},{"target",id(1)},{"weight",1}},json::object{{"id",1},{"source",id(1)},{"target",id(0)},{"weight",2}},json::object{{"id",2},{"source",id(1)},{"target",id(2)},{"weight",3}}};
  auto req=request("random-walks",graph,{{"start_vertices",starts},{"length",2},{"walk_model","node2vec"},{"p",0.5},{"q",1},{"random_seed",988}});req["budget"]=json::object{{"max_candidates",4000000}};
  const auto out=invoke(req);int returned=0;for(const auto& raw:out.at("result").as_object().at("walks").as_array())returned+=raw.as_array()[2]==id(0);check(std::abs(returned/12000.0-4.0/7)<0.03,"Wrong weighted node2vec bias");
}
void contracts() {
  auto graph=fixture(3,false,7);
  for(const char* op:{"maximal-independent-set","vertex-coloring"}) {
    invoke(request(op,graph,{{"random_seed",true}}),"invalid_input");
    auto directed=graph;directed.at("graph").as_object()["directed"]=true;invoke(request(op,directed),"invalid_input");
    invoke(request(op,graph,{{"extra",1}}),"invalid_input");
    auto req=request(op,graph);req["budget"]=json::object{{"max_candidates",1}};invoke(req,"resource_limit");
    invoke(request(op,fixture(0,false,0),{{"random_seed",-1}}));
  }
  for(json::value distance:json::array{0,3,1.5,true,nullptr})invoke(request("vertex-coloring",graph,{{"distance",distance}}),"invalid_input");
  invoke(request("induced-subgraph",graph,{{"mode","ego"},{"vertices_or_seeds",json::array{"missing"}}}),"invalid_input");
  invoke(request("induced-subgraph",graph,{{"mode","ego"},{"vertices_or_seeds",json::array{0}},{"radius",-1}}),"invalid_input");
  invoke(request("random-walks",graph,{{"start_vertices",json::array{0}},{"length",-1}}),"invalid_input");
  invoke(request("random-walks",graph,{{"start_vertices",json::array{false}},{"length",1}}),"invalid_input");
  invoke(request("random-walks",graph,{{"start_vertices",json::array{0}},{"length",1},{"p",2}}),"invalid_input");
  invoke(request("random-walks",graph,{{"start_vertices",json::array{0}},{"length",0}}));
  invoke(request("random-walks",fixture(0,true,0),{{"start_vertices",json::array{}},{"length",UINT64_MAX}}));
  if(backend!="cpp") {
    invoke(request("induced-subgraph",graph,{{"mode","induced"},{"vertices_or_seeds",json::array{0}}}),"unsupported_input");
    invoke(request("random-walks",graph,{{"start_vertices",json::array{0}},{"length",2},{"walk_model","node2vec"}}),"unsupported_input");
    auto req=request("random-walks",graph,{{"start_vertices",json::array{0}},{"length",UINT64_MAX}});invoke(req,"resource_limit");
    return;
  }
  for(json::value fans:json::array{nullptr,json::array{-2},json::array{true},json::array{1.5}}) invoke(request("neighborhood-sampling",graph,{{"seeds",json::array{0}},{"fanouts",fans}}),"invalid_input");
  invoke(request("neighborhood-sampling",graph,{{"seeds",json::array{0}},{"fanouts",json::array{1}},{"edge_type_fanouts",json::object{{"red",json::array{1,2}}}}}),"invalid_input");
  auto req=request("neighborhood-sampling",graph,{{"seeds",json::array{0}},{"fanouts",json::array{INT64_MAX}},{"replacement",true}});invoke(req,"resource_limit");
}
void boundaries() {
  auto graph=fixture(3,true,0);
  graph["edges"]=json::array{json::object{{"id",0},{"source",id(0)},{"target",id(1)},{"weight",std::numeric_limits<double>::max()}},json::object{{"id",1},{"source",id(0)},{"target",id(2)},{"weight",std::numeric_limits<double>::denorm_min()}}};
  auto req=request("random-walks",graph,{{"start_vertices",json::array{id(0)}},{"length",1},{"walk_model","weighted"},{"random_seed",3}});
  if(backend!="cpp") {invoke(req,"unsupported_input");req["device"]="auto";req["backend"]="auto";check(invoke(req).at("backend").as_object().at("id")=="cpp","Unsafe GPU sampling did not route to CPU");return;}
  invoke(req);req.at("parameters").as_object()["walk_model"]="node2vec";req.at("parameters").as_object()["p"]=std::numeric_limits<double>::denorm_min();invoke(req);
  for(const auto& timestamp:json::array{"1970-01-01T00:00:00Z","1969-12-31T19:00:00-05:00","1970-01-01T01:00:00+01:00","1970-01-01T00:00:00.0000000000000000001Z",0,INT64_C(9007199254740993)}) {
    graph.at("edges").as_array()[0].as_object()["timestamp"]=timestamp;graph.at("edges").as_array().resize(1);
    const auto out=invoke(request("neighborhood-sampling",graph,{{"seeds",json::array{0}},{"fanouts",json::array{-1}},{"time_cutoff",0}}));
    const bool retained=timestamp=="1970-01-01T00:00:00Z" || timestamp=="1969-12-31T19:00:00-05:00" || timestamp=="1970-01-01T01:00:00+01:00" || timestamp==0;
    check(out.at("result").as_object().at("sampled_edges").as_array().size()==static_cast<std::size_t>(retained),"Inexact timestamp cutoff");
  }
  for(const char* timestamp:{"1970-01-01T00:00:00","2023-02-29T00:00:00Z","2000-13-01T00:00:00Z","2000-01-01T00:00:60Z","2000-01-01T00:00:00+24:00","2000-01-01T00:00:00.Z"}) {
    graph.at("edges").as_array()[0].as_object()["timestamp"]=timestamp;invoke(request("neighborhood-sampling",graph,{{"seeds",json::array{0}},{"fanouts",json::array{-1}},{"time_cutoff",0}}),"invalid_input");
  }
  graph.at("edges").as_array()[0].as_object()["timestamp"]=INT64_C(9007199254740993);
  auto temporal=request("neighborhood-sampling",graph,{{"seeds",json::array{0}},{"fanouts",json::array{-1}},{"time_cutoff",INT64_C(9007199254740992)}});
  check(invoke(temporal).at("result").as_object().at("sampled_edges").as_array().empty(),"Large integer timestamp rounded down");
  temporal.at("parameters").as_object()["time_cutoff"]=INT64_C(9007199254740993);check(invoke(temporal).at("result").as_object().at("sampled_edges").as_array().size()==1,"Large exact timestamp excluded");
}
void large() {
  // Cross warp/block boundaries and preserve an isolate. Verify mathematical
  // invariants independently of cuGraph's choice of set, colors or random path.
  constexpr int n = 258;
  auto graph = fixture(0,false,0);
  json::array vertices, edges;
  for (int v=0;v<n;++v) vertices.push_back(json::object{{"id",id(v)}});
  for (int v=0;v<n-2;++v) edges.push_back(json::object{{"id",v},{"source",id(v)},{"target",id(v+1)}});
  graph["vertices"]=vertices; graph["edges"]=edges;
  const auto mis=invoke(request("maximal-independent-set",graph,{{"random_seed",7919}}));
  std::set<int> chosen;
  for(const auto& value:mis.at("result").as_object().at("vertices").as_array()) chosen.insert(index(value,n));
  check(chosen.count(n-1),"MIS dropped isolate");
  for(int v=0;v<n-1;++v) {
    check(!chosen.count(v) || v==0 || !chosen.count(v-1),"Large MIS is not independent");
    check(chosen.count(v) || (v && chosen.count(v-1)) || (v<n-2 && chosen.count(v+1)),"Large MIS is not maximal");
  }
  for(const int radius:{1,2}) {
    const auto result=invoke(request("vertex-coloring",graph,{{"distance",radius},{"random_seed",7919}}));
    std::map<int,int> colors;
    for(const auto& raw:result.at("result").as_object().at("colors").as_array()) { const auto& row=raw.as_object();colors.emplace(index(row.at("vertex"),n),row.at("color").to_number<int>()); }
    check(colors.size()==n,"Large coloring dropped vertices");
    for(int v=0;v<n-1;++v) for(int d=1;d<=radius && v+d<n-1;++d) check(colors[v]!=colors[v+d],"Large distance coloring conflict");
  }
  const auto ego=invoke(request("induced-subgraph",graph,{{"mode","ego"},{"vertices_or_seeds",json::array{id(128),id(n-1)}},{"radius",128}}));
  check(ego.at("result").as_object().at("graph")==graph,"Large ego graph lost records or isolate");
  graph.at("graph").as_object()["directed"]=true;
  for(const char* model:{"uniform","weighted"}) {
    const auto result=invoke(request("random-walks",graph,{{"start_vertices",json::array{id(0),id(128),id(n-1),id(0)}},{"length",300},{"walk_model",model},{"random_seed",7919}}));
    const auto& paths=result.at("result").as_object().at("walks").as_array();
    for(std::size_t i=0;i<paths.size();++i) {
      const int start=i==1?128:i==2?n-1:0, count=i==2?1:n-1-start;
      check(paths[i].as_array().size()==static_cast<std::size_t>(count),"Large walk did not stop at sink");
      for(int j=0;j<count;++j) check(paths[i].as_array()[j]==id(start+j),"Large walk changed ID or direction");
    }
  }
  auto limited=request("random-walks",graph,{{"start_vertices",json::array{id(0)}},{"length",300},{"random_seed",7919}});
  limited["budget"]=json::object{{"max_output_items",2}}; invoke(limited,"resource_limit");
  graph.at("graph").as_object()["directed"]=false;
  for(const char* op:{"maximal-independent-set","vertex-coloring"}) {
    auto req=request(op,graph,{{"random_seed",7919}});
    req["budget"]=json::object{{"max_output_items",1}};invoke(req,"resource_limit");
    req["budget"]=json::object{{"timeout_seconds",1e-12}};invoke(req,"resource_limit");
  }
}
}
int main(int argc,char** argv) {
  try {
    const std::string suite=argc>1?argv[1]:"contracts";if(argc>2)backend=argv[2];if(argc>3)device=std::stoi(argv[3]);
    if(suite=="contracts")contracts();else if(suite=="independent")independent();else if(suite=="coloring")coloring();else if(suite=="subgraphs")subgraphs();else if(suite=="walks")walks();else if(suite=="sampling")sampling();else if(suite=="probability")probability();else if(suite=="boundaries")boundaries();else if(suite=="large")large();else throw std::runtime_error("Unknown suite");
    const auto catalog=json::parse(graphmine::runtime::request(R"({"command":"catalog"})")).as_object();
    std::cout << json::serialize(json::object{{"suite",suite},{"backend",backend},{"gpu_device",device},{"passed_requests",calls},{"failed",0},{"implementation_sha256",catalog.at("implementation_sha256")}}) << '\n';return 0;
  } catch(const std::exception& e) {std::cerr << "after " << calls << " requests: " << e.what() << '\n';return 1;}
}
