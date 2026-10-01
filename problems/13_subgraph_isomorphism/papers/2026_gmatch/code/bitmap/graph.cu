#include "graph.h"

#ifdef GRAPHMINE_LIBRARY
Graph::Graph(const std::vector<std::vector<int>> &adjacency,
             const std::vector<int> &labels) {
    if (adjacency.size() != labels.size()) {
        throw std::invalid_argument("gMatch adjacency/label size mismatch");
    }
    vcount_ = static_cast<int>(adjacency.size());
    ecount_ = 0;
    adj_ = adjacency;
    deg_.resize(vcount_);
    vertex_label_ = labels;
    nlf_.resize(vcount_);
    for (int vertex = 0; vertex < vcount_; ++vertex) {
        std::sort(adj_[vertex].begin(), adj_[vertex].end());
        deg_[vertex] = static_cast<int>(adj_[vertex].size());
        ecount_ += deg_[vertex];
        label_vertex_mapping_[vertex_label_[vertex]].push_back(vertex);
    }
    ecount_ /= 2;
    for (int vertex = 0; vertex < vcount_; ++vertex) {
        for (const auto neighbor : adj_[vertex]) {
            nlf_[vertex][vertex_label_[neighbor]]++;
        }
    }
}

Graph::Graph(const Graph &original,
             const std::vector<int> &matching_order) {
    if (matching_order.size() != static_cast<std::size_t>(original.vcount_)) {
        throw std::invalid_argument("gMatch matching-order size mismatch");
    }
    vcount_ = original.vcount_;
    ecount_ = original.ecount_;
    adj_.resize(vcount_);
    deg_.resize(vcount_);
    vertex_label_.resize(vcount_);
    nlf_.resize(vcount_);
    std::vector<int> rename(vcount_);
    for (int renamed = 0; renamed < vcount_; ++renamed) {
        rename[matching_order[renamed]] = renamed;
    }
    for (int renamed = 0; renamed < vcount_; ++renamed) {
        const auto old = matching_order[renamed];
        vertex_label_[renamed] = original.vertex_label_[old];
        deg_[renamed] = original.deg_[old];
        label_vertex_mapping_[vertex_label_[renamed]].push_back(renamed);
        for (const auto old_neighbor : original.adj_[old]) {
            adj_[renamed].push_back(rename[old_neighbor]);
        }
        std::sort(adj_[renamed].begin(), adj_[renamed].end());
    }
    for (int vertex = 0; vertex < vcount_; ++vertex) {
        for (const auto neighbor : adj_[vertex]) {
            nlf_[vertex][vertex_label_[neighbor]]++;
        }
    }
    generate_backward_neighborhood();
}
#endif

void
Graph::generate_bfs_order(std::vector<int> &bfs_order, int start) const {
    std::queue<int> Q;
    std::vector<int> visited(vcount_, 0);
    Q.push(start);
    visited[start] = 1;
    bfs_order.push_back(start);

    while (!Q.empty()) {
        int v = Q.front();
        Q.pop();
        for (int vv : adj_[v]) {
            if (visited[vv] == 0) {
                Q.push(vv);
                visited[vv] = 1;
                bfs_order.push_back(vv);
            }
        }
    }
}

void
Graph::generate_matching_order(std::vector<int> &matching_order) const {
    int n = vcount_;
    std::vector<bool> visited(n, false);

    int selected_vertex = 0;
    int selected_vertex_selectivity = deg_[selected_vertex];

    for (int u = 1; u < n; ++u) {
        int u_selectivity = deg_[u];
        if (u_selectivity > selected_vertex_selectivity) {
            selected_vertex = u;
            selected_vertex_selectivity = u_selectivity;
        }
    }

    matching_order.push_back(selected_vertex);
    visited[selected_vertex] = true;

    std::vector<int> tie_vertices;
    std::vector<int> temp;

    for (int _i = 1; _i < n; ++_i) {
        selected_vertex_selectivity = 0;
        for (int u = 0; u < n; ++u) {
            if (!visited[u]) {
                int u_selectivity = 0;
                for (auto uu : matching_order) {
                    if (is_adjacent(u, uu)) {
                        u_selectivity += 1;
                    }
                }
                if (u_selectivity > selected_vertex_selectivity) {
                    selected_vertex_selectivity = u_selectivity;
                    tie_vertices.clear();
                    tie_vertices.push_back(u);
                }
                else if (u_selectivity == selected_vertex_selectivity) {
                    tie_vertices.push_back(u);
                }
            }
        }

        if (tie_vertices.size() != 1) {
            temp.swap(tie_vertices);
            tie_vertices.clear();

            int count = 0;
            std::vector<int> u_fn;
            for (auto u : temp) {
                for (auto uu : adj_[u]) {
                    if (!visited[uu]) {
                        u_fn.push_back(uu);
                    }
                }

                int cur_count = 0;
                for (auto uu : matching_order) {
                    auto &uun = adj_[uu];
                    std::vector<int> uun_tmp;
                    uun_tmp.insert(uun_tmp.end(), uun.begin(), uun.end());

                    int common_neighbor_count = 0;
                    for (int ii : uun_tmp) {
                        for (int jj : u_fn) {
                            if (ii == jj) {
                                common_neighbor_count++;
                                break;
                            }
                        }
                        if (common_neighbor_count != 0) {
                            break;
                        }
                    }

                    if (common_neighbor_count > 0) {
                        cur_count += 1;
                    }
                }

                u_fn.clear();

                if (cur_count > count) {
                    count = cur_count;
                    tie_vertices.clear();
                    tie_vertices.push_back(u);
                }
                else if (cur_count == count) {
                    tie_vertices.push_back(u);
                }
            }
        }

        if (tie_vertices.size() != 1) {
            temp.swap(tie_vertices);
            tie_vertices.clear();

            int count = 0;
            std::vector<int> u_fn;
            for (auto u : temp) {
                for (auto uu : adj_[u]) {
                    if (!visited[uu]) {
                        u_fn.push_back(uu);
                    }
                }

                int cur_count = 0;
                for (auto uu : u_fn) {
                    bool valid = true;
                    for (auto uuu : matching_order) {
                        if (is_adjacent(uu, uuu)) {
                            valid = false;
                            break;
                        }
                    }
                    if (valid) {
                        cur_count += 1;
                    }
                }

                u_fn.clear();

                if (cur_count > count) {
                    count = cur_count;
                    tie_vertices.clear();
                    tie_vertices.push_back(u);
                }
                else if (cur_count == count) {
                    tie_vertices.push_back(u);
                }
            }
        }

        matching_order.push_back(tie_vertices[0]);
        visited[tie_vertices[0]] = true;
        tie_vertices.clear();
        temp.clear();
    }

    std::cout << "Matching order: ";
    for (auto v : matching_order) {
        std::cout << v << " ";
    }
    std::cout << std::endl;
}


Graph::Graph(const std::string &file_path) {
    std::ifstream infile(file_path);
    if (!infile.is_open()) {
        std::cout << "Cannot open graph file " << file_path << "." << std::endl;
        exit(-1);
    }

    char type = 0;
    infile >> type >> vcount_ >> ecount_;

    adj_.resize(vcount_);
    deg_.resize(vcount_);
    vertex_label_.resize(vcount_);
    nlf_.resize(vcount_);

    while (infile >> type) {
        if (type == 'v') {
            int vid, label, deg;
            infile >> vid >> label >> deg;
            vertex_label_[vid] = label;
            deg_[vid] = deg;
            label_vertex_mapping_[label].emplace_back(vid);
        }
        else {
            break;
        }
    }

    if (type == 'e') {
        std::string next_str;
        while (true) {
            int v1, v2;
            infile >> v1 >> v2;

            adj_[v1].emplace_back(v2);
            adj_[v2].emplace_back(v1);

            nlf_[v1][vertex_label_[v2]]++;
            nlf_[v2][vertex_label_[v1]]++;

            if (!(infile >> next_str)) {
                break;
            }
            if (next_str == "e") {
                continue;
            }
            else if (!(infile >> next_str)) {
                break;
            }
        }
    }

    infile.close();

    for (int v = 0; v < vcount_; v++) {
        if (adj_[v].size() != deg_[v]) {
            std::cout << "Degree Error: ";
            std::cout << v << ", " << adj_[v].size() << " != " << deg_[v] << std::endl;
        }
    }

    for (auto &l : adj_) {
        std::sort(l.begin(), l.end());
    }

    std::cout << "Graph loaded from file " << file_path << "." << std::endl;

    print_meta();
}


Graph::Graph(const std::string &file_path, std::vector<int> &matching_order) {
    std::vector<int> rename(matching_order.size());
    for (int i = 0; i < matching_order.size(); i++) {
        rename[matching_order[i]] = i;
    }

    std::ifstream infile(file_path);
    if (!infile.is_open()) {
        std::cout << "Cannot open graph file " << file_path << "." << std::endl;
        exit(-1);
    }

    char type = 0;
    infile >> type >> vcount_ >> ecount_;

    adj_.resize(vcount_);
    deg_.resize(vcount_);
    vertex_label_.resize(vcount_);
    nlf_.resize(vcount_);

    while (infile >> type) {
        if (type == 'v') {
            int vid, label, deg;
            infile >> vid >> label >> deg;

            vid = rename[vid];

            vertex_label_[vid] = label;
            deg_[vid] = deg;
            label_vertex_mapping_[label].emplace_back(vid);
        }
        else {
            break;
        }
    }

    if (type == 'e') {
        std::string next_str;
        while (true) {
            int v1, v2;
            infile >> v1 >> v2;

            v1 = rename[v1];
            v2 = rename[v2];

            adj_[v1].emplace_back(v2);
            adj_[v2].emplace_back(v1);

            nlf_[v1][vertex_label_[v2]]++;
            nlf_[v2][vertex_label_[v1]]++;

            if (!(infile >> next_str)) {
                break;
            }
            if (next_str == "e") {
                continue;
            }
            else if (!(infile >> next_str)) {
                break;
            }
        }
    }

    infile.close();

    for (int v = 0; v < vcount_; v++) {
        if (adj_[v].size() != deg_[v]) {
            std::cout << "Degree Error: ";
            std::cout << v << ", " << adj_[v].size() << " != " << deg_[v] << std::endl;
        }
    }

    for (auto &l : adj_) {
        std::sort(l.begin(), l.end());
    }

    generate_backward_neighborhood();

    std::cout << "Query vertices are renamed according to the matching order." << std::endl;
}


int
Graph::find_automorphisms(std::vector<std::vector<uint32_t>> &embeddings) const {
    // Note that this method is working on small graphs (tens of vertices) only.

    // This method conducts subgraph matching from Q to Q.
    std::vector<bool> visited(vcount_, false);
    std::vector<uint32_t> idx(vcount_);
    std::vector<uint32_t> mapping(vcount_);
    std::vector<std::vector<uint32_t>> local_candidates(vcount_);
    std::vector<std::vector<uint32_t>> global_candidates(vcount_);
    std::vector<std::vector<uint32_t>> backward_neighbors(vcount_);

    // Initialize global candidates.
    for (uint32_t u = 0; u < vcount_; u++) {
        uint32_t u_label = label(u);
        uint32_t u_degree = degree(u);

        for (uint32_t v = 0; v < vcount_; v++) {
            uint32_t v_label = label(v);
            uint32_t v_degree = degree(v);

            if (v_label == u_label && v_degree == u_degree) {
                global_candidates[u].push_back(v);
            }
        }
    }

    // Set backward neighbors to compute local candidates.
    for (uint32_t i = 1; i < vcount_; i++) {
        for (uint32_t j = 0; j < i; j++) {
            if (is_adjacent(i, j)) {
                backward_neighbors[i].push_back(j);
            }
        }
    }

    // Recursive search along the matching order (0, 1, ..., n).
    int cur_level = 0;
    local_candidates[cur_level] = global_candidates[0];

    while (true) {
        while (idx[cur_level] < local_candidates[cur_level].size()) {
            uint32_t u = cur_level;
            uint32_t v = local_candidates[cur_level][idx[cur_level]];
            idx[cur_level] += 1;

            if (cur_level == vcount_ - 1) {
                // Find an embedding
                mapping[u] = v;
                embeddings.push_back(mapping);
            }
            else {
                mapping[u] = v;
                visited[v] = true;
                cur_level += 1;
                idx[cur_level] = 0;

                {
                    // Compute local candidates.
                    u = cur_level;
                    for (auto temp_v : global_candidates[u]) {
                        if (!visited[temp_v]) {
                            bool is_feasible = true;
                            for (auto uu : backward_neighbors[u]) {
                                uint32_t temp_vv = mapping[uu];
                                if (!is_adjacent(temp_v, temp_vv)) {
                                    is_feasible = false;
                                    continue;
                                }
                            }
                            if (is_feasible) {
                                local_candidates[cur_level].push_back(temp_v);
                            }
                        }
                    }
                }
            }
        }

        local_candidates[cur_level].clear();
        cur_level -= 1;
        if (cur_level < 0) {
            break;
        }
        visited[mapping[cur_level]] = false;
    }

    std::cout << "Found " << embeddings.size() << " automorphisms of the query graph." << std::endl;
    return embeddings.size();
}


int
Graph::restriction_generation(std::vector<uint32_t> &partial_order) const {
    assert(vcount_ <= 32);

    std::vector<std::vector<uint32_t>> automorphisms;
    int alpha = find_automorphisms(automorphisms);

    bool relation[32][32];
    memset(relation, 0, sizeof(relation));

    for (int u = 0; u < vcount_; u++) {
        std::vector<std::vector<uint32_t>> stablized_aut;
        for (auto &m : automorphisms) {
            if (m[u] == u) {
                stablized_aut.emplace_back(m);
            }
            else {
                relation[u][m[u]] = 1;
                if (u > m[u]) {
                    printf("Error\n");
                    exit(-1);
                }
            }
        }
        automorphisms = stablized_aut;
    }

    // Find all path longer than 1
    bool M[32][32];

    // Compute R^2
    for (int u = 0; u < vcount_; u++) {
        for (int v = 0; v < vcount_; v++) {
            M[u][v] = 0;
            for (int w = 0; w < vcount_; w++) {
                if (relation[u][w] && relation[w][v]) {
                    M[u][v] = 1;
                    break;
                }
            }
        }
    }

    for (int k = 2; k < vcount_ - 1; k++) {
        for (int u = 0; u < vcount_; u++) {
            for (int v = 0; v < vcount_; v++) {
                if (M[u][v]) {
                    continue;
                }
                for (int w = 0; w < vcount_; w++) {
                    if ((relation[u][w] && M[w][v]) || (M[u][w] && relation[w][v])) {
                        M[u][v] = 1;
                        break;
                    }
                }
            }
        }
    }

    // Only save the Hasse Graph
    partial_order.resize(vcount_, 0);

    for (int u = 0; u < vcount_; u++) {
        for (int v = 0; v < vcount_; v++) {
            if (relation[u][v] && !M[u][v]) {
                partial_order[u] |= (1 << v);
                printf("%d -> %d\n", u, v);
            }
        }
    }

    return alpha;
}
