# Load data and IP clustering

import json
import math, csv
import random
import pandas as pd
import numpy as np
import argparse
from sklearn import preprocessing
from lib.utils import MaxMinScaler
from tqdm import tqdm
import networkx as nx
import ast

parser = argparse.ArgumentParser()

parser.add_argument('--dataset', type=str, default='Shanghai', choices=["Shanghai", "New_York", "LosAngeles","Hongkong","Tokyo","Seoul","Chicago","Osaka","Dallas","Seattle"],
                    help='which dataset to use')
parser.add_argument('--train_test_ratio', type=float, default=0.8, help='landmark ratio')
parser.add_argument('--lm_ratio', type=float, default=0.7, help='landmark ratio')
parser.add_argument('--seed', type=int, default=1234)
# parser.add_argument('--seed', type=int, default=2022)


opt = parser.parse_args()
print("Dataset: ", opt.dataset)





def get_XY_MINT(dataset):
    data_path = "./datasets/{}/data.csv".format(dataset)
    ip_path = './datasets/{}/IP.csv'.format(dataset)
    trace_path = './datasets/{}/last_traceroute.csv'.format(dataset)

    data_origin = pd.read_csv(data_path, encoding='gbk', low_memory=False)
    ip_origin = pd.read_csv(ip_path, encoding='gbk', low_memory=False)
    trace_origin = pd.read_csv(trace_path, encoding='gbk', low_memory=False)

    data = pd.concat([data_origin, ip_origin, trace_origin], axis=1)

    # labels
    Y = data[['longitude', 'latitude']]
    Y = np.array(Y)

    # features
    X_2 = data[['ip_split1', 'ip_split2', 'ip_split3', 'ip_split4']]
    X_2 = preprocessing.MinMaxScaler().fit_transform(np.array(X_2))

    X_5 = data[['trace_steps']]
    step_scaler = MaxMinScaler()
    step_scaler.fit(X_5)
    X_5 = step_scaler.transform(X_5)

    X_6 = data[['last1_delay', 'last2_delay_total', 'last3_delay_total', 'last4_delay_total']]
    X_6 = np.array(X_6)
    X_6[X_6 <= 0] = 0
    X_6 = preprocessing.MinMaxScaler().fit_transform(X_6)

    X = np.concatenate([X_2, X_5, X_6], axis=1)


    trace_data = data_origin['trace'].values
    print(f"Loaded {len(trace_data)} trace records from data.csv")

    return X, Y, trace_data




def get_idx_sig(num,seed,lm_ratio):
    idx = list(range(0, num))
    train_idx=[]
    lm_train_idx = []
    tg_train_idx = []
    tg_test_idx = []
    tg_val_idx = []

    #print(dataset)
    df1 = pd.read_csv("./datasets/Shanghai/data.csv")
    df2 = pd.read_csv("./datasets/Shanghai/data_train.csv")
    df3 = pd.read_csv("./datasets/Shanghai/data_val.csv")
    df4 = pd.read_csv("./datasets/Shanghai/data_test.csv")

    numip_set_train = set(df2['IP'])
    numip_set_val = set(df3['IP'])
    numip_set_test = set(df4['IP'])
    i = 0
    for numip in df1['IP']:
        if numip in numip_set_train:   
            train_idx.append(i)
        if numip in numip_set_val:
            tg_val_idx.append(i)
        if numip in numip_set_test:
            tg_test_idx.append(i)

        i+=1
    random.seed(seed)
    random.shuffle(train_idx)
    for tidx in train_idx:
        random_number = random.uniform(0,1)
        if random_number <= lm_ratio:
            lm_train_idx.append(tidx)
        else:
            tg_train_idx.append(tidx)

    return lm_train_idx, tg_train_idx, lm_train_idx + tg_train_idx, tg_val_idx , lm_train_idx + tg_train_idx , tg_test_idx



def parse_list_format_trace(trace_str):
    try:
        clean_str = trace_str.strip()
        if clean_str.startswith("['") and clean_str.endswith("']"):
            clean_str = clean_str[2:-2]
        
        parts = re.split(r"'\s*'", clean_str)
        
        trace_list = []
        i = 0
        while i < len(parts):
            if parts[i] and parts[i] != '-1':
                ip = parts[i].strip("'")
                if i + 1 < len(parts):
                    try:
                        rtt = float(parts[i + 1])
                        if rtt >= 0:
                            trace_list.append({ip: rtt})
                        i += 2
                        continue
                    except (ValueError, IndexError):
                        pass
                trace_list.append({ip: 0.0})
            i += 1
        
        return trace_list
    except Exception as e:
        print(f"Error parsing list format: {e}")
        return []

def parse_dict_format_trace(trace_str):
    try:
        parsed = ast.literal_eval(trace_str)
        if isinstance(parsed, list):
            return parsed
    except (SyntaxError, ValueError):
        pass
    return []

def parse_trace_data(trace_data):
    if trace_data is None or (isinstance(trace_data, float) and np.isnan(trace_data)):
        return []
    
    if isinstance(trace_data, list):
        return trace_data
    
    trace_str = str(trace_data).strip()
    
    if not trace_str or trace_str == "nan" or trace_str == "[]":
        return []
    
    result = parse_dict_format_trace(trace_str)
    if result:
        return result
    
    result = parse_list_format_trace(trace_str)
    if result:
        return result
    
    print(f"Failed to parse trace data with any format: {trace_str[:100]}...")
    return []

def debug_trace_data(T, sample_size=10):
    print("\n=== Debug Trace Data ===")
    dict_format_count = 0
    list_format_count = 0
    failed_count = 0
    
    for i in range(min(sample_size, len(T))):
        trace_data = T[i]
        print(f"Index {i}:")
        print(f"  Raw: {str(trace_data)[:200]}...")
        
        dict_result = parse_dict_format_trace(str(trace_data))
        list_result = parse_list_format_trace(str(trace_data))
        
        if dict_result:
            print(f"  Dict format: ✓ ({len(dict_result)} hops)")
            dict_format_count += 1
        elif list_result:
            print(f"  List format: ✓ ({len(list_result)} hops)")
            list_format_count += 1
        else:
            print(f"  Both formats: ✗")
            failed_count += 1
        print()
    
    print(f"Format statistics in first {sample_size} samples:")
    print(f"  Dictionary format: {dict_format_count}")
    print(f"  List format: {list_format_count}")
    print(f"  Failed: {failed_count}")


def get_graph_MINT(dataset, lm_idx, tg_idx, mode):
    X, Y, T = get_XY_MINT(dataset)
    
    G = nx.Graph()
    
    print("Building network topology from traceroute data...")
    
    valid_traces = 0
    for i, trace_data in tqdm(enumerate(T), total=len(T), desc="Building topology"):
        trace_list = parse_trace_data(trace_data)
        
        if not trace_list:
            continue
            
        valid_traces += 1
        
        prev_node = None
        prev_rtt = 0.0
        
        for hop in trace_list:
            if hop and isinstance(hop, dict) and len(hop) > 0:
                for router_ip, current_rtt in hop.items():
                    if router_ip and router_ip != "" and router_ip != "-1":
                        G.add_node(router_ip)
                        
                        if prev_node is not None and prev_node != "" and prev_node != "-1":
                            hop_rtt = current_rtt - prev_rtt
                            hop_rtt = max(hop_rtt, 0.0)
                            
                            if G.has_edge(prev_node, router_ip):
                                existing_rtt = G[prev_node][router_ip].get('rtt', hop_rtt)
                                min_hop_rtt = min(existing_rtt, hop_rtt)
                                G[prev_node][router_ip]['rtt'] = min_hop_rtt
                            else:
                                G.add_edge(prev_node, router_ip, rtt=hop_rtt)
                        
                        prev_node = router_ip
                        prev_rtt = current_rtt
    
    print(f"Network topology built with {G.number_of_nodes()} nodes and {G.number_of_edges()} edges")
    print(f"Processed {valid_traces}/{len(T)} valid traceroutes")
    
    data = []
    processed_count = 0
    
    print(f"Processing {len(tg_idx)} target IPs for {mode} set...")
    
    for id in tqdm(tg_idx, desc=f"Processing {mode} targets"):
        target_ip = None
        target_rtt = 0.0
        
        try:
            trace_data = T[id]
            trace_list = parse_trace_data(trace_data)
            
            if not trace_list:
                continue
                
            for hop in reversed(trace_list):
                if hop and isinstance(hop, dict) and len(hop) > 0:
                    target_ip = list(hop.keys())[0]
                    if target_ip and target_ip != "" and target_ip != "-1":
                        target_rtt = list(hop.values())[0]
                        break
                    
            if target_ip is None or target_ip == "" or target_ip == "-1":
                continue
                
        except Exception as e:
            continue
        
        min_hops = float('inf')
        closest_landmarks = []
        landmark_rtts = []
        
        for lm_id in lm_idx:
            try:
                lm_trace_data = T[lm_id]
                lm_trace_list = parse_trace_data(lm_trace_data)
                
                if not lm_trace_list:
                    continue
                    
                landmark_ip = None
                landmark_rtt = 0.0
                for hop in reversed(lm_trace_list):
                    if hop and isinstance(hop, dict) and len(hop) > 0:
                        landmark_ip = list(hop.keys())[0]
                        if landmark_ip and landmark_ip != "" and landmark_ip != "-1":
                            landmark_rtt = list(hop.values())[0]
                            break
                            
                if landmark_ip is None or landmark_ip == "" or landmark_ip == "-1":
                    continue
                
                if landmark_ip not in G:
                    G.add_node(landmark_ip)
                if target_ip not in G:
                    G.add_node(target_ip)
                
                try:
                    path_length = nx.shortest_path_length(G, landmark_ip, target_ip)
                    
                    try:
                        shortest_path = nx.shortest_path(G, landmark_ip, target_ip, weight='rtt')
                        path_rtt = 0.0

                        for i in range(len(shortest_path) - 1):
                            edge_rtt = G[shortest_path[i]][shortest_path[i+1]].get('rtt', 0.0)
                            path_rtt += edge_rtt
                    except:
                        path_rtt = abs(target_rtt - landmark_rtt)
                    
                    if path_length < min_hops:
                        min_hops = path_length
                        closest_landmarks = [lm_id]
                        landmark_rtts = [path_rtt]
                    elif path_length == min_hops:
                        closest_landmarks.append(lm_id)
                        landmark_rtts.append(path_rtt)
                        
                except nx.NetworkXNoPath:
                    continue
                    
            except Exception:
                continue
        
        if not closest_landmarks:
            closest_landmarks = lm_idx
            min_hops = -1
            landmark_rtts = [target_rtt] * len(lm_idx)
        
        # construct graph data
        lm_nodes = X[closest_landmarks]
        lm_labels = Y[closest_landmarks]
        tg_nodes = X[id]
        tg_labels = Y[id]
        
        data_tg = {
            "lm_X": lm_nodes,
            "lm_Y": lm_labels,
            "tg_X": np.expand_dims(tg_nodes, axis=0),
            "tg_Y": np.expand_dims(tg_labels, axis=0),
            "min_hops": min_hops if min_hops != float('inf') else -1,
            "target_id": id,
            "landmark_ids": closest_landmarks,
            "target_ip": target_ip,
            "target_rtt": target_rtt,
            "landmark_rtts": np.array(landmark_rtts),
            "avg_rtt": np.mean(landmark_rtts) if landmark_rtts else 0.0,
            "min_rtt": np.min(landmark_rtts) if landmark_rtts else 0.0,
            "max_rtt": np.max(landmark_rtts) if landmark_rtts else 0.0
        }
        data.append(data_tg)
        processed_count += 1

    print(f"Generated {len(data)} graph data entries for {mode} set")
    
    output_file = "datasets/{}/Clustering_s{}_graph{}_{}.npz".format(dataset, seed, int(lm_ratio * 100), mode)
    np.savez(output_file, data=data)
    print(f"Saved to {output_file}")
    
    return data

if __name__ == '__main__':
    seed = opt.seed
    train_test_ratio = opt.train_test_ratio
    lm_ratio = opt.lm_ratio
    
    X, Y, T = get_XY_MINT(opt.dataset)
    print(f"Loaded dataset with {len(X)} samples")
    
    lm_train_idx, tg_train_idx, lm_val_idx, tg_val_idx, lm_test_idx, tg_test_idx = get_idx_sig(
        len(X), seed, lm_ratio
    )

    print(f"Landmark indices: train={len(lm_train_idx)}, val={len(lm_val_idx)}, test={len(lm_test_idx)}")
    print(f"Target indices: train={len(tg_train_idx)}, val={len(tg_val_idx)}, test={len(tg_test_idx)}")

    print("Loading train set...")
    get_graph_MINT(opt.dataset, lm_train_idx, tg_train_idx, mode="train")
    print("Train set loaded.")

    print("Loading val set...")
    get_graph_MINT(opt.dataset, lm_val_idx, tg_val_idx, mode="val")
    print("Val set loaded.")

    print("Loading test set...")
    get_graph_MINT(opt.dataset, lm_test_idx, tg_test_idx, mode="test")
    print("Test set loaded.")

    print("Finish!")
