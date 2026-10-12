#include "graph.hpp"
#include <cassert>


void undirected_graph::create_csr(const std::vector<std::vector<int>>& adjlist) {
    vertices.push_back(edges.size());
    for (int i = 0; i < numVert; i++) {
        edges.insert(edges.end(), adjlist[i].begin(), adjlist[i].end());
        vertices.push_back(edges.size());
    }
}

undirected_graph::undirected_graph(const std::string& filename) {
    std::ifstream in(filename);

    if (!in) {
        std::cerr << "Unable to open file." << std::endl;
        return;
    }
    filepath = filename;
    readGraphFile();
}

void undirected_graph::readGraphFile() {
    if (!std::filesystem::exists(filepath)) {
        throw std::runtime_error("File does not exist: " + filepath.string());
    }

    std::string ext = filepath.extension().string();
    if (ext == ".edges" || ext == ".eg2" || ext == ".txt") {
        readEdgeList();
    }
    else if (ext == ".egr" || ext == ".bin" || ".csr") {
        readECLgraph();
    }
    else {
        throw std::runtime_error("Unsupported graph format: " + ext);
    }
}

void undirected_graph::readEdgeList() {
    std::ifstream in(filepath);
    if (!in) {
        throw std::runtime_error("Error opening file: ");
    }

    int u, v;
    in >> numVert >> numEdges;
    long ctr = 0;
    std::vector<std::vector<int>> adjlist(numVert);
    for (size_t i = 0; i < numEdges; ++i) {
        in >> u >> v;
        adjlist[u].push_back(v);
        if (u < v) {
            u_arr.push_back(u);
            v_arr.push_back(v);
            ctr++;
        }
    }
    assert(ctr == numEdges/2);

    numEdges = ctr;
    create_csr(adjlist);
}

void undirected_graph::readECLgraph() {
    std::ifstream inFile(filepath, std::ios::binary);
    if (!inFile) {
        throw std::runtime_error("Error opening file: ");
    }

    // Reading sizes
    size_t size;
    inFile.read(reinterpret_cast<char*>(&size), sizeof(size));
    vertices.resize(size);
    inFile.read(reinterpret_cast<char*>(&size), sizeof(size));
    edges.resize(size);

    // Reading data
    inFile.read(reinterpret_cast<char*>(vertices.data()), vertices.size() * sizeof(long));
    inFile.read(reinterpret_cast<char*>(edges.data()), edges.size() * sizeof(int));

    numVert = vertices.size() - 1;
    numEdges = edges.size();

    csr_to_coo();
}

void undirected_graph::csr_to_coo() {

    u_arr.reserve(numEdges/2);
    v_arr.reserve(numEdges/2);

    long ctr = 0;

    for (int i = 0; i < numVert; ++i) {
        for (long j = vertices[i]; j < vertices[i + 1]; ++j) {
            if(i < edges[j]) {
                u_arr.push_back(i);
                v_arr.push_back(edges[j]);
                ctr++;
            }
        }
    }    

    assert(ctr == numEdges/2);

    long max_degree = 0;
    max_degree_vert = -1;
    avg_out_degree = 0.0;
    for (int i = 0; i < numVert; ++i) {
        long degree = vertices[i+1] - vertices[i];
        avg_out_degree += (double)degree;
        if (degree > max_degree) {
            max_degree = degree;
            max_degree_vert = i;
        }
    }
    avg_out_degree /= (double)numVert;
    
    assert(max_degree_vert >= 0);
    assert(avg_out_degree >= 0.0);
}