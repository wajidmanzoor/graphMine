import numpy as np
import scipy.sparse as sp
from scipy.linalg import eigh
from scipy.sparse.linalg import eigs, eigsh, svds
from scipy.sparse import coo_matrix
from models import HyperData
import torch
import os
from typing import Tuple
import subprocess
from config import paths
import easypart as easypart
import kahypar as kahypar

def basic_randomized_svds(X, k, q=5, s=10):
    m, n = X.shape
    if k + s > min(m, n):
        raise ValueError("k + s must be less than or equal to the minimum dimension of X")
    Omega = np.random.randn(n, k + s)
    Y = X @ Omega
    Q, _ = np.linalg.qr(Y)
    for i in range(q):
        T, _ = np.linalg.qr(X.T @ Q)
        Q, _ = np.linalg.qr(X @ T)
    B = Q.T @ X
    U_hat, S_hat, V_hat_T = np.linalg.svd(B, full_matrices=False)
    U = Q @ U_hat[:, :k]
    Sigma = S_hat[:k]
    V = V_hat_T[:k, :].T
    return U, Sigma, V

def generate_sparse_sign_matrix(n, h, z):
    S = np.zeros((n, h), dtype=np.int8)
    for j in range(h):
        indices = np.random.choice(n, size=z, replace=False)
        signs = np.random.choice([-1, 1], size=z)
        S[indices, j] = signs
    return S

def randomized_svds_with_sparse_matrix(X, k, q=5, s=10):
    m, n = X.shape
    if k + s > min(m, n):
        raise ValueError("k + s must be less than or equal to the minimum dimension of X")
    h = k + s
    z = min(8, n)
    Omega = generate_sparse_sign_matrix(n, h, z)
    Y = X @ Omega
    Q, _ = np.linalg.qr(Y)
    for i in range(q):
        T, _ = np.linalg.qr(X.T @ Q)
        Q, _ = np.linalg.qr(X @ T)
    B = Q.T @ X
    U_hat, S_hat, V_hat_T = np.linalg.svd(B, full_matrices=False)
    U = Q @ U_hat[:, :k]
    Sigma = S_hat[:k]
    V = V_hat_T[:k, :].T
    return U, Sigma, V

def eigSVD(A):
    lamb, X = eigh(A.T @ A)
    idx = np.argsort(lamb)[::-1]
    lamb = lamb[idx]
    V = X[:, idx]
    pos = lamb > 1e-10
    lamb = lamb[pos]
    V = V[:, pos]
    S = np.sqrt(lamb)
    U = (A @ V) / S
    return U, S, V

def freigs(A, k, q=5, s=10):
    n = A.shape[0]
    Omega = np.random.randn(n, k + s)
    Y = A @ Omega
    Q, _, _ = eigSVD(Y)
    for i in range(q):
        Q, _, _ = eigSVD(A @ (A @ Q))
    S = Q.T @ (A @ Q)
    Lambda, U_tilde = eigh(S)
    idx = np.argsort(Lambda)[::-1][:k]
    Lambda = Lambda[idx]
    U_tilde = U_tilde[:, idx]
    U = Q @ U_tilde
    return Lambda, U

def create_clique_expansion_graph(hypergraph_vertices, hypergraph_edges) -> Tuple[coo_matrix, np.ndarray, np.ndarray]:
    node_degree = np.zeros(len(hypergraph_vertices))
    pin_count = np.zeros(len(hypergraph_vertices))
    edge_dict = {}
    for edge in hypergraph_edges:
        for i in range(len(edge)):
            for j in range(i + 1, len(edge)):
                node_pair = (edge[i], edge[j])
                node_pair_reversed = (edge[j], edge[i])
                weight = 1 / (len(edge) - 1)
                if node_pair in edge_dict:
                    edge_dict[node_pair] += weight
                    edge_dict[node_pair_reversed] += weight
                else:
                    edge_dict[node_pair] = weight
                    edge_dict[node_pair_reversed] = weight
            pin_count[edge[i]] += 1
    row = []
    col = []
    data = []
    for (i, j), weight in edge_dict.items():
        row.append(i)
        col.append(j)
        data.append(weight)
        node_degree[i] += 1
    num_nodes = len(hypergraph_vertices)
    adj_matrix = coo_matrix((data, (row, col)), shape=(num_nodes, num_nodes))
    return adj_matrix, node_degree, pin_count

def normalize_hypergraph_incidence_matrix(H: coo_matrix) -> coo_matrix:
    d_v = np.array(H.sum(axis=1)).flatten()
    d_e = np.array(H.sum(axis=0)).flatten()
    d_v_inv_sqrt = np.power(d_v, -0.5).flatten()
    d_e_inv_sqrt = np.power(d_e, -0.5).flatten()
    d_v_inv_sqrt[np.isinf(d_v_inv_sqrt)] = 0.
    d_e_inv_sqrt[np.isinf(d_e_inv_sqrt)] = 0.
    d_v_mat_inv_sqrt = sp.diags(d_v_inv_sqrt)
    d_e_mat_inv_sqrt = sp.diags(d_e_inv_sqrt)
    return (d_v_mat_inv_sqrt @ H @ d_e_mat_inv_sqrt).tocoo()

def normalize_adj(adj: coo_matrix) -> coo_matrix:
    rowsum = np.array(adj.sum(1))
    d_inv_sqrt = np.power(rowsum, -0.5).flatten()
    d_inv_sqrt[np.isinf(d_inv_sqrt)] = 0.
    d_mat_inv_sqrt = sp.diags(d_inv_sqrt)
    return adj.dot(d_mat_inv_sqrt).transpose().dot(d_mat_inv_sqrt).tocoo()

def compute_topological_features(adj_matrix: coo_matrix, d: int, adj_normalize: bool, feature_abs: bool, use_sketch: bool) -> np.ndarray:
    # rowsum = np.array(adj_matrix.sum(1)).squeeze(1)
    # data = -adj_matrix.data
    # laplace_data = np.concatenate((data, rowsum))
    # diag = np.arange(len(rowsum))
    # laplace = coo_matrix((laplace_data, (np.concatenate((adj_matrix.row, diag)), np.concatenate((adj_matrix.col, diag)))), shape=(len(rowsum), len(rowsum)))
    if adj_normalize:
       adj_matrix = normalize_adj(adj_matrix)
    lamb, X = eigsh(adj_matrix, d) if not use_sketch else freigs(adj_matrix, d, 5)
    X = X[:, np.argsort(lamb)]
    if feature_abs:
        X = np.abs(X)
    else:
        for i in range(X.shape[1]):    
            if X[np.argmax(np.absolute(X[:,i])),i] < 0:
                X[:,i] = -X[:,i]
    return X

def create_partition_id_feature(num_nodes, filename):
    partition_feature = []
    hmetis_path = paths.get_exec_path('hmetis2.0pre1')
    data_file_path = paths.get_data_path(filename)
    partition_file_path = paths.get_partition_file_path(filename)
    os.system(f'{hmetis_path} {data_file_path} 2 -ufactor=2 -ptype=rb -otype=cut -nruns=1 -seed=42 > /dev/null')
    with open(partition_file_path, 'r') as f:
        for line in f:
            partition_id = int(line.strip())
            partition_feature.append(partition_id)
    os.system(f'rm {partition_file_path}')
    if len(partition_feature) != num_nodes:
        print('Partition feature length does not match number of nodes!')
    partition_feature = np.array(partition_feature)
    return partition_feature

def preprocess_data(hypergraph_vertices, hypergraph_edges, filename, num_nodes, num_nets, use_sketch=False):
    adj_matrix, node_degree, pin_count = create_clique_expansion_graph(hypergraph_vertices, hypergraph_edges)
    clique_topo_features = compute_topological_features(adj_matrix, 2, True, False, use_sketch)
    row, col, value = [], [], []
    for i, e in enumerate(hypergraph_edges):
        for v in e:
            row.append(v)
            col.append(i)
            value.append(1)
    H = coo_matrix((value, (row, col)), shape=(num_nodes, num_nets), dtype=float)
    H = normalize_hypergraph_incidence_matrix(H)
    U, S, Vt = svds(H, k=2, which='LM', random_state=42, solver='propack', maxiter=10000) if not use_sketch else basic_randomized_svds(H, 2, 5)
    U = U[:, np.argsort(S)[::-1]]
    for i in range(U.shape[1]):    
        if U[np.argmax(np.absolute(U[:,i])),i] < 0:
            U[:,i] = -U[:,i]
    star_topo_features = torch.tensor(U.copy(), dtype=torch.float)
    partition_feature = create_partition_id_feature(len(hypergraph_vertices), filename)
    features = np.column_stack([clique_topo_features, star_topo_features, node_degree, pin_count, partition_feature])
    del adj_matrix, node_degree, pin_count, clique_topo_features, star_topo_features, H, U, S, Vt
    deg_feature_norm = np.linalg.norm(features[:, 4])
    for i in [0, 1, 2, 3, 5, 6]:
        feature_norm = np.linalg.norm(features[:, i])
        if feature_norm > 1e-8:
            features[:, i] = features[:, i] / feature_norm * deg_feature_norm
        else:
            features[:, i] = 0.0
    hyperedge_index = torch.tensor(np.array([
        np.concatenate(hypergraph_edges),
        np.repeat(np.arange(len(hypergraph_edges)), [len(e) for e in hypergraph_edges])
    ]), dtype=torch.long)
    x = torch.tensor(features, dtype=torch.float)
    data = HyperData(x=x, hyperedge_index=hyperedge_index)
    return data, partition_feature

def evaluate_partition(partition: np.ndarray, hypergraph_vertices, hypergraph_edges, num_partitions):
    cut = 0
    partition_weights = np.zeros(num_partitions)
    for node in hypergraph_vertices:
        partition_id = int(partition[node])
        partition_weights[partition_id] += 1
    for edge in hypergraph_edges:
        edge_partitions = set()
        for node in edge:
            edge_partitions.add(partition[node])
        if len(edge_partitions) > 1:
            cut += 1
    imbalance = np.max((partition_weights - np.mean(partition_weights)) / np.mean(partition_weights))
    return cut, imbalance

def evalPoint(id: int, partition, hypergraph_vertices, hypergraph_edges, num_partitions, filename, use_easypart=True, use_kahypar=False):
    channel = subprocess.DEVNULL
    num_nodes = len(hypergraph_vertices)
    num_nets = len(hypergraph_edges)
    partition_file_with_id = paths.get_partition_file_with_id_path(filename, id)
    with open(partition_file_with_id, 'w') as f:
        for i in range(len(partition)):
            f.write(f'{partition[i]}\n')

    hyperedge_indices = []
    hyperedges = []
    index = 0
    for edge in hypergraph_edges:
        hyperedge_indices.append(index)
        index += len(edge)
        hyperedges.extend(edge)
    hyperedge_indices.append(index)

    if use_easypart:
        hypergraph = easypart.Graph(num_nodes, num_nets, hyperedge_indices, hyperedges)
        params = easypart.Params()
        params.epsilon = 0.02
        params.part_num = 2
        params.thread = 1
        easypart.partition(hypergraph, params, partition_file_with_id)
        # command = ['./exec/EasyPart', '-g', f'./data/{filename}', '-e', '0.04', '-p', '2', '-t', '1', '-m', 'quality', '-f', f'./data/{filename}.part.2.{id}', '-o', '1']
        # try:
        #     subprocess.run(command, shell=False, stdout=channel, stderr=channel)
        # except Exception:
        #     print(f"Error running EasyPart for {filename} with id {id}")

    if use_kahypar:
        hypergraph = kahypar.Hypergraph(num_nodes, num_nets, hyperedge_indices, hyperedges, num_partitions)
        context = kahypar.Context()
        context.loadINIconfiguration(paths.get_exec_path("cut_kKaHyPar_sea20.ini"))
        context.setK(num_partitions)
        context.setEpsilon(0.04)
        context.setInputPartitionFileName(partition_file_with_id)
        context.writePartitionFile(True)
        context.setPartitionFileName(partition_file_with_id)
        context.suppressOutput(True)
        kahypar.partition(hypergraph, context)
        # command = ['./exec/KaHyPar', '-h', f'./data/{filename}', '-k', '2', '-e', '0.04', '-o', 'cut', '-m', 'direct', '-p', './exec/cut_kKaHyPar_sea20.ini', '--part-file', f'./data/{filename}.part.2.{id}', '-w', '1']
        # try:
        #     subprocess.run(command, shell=False, stdout=channel, stderr=channel)
        # except Exception:
        #     pass

    partition_id = np.zeros(num_nodes)
    index = 0
    with open(partition_file_with_id, 'r') as f:
        for line in f:
            partition_id[index] = int(line.strip())
            index += 1
    command = ['rm', partition_file_with_id]
    try:
        # os.remove(f'./data/{filename}.part.2.{id}')
        subprocess.run(command, shell=False, stdout=channel, stderr=channel)
    except Exception:
        print(f"Error removing partition file for {filename} with id {id}")
    cut, imbalance = evaluate_partition(partition_id, hypergraph_vertices, hypergraph_edges, num_partitions)
    return cut, imbalance, partition_id
