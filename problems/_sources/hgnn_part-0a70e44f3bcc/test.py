import argparse
import torch
import numpy as np
import time
import multiprocessing as mp
from transformers import set_seed
from utils import *
from models import GraphPartitionModel
from config import paths

paths.MODELS_DIR.mkdir(exist_ok=True)

if __name__ == '__main__':
    set_seed(42)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    parser = argparse.ArgumentParser()
    parser.add_argument('--filename', type=str, default='ibm02.hgr')
    parser.add_argument('--modelname', type=str, default='model.pt')
    parser.add_argument('--num_partitions', type=int, default=2)
    parser.add_argument('--latent_dim', type=int, default=64)
    parser.add_argument('--hidden_dim', type=int, default=256)
    parser.add_argument('--use_sketch', action='store_true')
    parser.add_argument('--cuda', type=int, default=0)
    args = parser.parse_args()
    torch.cuda.set_device(args.cuda)
    filename = args.filename
    modelname = args.modelname
    num_partitions = args.num_partitions
    preprocess_time = 0
    with open(paths.get_data_path(filename), 'r') as f:
        lines = f.readlines()
        num_nets, num_nodes = map(int, lines[0].split())
        hypergraph_vertices = list(range(num_nodes))
        hypergraph_edges, trunc_hypergraph_edges = [], []
        for line in lines[1:]:
            hypergraph_edges.append([int(node) - 1 for node in line.split()])
            if len(line.split()) > 1000:
                continue
            trunc_hypergraph_edges.append([int(node) - 1 for node in line.split()])
    t0 = time.time()
    data, initial_partition = preprocess_data(hypergraph_vertices, trunc_hypergraph_edges, filename, num_nodes, num_nets, args.use_sketch)
    data = data.to(device)
    t1 = time.time()
    preprocess_time += t1 - t0
    input_dim = 7
    latent_dim = args.latent_dim
    hidden_dim = args.hidden_dim
    num_partitions = 2
    model = GraphPartitionModel(input_dim, hidden_dim, latent_dim, num_partitions, True)
    model.load_state_dict(torch.load(paths.get_model_path(modelname), map_location=device))
    model = model.to(device)
    model.eval()
    best_cut, best_imbalance = evaluate_partition(initial_partition, hypergraph_vertices, hypergraph_edges, num_partitions)
    best_partition_id = initial_partition
    reason_time = 0
    vcycle_time = 0
    for tau in range(11):
        tau_best_cut = float('inf')
        t0 = time.time()
        partitions = model.sample(data, m=12)
        t1 = time.time()
        reason_time += t1 - t0
        t0 = time.time()
        processes = []
        pool = mp.Pool(processes=12)
        for m, partition in enumerate(partitions):
            processes.append(pool.apply_async(evalPoint, (m, partitions[m], hypergraph_vertices, hypergraph_edges, num_partitions, filename, True, True)))
            time.sleep(0.01)
        pool.close()
        pool.join()
        for process in processes:
            cut, imbalance, partition_id = process.get()
            tau_best_cut = min(tau_best_cut, cut)
            if cut < best_cut:
                best_cut = cut
                best_imbalance = imbalance
                best_partition_id = partition_id
        t1 = time.time()
        vcycle_time += t1 - t0
        print(f'Tau: {tau}, Best Cut: {best_cut}, Imbalance: {best_imbalance:.3f}, Cut: {tau_best_cut}')
        best_partition_id = best_partition_id / np.linalg.norm(best_partition_id) * np.linalg.norm(data.x[:, 4].cpu().numpy())
        data.x[:, 6] = torch.tensor(best_partition_id, dtype=torch.float).to(device)
    print(f'Final Best Cut: {best_cut}, Imbalance: {best_imbalance:.3f}, Preprocess Time: {preprocess_time:.3f}, Reasoning Time: {reason_time:.3f}, V-Cycle Time: {vcycle_time:.3f}')
