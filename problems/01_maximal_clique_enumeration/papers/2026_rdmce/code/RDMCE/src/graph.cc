#include "graph.h"
inline void Graph::ApplyOrder(const vlist_t &order)
{
  assert(order.size() == num_vertices_);
  vlist_t order_rev(num_vertices_);
  for (vid_t v = 0; v < num_vertices_; v++)
    order_rev[order[v]] = v;

  std::vector<vlist_t> V_new(num_vertices_);
  for (vid_t v = 0; v < num_vertices_; v++)
  {
    V_new[v] = std::move(V_[order[v]]);
    for (auto &u : V_new[v])
      u = order_rev[u];
    std::sort(V_new[v].begin(), V_new[v].end());
  }
  std::swap(V_, V_new);
  V_new.clear();

  std::vector<vid_t> labels_new(num_vertices_);
  for (vid_t v = 0; v < num_vertices_; v++)
    labels_new[v] = labels_[order[v]];
  std::swap(labels_, labels_new);
  labels_new.clear();
}

Graph::Graph(const Graph &other)
{
  name_ = other.name_;
  V_.reserve(other.V_.size());
  for (const auto &vlist : other.V_) // deep copy
    V_.emplace_back(vlist.begin(), vlist.end());
  labels_.reserve(other.labels_.size());
  for (const auto &label : other.labels_)
    labels_.emplace_back(label);
  num_vertices_ = other.num_vertices_;
  num_edges_ = other.num_edges_;
  max_degree_ = other.max_degree_;
}

Graph::Graph(Graph &&other)
{
  name_ = other.name_;
  assert(V_.empty() && labels_.empty());
  V_ = std::move(other.V_);
  labels_ = std::move(other.labels_);
  num_vertices_ = other.num_vertices_;
  num_edges_ = other.num_edges_;
  max_degree_ = other.max_degree_;
}

Graph::~Graph()
{
  for (auto &vlist : V_)
    vlist.clear();
  V_.clear();
  labels_.clear();
  if(colidx_cpu_ != nullptr)
    delete[] colidx_cpu_;
  if(rowoffset_cpu_ != nullptr)
    delete[] rowoffset_cpu_;
}

void Graph::LoadFromFile(const std::string &path)
{
  std::ifstream fin(path);
  if (!fin.is_open())
  {
    std::cerr << "Error: Failed to open file " << path << std::endl;
    exit(1);
  }
  assert(V_.empty());
  name_ = ExtractName(path);

  std::vector<std::pair<vid_t, vid_t>> edges;
  std::string line;
  std::vector<bool> has_vertex;

  Timer t;
  t.Start();

  vid_t u, v;
  while (!fin.eof())
  {
    if (fin >> u >> v)
    {
      fin.ignore(std::numeric_limits<std::streamsize>::max(), '\n');
      if(u == v)
        continue;
      if(u > v)
        std::swap(u, v);
      edges.emplace_back(u, v);
      vid_t max_v = std::max(u, v);
      while (has_vertex.size() <= max_v)
        has_vertex.emplace_back(false);
      has_vertex[u] = true;
      has_vertex[v] = true;
    }
    else
    {
      fin.clear();
      fin.ignore(std::numeric_limits<std::streamsize>::max(), '\n');
    }
  }

  t.Stop();
  std::cout << "Read " << edges.size() << " edges in " << t.Elapsed() << " seconds" << std::endl;

  std::sort(edges.begin(), edges.end());
  auto last = std::unique(edges.begin(), edges.end());
  edges.erase(last, edges.end());
  num_edges_ = edges.size();

  // std::ofstream fout(path + ".sorted");
  // if (!fout.is_open()){
  //   std::cerr << "Error: Failed to open file " << path + ".sorted" << std::endl;
  //   exit(1);
  // }
  // for (auto [u, v] : edges)
  //   fout << u - 1 << " " << v - 1 << std::endl;
  // fout.close();

  vlist_t label_to_id(has_vertex.size());
  for (int i = 0; i < has_vertex.size(); i++)
    if (has_vertex[i])
    {
      label_to_id[i] = labels_.size();
      labels_.emplace_back(i);
    }
  num_vertices_ = labels_.size();
  num_edges_ = edges.size();
  V_.resize(num_vertices_);
  max_degree_ = 0;

  for (auto [x, y] : edges)
  {
    x = label_to_id[x];
    y = label_to_id[y];
    if(!V_[x].empty() && V_[x].back() == y)
      num_edges_--;
    else{
      V_[x].emplace_back(y);
      V_[y].emplace_back(x);
    }
  }

  for (auto &vlist : V_)
    max_degree_ = std::max(max_degree_, vlist.size());
  degeneracy_ = max_degree_;
  edges.clear();
  has_vertex.clear();
}

void Graph::StoreIntoBin(const std::string &path){
  size_t dotPos = path.find_last_of(".");
  std::ofstream fout(path.substr(0, dotPos) + ".bin", std::ios::binary);  

  if (!fout.is_open())
  {
    std::cerr << "Error: Failed to open file " << name_ + ".bin" << std::endl;
    exit(1);
  }
  fout.write((char *)&num_vertices_, sizeof(num_vertices_));
  fout.write((char *)&num_edges_, sizeof(num_edges_));
  fout.write((char *)&max_degree_, sizeof(max_degree_));
  fout.write((char *)&degeneracy_, sizeof(degeneracy_));
  for (auto &vlist : V_){
    size_t size = vlist.size();
    fout.write((char *)&size, sizeof(size));
    for (auto &v : vlist)
      fout.write((char *)&v, sizeof(v));   
  }
  for (auto &label : labels_)
    fout.write((char *)&label, sizeof(label));
  fout.close();
}

void Graph::LoadFromBin(const std::string &path){
  std::ifstream fin(path, std::ios::binary);
  if (!fin.is_open())
  {
    std::cerr << "Error: Failed to open file " << path << std::endl;
    exit(1);
  }
  fin.read((char *)&num_vertices_, sizeof(num_vertices_));
  fin.read((char *)&num_edges_, sizeof(num_edges_));
  fin.read((char *)&max_degree_, sizeof(max_degree_));
  fin.read((char *)&degeneracy_, sizeof(degeneracy_));
  V_.resize(num_vertices_);
  labels_.resize(num_vertices_);
  for (auto &vlist : V_){
    size_t size;
    fin.read((char *)&size, sizeof(size));
    vlist.resize(size);
    fin.read((char *)&vlist[0], sizeof(vlist[0]) * size);
  }
  fin.read((char *)&labels_[0], sizeof(labels_[0]) * num_vertices_);
  fin.close();

  // std::ofstream fout(path + ".sorted");
  // if (!fout.is_open()){
  //   std::cerr << "Error: Failed to open file " << path + ".sorted" << std::endl;
  //   exit(1);
  // }

  // for(vid_t v = 0; v < num_vertices_; v++){
  //   for(auto &u : V_[v])
  //     if(v < u)
  //       fout << v << " " << u << std::endl;
  // }

  // fout.close();
}


void Graph::ConvertToCsr(){
  if(rowoffset_cpu_ != nullptr)
    delete[] rowoffset_cpu_;
  if(colidx_cpu_ != nullptr)
    delete[] colidx_cpu_;
  rowoffset_cpu_ = new vid_t[num_vertices_ + 1];
  colidx_cpu_ = new vid_t[num_edges_ * 2];
  vid_t edge_cpu = 0;
  for (vid_t i = 0; i < num_vertices_; i++)
  {
    rowoffset_cpu_[i] = edge_cpu;
    for (vid_t j = 0; j < N(i).size(); j++)
    {
      // rowidx_cpu[edge_cpu] = i;
      colidx_cpu_[edge_cpu] = N(i)[j];
      edge_cpu++;
    }
  }
  rowoffset_cpu_[num_vertices_] = edge_cpu;
  assert(edge_cpu == num_edges_ * 2);
}




void Graph::SortByOrder(OrderType order)
{
  switch (order)
  {
  case OrderType::UNCHANGED:
    break;
  case OrderType::ASC:
    SortByDegreeAsc();
    break;
  case OrderType::DES:
    SortByDegreeDes();
    break;
  case OrderType::DEG:
    SortByDegeneracy();
    break;
  }
}

void Graph::SortByDegreeAsc()
{
  vlist_t order(num_vertices_);
  for (vid_t v = 0; v < num_vertices_; v++)
    order[v] = v;
  std::sort(order.begin(), order.end(), [&](vid_t v1, vid_t v2)
            { return V_[v1].size() < V_[v2].size(); });
  ApplyOrder(order);

  order.clear();
}

void Graph::SortByDegreeDes()
{
  vlist_t order(num_vertices_);
  for (vid_t v = 0; v < num_vertices_; v++)
    order[v] = v;
  std::sort(order.begin(), order.end(), [&](vid_t v1, vid_t v2)
            { return V_[v1].size() > V_[v2].size(); });
  ApplyOrder(order);
}

void Graph::SortByDegeneracy()
{
  vlist_t order;
  order.reserve(num_vertices_);
  std::vector<int> degree(num_vertices_);
  degeneracy_ = 0;
  for (vid_t v = 0; v < num_vertices_; v++)
    degree[v] = V_[v].size();
  while (order.size() < num_vertices_)
  {
    size_t cur_id = order.size();
    degeneracy_++;
    for (vid_t v = 0; v < num_vertices_; v++)
      if (degree[v] == degeneracy_)
        order.emplace_back(v);
    while (cur_id < order.size())
    {
      vid_t v = order[cur_id];
      cur_id++;
      for (auto &u : V_[v])
        if (--degree[u] == degeneracy_)
          order.emplace_back(u);
    }
  }
  ApplyOrder(order);
}

std::ostream &operator<<(std::ostream &os, const Graph &graph)
{
  os << "Graph: " << graph.name_ << std::endl;
  os << "|V|:" << graph.num_vertices_ << " ";
  os << "|E|:" << graph.num_edges_ << " ";
  os << "max_degree: " << graph.max_degree_ << std::endl
     << std::endl;

  for (vid_t v = 0; v < graph.num_vertices_; v++)
  {
    os << "v" << v << "(" << graph.labels_[v] << ")" << ": ";
    for (auto &u : graph.V_[v])
    {
      os << "v" << u << "(" << graph.labels_[u] << ") ";
    }
    os << std::endl;
  }

  return os;
}
