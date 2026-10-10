#include "graphmine/runtime.hpp"
#include <boost/json.hpp>
#include <boost/multiprecision/cpp_int.hpp>
#include <algorithm>
#include <iostream>
#include <limits>
#include <map>
#include <optional>
#include <queue>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

namespace json = boost::json;
using Exact = boost::multiprecision::cpp_rational;
using Integer = boost::multiprecision::cpp_int;
namespace {
std::size_t calls = 0;
std::string backend = "cpp";
int device = 0;
void check(bool ok,const std::string& message) { if (!ok) throw std::runtime_error(message); }
json::value vid(int v) { return v == 0 ? json::value(0) : v == 1 ? json::value("0") : json::value(INT64_C(9007199254740991) + v); }
json::value eid(int e) { return e == 0 ? json::value(0) : e == 1 ? json::value("0") : json::value("edge-" + std::to_string(e)); }
struct Fixture {
  int n; bool directed; json::object graph;
  Fixture(int count,bool direction,unsigned mask,unsigned base=2):n(count),directed(direction) {
    json::array vertices,edges; const auto initial=mask;
    for (int v=0;v<n;++v) vertices.push_back(json::object{{"id",vid(v)}});
    for (int u=0;u<n;++u) for (int v=directed?0:u+1;v<n;++v) if (u!=v) {
      const auto digit=mask%base;mask/=base;if(!digit)continue;
      const double capacity=base>2?digit*0.5:((u+2*v+initial)%5)*0.5;
      edges.push_back(json::object{{"id",eid(edges.size())},{"source",vid(u)},{"target",vid(v)},{"weight",capacity}});
    }
    if(!edges.empty()&&initial%7==0){auto duplicate=edges.front().as_object();duplicate["id"]="parallel";duplicate["weight"]=1.5;edges.push_back(duplicate);}
    if(n&&initial%11==0)edges.push_back(json::object{{"id","loop"},{"source",vid(0)},{"target",vid(0)},{"weight",5}});
    graph={{"graph",{{"id","flow-oracle"},{"directed",directed},{"allows_self_loops",true},{"allows_parallel_edges",true}}},{"vertices",vertices},{"edges",edges}};
  }
  int vertex(const json::value& id)const{for(int v=0;v<n;++v)if(vid(v)==id)return v;throw std::runtime_error("Lost typed vertex identity");}
};
json::object request(const Fixture& f,json::object args={}) {
  args["source"]=vid(0);args["sink"]=vid(f.n-1);
  return {{"command","run"},{"operation","max-flow-min-cut"},{"graph",f.graph},{"parameters",args},{"backend",backend},{"device",backend=="cpp"?"cpu":"gpu"},{"gpu_device",device}};
}
json::object invoke(json::object input,const char* error=nullptr) {
  const auto result=json::parse(graphmine::runtime::request(json::serialize(input))).as_object();++calls;
  if(calls%500==0)std::cerr<<"Validated "<<calls<<" flow requests\n";
  if(error){check(result.contains("error")&&result.at("error").as_object().at("code")==error,"Wrong flow error: "+json::serialize(result));return result;}
  check(!result.contains("error"),"Native failure: "+json::serialize(result));return result;
}
Exact exact(const json::object& row,const char* key){const auto& value=row.at(std::string(key)+"_exact").as_object();return Exact(Integer(std::string(value.at("numerator").as_string())))/Integer(std::string(value.at("denominator").as_string()));}
void verify(const Fixture& f,bool unit,bool side,json::array limits={}) {
  struct Arc {int u,v;Exact capacity;json::value id;};std::vector<Arc> arcs;
  Exact total=0;std::vector<std::optional<Exact>> capacities(f.n);
  for(const auto& raw:limits){const auto& row=raw.as_object();capacities[f.vertex(row.at("vertex"))]=Exact(row.at("capacity").to_number<double>());}
  for(const auto& raw:f.graph.at("edges").as_array()){
    const auto& row=raw.as_object();const int u=f.vertex(row.at("source")),v=f.vertex(row.at("target"));
    const Exact capacity=unit?Exact(1):Exact(row.at("weight").to_number<double>());
    arcs.push_back({u,v,capacity,row.at("id")});if(u!=v){total+=capacity;if(!f.directed){arcs.push_back({v,u,capacity,row.at("id")});total+=capacity;}}
  }
  // Enumerate every split-network cut, independently of residual augmentation.
  std::optional<Exact> best;
  for(unsigned mask=0;mask<(1U<<(2*f.n));++mask){
    if(!(mask&1)||(mask&(1U<<(2*f.n-1))))continue;Exact cost=0;
    for(int v=0;v<f.n;++v)if((mask&(1U<<(2*v)))&&!(mask&(1U<<(2*v+1))))cost+=capacities[v].value_or(total+1);
    for(const auto& arc:arcs)if(arc.u!=arc.v&&(mask&(1U<<(2*arc.u+1)))&&!(mask&(1U<<(2*arc.v))))cost+=arc.capacity;
    if(!best||cost<*best)best=cost;
  }
  const auto output=invoke(request(f,{{"capacity_mode",unit?"unit_capacity":"edge_weight"},{"return_cut_side",side},{"vertex_capacities",limits}}));
  const auto& result=output.at("result").as_object();const auto value=exact(result,"max_flow_value");
  check(result.at("optimal").as_bool()&&value==*best&&exact(result,"min_cut_value")==value,"Flow differs from independent cut optimum");
  check(result.at("flows")==result.at("flow_assignment")&&exact(result,"flow_value")==value&&exact(result,"cut_capacity")==value,"Flow compatibility aliases disagree");
  std::vector<Exact> incoming(f.n,0),outgoing(f.n,0),flow(arcs.size());std::vector<bool> found(arcs.size(),false);
  const auto& rows=result.at("flow_assignment").as_array();check(rows.size()==arcs.size(),"Original edge flow assignments missing");
  for(const auto& raw:rows){const auto& row=raw.as_object();const auto u=f.vertex(row.at("source")),v=f.vertex(row.at("target"));std::size_t index=arcs.size();
    for(std::size_t i=0;i<arcs.size();++i)if(arcs[i].u==u&&arcs[i].v==v&&arcs[i].id==row.at("edge")){index=i;break;}
    check(index<arcs.size()&&!found[index],"Invalid or repeated original flow identity");found[index]=true;flow[index]=exact(row,"flow");
    check(flow[index]>=0&&flow[index]<=arcs[index].capacity&&exact(row,"capacity")==arcs[index].capacity,"Original capacity violated");
    if(u==v)check(flow[index]==0,"Self-loop carries flow");outgoing[u]+=flow[index];incoming[v]+=flow[index];
  }
  std::vector<std::vector<int>> residual(2*f.n);
  auto residual_arc=[&](int u,int v,const Exact& capacity,const Exact& amount){if(capacity>amount)residual[u].push_back(v);if(amount>0)residual[v].push_back(u);};
  for(int v=0;v<f.n;++v){
    const Exact expected=v==0?value:v==f.n-1?-value:Exact(0);check(outgoing[v]-incoming[v]==expected,"Flow conservation violated");
    const auto through=v==f.n-1?incoming[v]:outgoing[v];check(!capacities[v]||through<=*capacities[v],"Vertex capacity violated");
    residual_arc(2*v,2*v+1,capacities[v].value_or(total+1),through);
  }
  for(std::size_t i=0;i<arcs.size();++i)if(arcs[i].u!=arcs[i].v)residual_arc(2*arcs[i].u+1,2*arcs[i].v,arcs[i].capacity,flow[i]);
  std::vector<bool> seen(2*f.n,false);seen[0]=true;std::queue<int> queue;queue.push(0);
  while(!queue.empty()){auto u=queue.front();queue.pop();for(auto v:residual[u])if(!seen[v]){seen[v]=true;queue.push(v);}}
  check(!seen.back(),"Returned flow leaves an augmenting path");
  std::set<std::string> expected_edges,actual_edges;std::set<int> expected_vertices,actual_vertices;Exact cut=0;
  for(const auto& arc:arcs)if(arc.u!=arc.v&&seen[2*arc.u+1]&&!seen[2*arc.v]){expected_edges.insert(json::serialize(arc.id));cut+=arc.capacity;}
  for(int v=0;v<f.n;++v)if(seen[2*v]&&!seen[2*v+1]){check(bool(capacities[v]),"Unbounded vertex cut");expected_vertices.insert(v);cut+=*capacities[v];}
  for(const auto& id:result.at("min_cut_edges").as_array())check(actual_edges.insert(json::serialize(id)).second,"Duplicate cut edge ID");
  for(const auto& id:result.at("min_cut_vertices").as_array())check(actual_vertices.insert(f.vertex(id)).second,"Duplicate cut vertex ID");
  check(actual_edges==expected_edges&&actual_vertices==expected_vertices&&cut==value,"Cut certificate is invalid");
  check(result.contains("source_side_vertices")==side&&output.at("ports").as_object().contains("vertices")==side,"Cut-side selection ignored");
  if(side){unsigned actual=0,desired=0;for(int v=0;v<f.n;++v)if(seen[2*v])desired|=1U<<v;for(const auto& id:result.at("source_side_vertices").as_array())actual|=1U<<f.vertex(id);check(actual==desired,"Incorrect source-side partition");
    const auto& split=result.at("split_source_side").as_array();check(split.size()==static_cast<unsigned>(f.n),"Incomplete split partition");
    for(const auto& raw:split){const auto& row=raw.as_object();const auto v=f.vertex(row.at("vertex"));check(row.at("input_reachable").as_bool()==seen[2*v]&&row.at("output_reachable").as_bool()==seen[2*v+1],"Wrong split-vertex reachability");}}
}
void integral(Fixture& f) { for (auto& raw:f.graph.at("edges").as_array()) raw.as_object()["weight"]=raw.as_object().at("weight").to_number<double>()*2; }
void gpu_contracts(){
  Fixture f(3,true,63);integral(f);auto input=request(f);
  input.at("parameters").as_object()["sink"]=vid(0);invoke(input,"invalid_input");
  for(const auto key:{"unknown","capacity_mode","solution_quality","return_cut_side"}){input=request(f);input.at("parameters").as_object()[key]=13;invoke(input,"invalid_input");}
  for(const auto key:{"max_candidates","max_output_items"}){input=request(f);input["budget"]=json::object{{key,1}};invoke(input,"resource_limit");}
  input=request(f);input["budget"]=json::object{{"timeout_seconds",1e-12}};invoke(input,"resource_limit");
}
void gpu_boundaries(){
  Fixture f(3,true,63);integral(f);
  for(const auto weight:{0.5,1000000001.0}){
    auto copy=f;copy.graph.at("edges").as_array()[0].as_object()["weight"]=weight;auto input=request(copy);invoke(input,"unsupported_input");
    input["device"]="auto";input["backend"]="auto";auto output=invoke(input);check(output.at("backend").as_object().at("id")=="cpp","Unsafe flow was not routed to CPU");
  }
  auto input=request(f,{{"vertex_capacities",json::array{json::object{{"vertex",vid(1)},{"capacity",1}}}}});invoke(input,"unsupported_input");input["device"]="auto";input["backend"]="auto";check(invoke(input).at("backend").as_object().at("id")=="cpp","Vertex capacity was not routed to CPU");
  for(bool directed:{false,true}){Fixture empty(3,directed,0);verify(empty,false,true);Fixture zeros(3,directed,63);for(auto& raw:zeros.graph.at("edges").as_array())raw.as_object()["weight"]=0;verify(zeros,false,true);}
  Fixture limit(2,true,0);limit.graph["edges"]=json::array{json::object{{"id","limit"},{"source",vid(0)},{"target",vid(1)},{"weight",1000000000}}};verify(limit,false,true);
  const unsigned n=20000;json::array vertices,edges;for(unsigned v=0;v<n;++v)vertices.push_back(json::object{{"id",v}});
  for(unsigned v=0;v+1<n;++v)edges.push_back(json::object{{"id",v},{"source",v},{"target",v+1},{"weight",1}});
  input=request(f);input["graph"]=json::object{{"graph",{{"id","deep-gpu-flow"},{"directed",true},{"allows_self_loops",false},{"allows_parallel_edges",false}}},{"vertices",vertices},{"edges",edges}};input["parameters"]=json::object{{"source",0},{"sink",n-1}};
  check(exact(invoke(input).at("result").as_object(),"max_flow_value")==1,"Deep GPU path flow incorrect");
}
void contracts(){
  Fixture f(3,true,63);auto input=request(f);input.at("parameters").as_object()["sink"]=vid(0);invoke(input,"invalid_input");
  input=request(f);input.at("parameters").as_object()["source"]="unknown";invoke(input,"invalid_input");
  for(const auto key:{"unknown","capacity_mode","solution_quality","return_cut_side"}){input=request(f);input.at("parameters").as_object()[key]=13;invoke(input,"invalid_input");}
  input=request(f);input.at("graph").as_object().at("edges").as_array()[0].as_object().erase("weight");invoke(input,"invalid_input");
  input=request(f);input.at("graph").as_object().at("edges").as_array()[0].as_object()["weight"]=-1;invoke(input,"invalid_input");
  for(const auto capacities:{json::value(json::object{}),json::value(json::array{json::object{{"vertex",vid(0)},{"capacity",-1}}}),json::value(json::array{json::object{{"vertex",vid(0)},{"capacity",true}}}),json::value(json::array{json::object{{"vertex","unknown"},{"capacity",1}}}),json::value(json::array{json::object{{"vertex",vid(0)},{"capacity",1}},json::object{{"vertex",vid(0)},{"capacity",1}}})}){input=request(f,{{"vertex_capacities",capacities}});invoke(input,"invalid_input");}
  for(const auto key:{"max_candidates","max_output_items"}){input=request(f);input["budget"]=json::object{{key,1}};invoke(input,"resource_limit");}
  input=request(f);input["budget"]=json::object{{"timeout_seconds",1e-12}};invoke(input,"resource_limit");
}
void boundaries(){
  for(const auto weights:{std::vector<double>{1e308,1e308,1e308,1e308},std::vector<double>{9007199254740992.0,1,9007199254740992.0,2},std::vector<double>{std::numeric_limits<double>::denorm_min(),1,1,std::numeric_limits<double>::denorm_min()}}){
    Fixture f(4,true,0);json::array edges;const std::vector<std::pair<int,int>> pairs{{0,1},{1,3},{0,2},{2,3}};
    for(unsigned i=0;i<pairs.size();++i)edges.push_back(json::object{{"id",eid(i)},{"source",vid(pairs[i].first)},{"target",vid(pairs[i].second)},{"weight",weights[i]}});
    f.graph["edges"]=edges;verify(f,false,true);verify(f,false,false,{{{"vertex",vid(0)},{"capacity",1}}});
  }
  Fixture f(2,true,0);verify(f,false,true);verify(f,false,false);
  const unsigned n=20000;json::array vertices,edges;for(unsigned v=0;v<n;++v)vertices.push_back(json::object{{"id",v}});
  for(unsigned v=0;v+1<n;++v)edges.push_back(json::object{{"id",v},{"source",v},{"target",v+1},{"weight",1}});
  auto input=request(f);input["graph"]=json::object{{"graph",{{"id","deep-flow"},{"directed",true},{"allows_self_loops",false},{"allows_parallel_edges",false}}},{"vertices",vertices},{"edges",edges}};
  for(bool limited:{false,true}){input["parameters"]=json::object{{"source",0},{"sink",n-1}};if(limited)input.at("parameters").as_object()["vertex_capacities"]=json::array{json::object{{"vertex",n/2},{"capacity",0.5}}};
    const auto output=invoke(input);const auto& result=output.at("result").as_object();check(exact(result,"max_flow_value")== (limited?Exact(1)/2:Exact(1)),"Deep path flow incorrect");check(result.at("flow_assignment").as_array().size()==n-1,"Deep path lost original flows");
    if(limited)check(result.at("min_cut_vertices")==json::array{n/2},"Deep path has wrong limiting vertex");}
}
}
int main(int argc,char** argv){try{
  const std::string suite=argc>1?argv[1]:"edges"; backend=argc>2?argv[2]:"cpp"; device=argc>3?std::stoi(argv[3]):0;
  if(suite=="contracts"){if(backend=="cpp")contracts();else gpu_contracts();}else if(suite=="boundaries"){if(backend=="cpp")boundaries();else gpu_boundaries();}
  else if(suite=="edges"){
    if(backend!="cpp") {
      for(unsigned mask=0;mask<64;++mask)for(bool unit:{false,true})for(bool side:{false,true}){Fixture f(3,true,mask);integral(f);verify(f,unit,side);}
      for(unsigned mask=0;mask<729;++mask){Fixture f(3,true,mask,3);integral(f);verify(f,false,true);}
      for(unsigned mask=0;mask<64;++mask){Fixture f(4,false,mask);integral(f);verify(f,false,true);}
    } else {
    for(bool directed:{false,true})for(unsigned mask=0;mask<(directed?4096U:64U);++mask)for(bool unit:{false,true})for(bool side:{false,true})verify(Fixture(4,directed,mask),unit,side);
    for(unsigned mask=0;mask<729;++mask)verify(Fixture(3,true,mask,3),false,true);
    }
  }else if(suite=="vertices"){
    for(unsigned mask=0;mask<64;++mask)for(unsigned code=0;code<64;++code){json::array limits;unsigned digits=code;for(int v=0;v<3;++v){auto digit=digits%4;digits/=4;if(digit)limits.push_back(json::object{{"vertex",vid(v)},{"capacity",(digit-1)*0.5}});}verify(Fixture(3,true,mask),false,true,limits);verify(Fixture(3,false,mask%8),true,false,limits);}
  }else throw std::runtime_error("Unknown flow suite");
  const auto catalog=json::parse(graphmine::runtime::request("{\"command\":\"catalog\"}")).as_object();std::cout<<json::serialize(json::object{{"suite",suite},{"backend",backend},{"gpu_device",backend=="cpp"?json::value(nullptr):json::value(device)},{"passed_requests",calls},{"failed",0},{"implementation_sha256",catalog.at("implementation_sha256")}})<<'\n';return 0;
}catch(const std::exception& error){std::cerr<<"Flow oracle failed after "<<calls<<" requests: "<<error.what()<<'\n';return 1;}}
