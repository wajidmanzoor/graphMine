#include <bits/stdc++.h>
#include <omp.h>

using namespace std;

void process_file(char* file_name) {
    FILE* file = fopen(file_name, "r");
    std::stringstream ss;
    if (file == NULL) {
        ss << "Error: Unable to open file: " << file_name << endl;
        cerr << ss.str();
        exit(1);
    }

    // Read in edges (x,y,t) and find the number of static undirected edges
    int x, y, t;
    unordered_map< int, unordered_set<int> > edges;
    size_t num_edges = 0;
    while (fscanf(file, "%i %i %i", &x, &y, &t) != EOF) {
        num_edges++;
        if (x < 0 || y < 0 || t < 0) {
            ss << "Error: Invalid edge #" << num_edges << ": "
                << x << " " << y << " " << t << endl;
            cerr << ss.str();
            exit(1);
        }
        if (x > y) swap(x, y);
        edges[x].insert(y);
        
        auto it = edges.find(y);
        if (it == edges.end()) {
            edges[y] = unordered_set<int>();
        }
    }

    size_t num_static_edges = 0;
    for (auto it = edges.begin(); it != edges.end(); it++) {
        num_static_edges += it->second.size();
    }

    ss << "File: " << file_name;
    ss << "\nNumber of edges: " << num_edges;
    ss << "\nNumber of nodes: " << edges.size();
    ss << "\nNumber of static edges: " << num_static_edges;
    ss << endl;
    cout << ss.str();
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        cout << "Usage: ./find_num_static_edges <input_files>" << endl;
        return 1;
    }

    cout << "Number of input files: " << argc - 1 << endl;
    for (int i = 1; i < argc; i++) {
        cout << "Input file #" << i << ": " << argv[i] << endl;
    }

    omp_set_num_threads(argc - 1);

    #pragma omp parallel for schedule(dynamic, 1)
    for (int i = 1; i < argc; i++) {
        process_file(argv[i]);
    }

    return 0;

}
