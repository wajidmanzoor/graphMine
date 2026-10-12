# -*- coding: utf-8 -*-import networkx as nx

import networkx as nx
import xml.etree.ElementTree as ET
import random
import subprocess
import math
import re
import numpy as np
from statistics import mean
import sys
import os

import networkx as nx

def apply_edit_operations(original_graph, edit_path, n):
    """
    Applies the first N operations from the edit path to transform the original graph.
    
    Args:
        original_graph (nx.Graph): The original graph to transform.
        edit_path (list): List of edit operations. Each operation is either:
            - A tuple (old_node_info, new_node_info) for node substitutions.
            - A list of edge changes, where each edge change is a tuple (old_edge, new_edge).
        n (int): Number of operations to apply from the start of the edit path.
    
    Returns:
        nx.Graph: The transformed graph after applying the first N operations.
    """
    G = original_graph.copy()
    applied = 0
    for operation in edit_path:
        if applied >= n:
            break
        # Node substitution: (old_node_info, new_node_info)
        if isinstance(operation, tuple):
            old_node_info, new_node_info = operation
            old_id = old_node_info.get('id')
            new_id = new_node_info.get('id')
            new_attrs = new_node_info.get('attrs', {})
            
            # Remove old node (and its edges)
            if G.has_node(old_id):
                G.remove_node(old_id)
            # Add new node with attributes
            G.add_node(new_id, **new_attrs)
            applied += 1
        # Edge operations: list of (old_edge, new_edge)
        elif isinstance(operation, list):
            for edge_change in operation:
                old_edge, new_edge = edge_change
                # Remove old edge if present (check attributes if provided)
                if old_edge is not None:
                    u, v = old_edge[:2]
                    attrs = old_edge[2] if len(old_edge) > 2 else {}
                    if G.has_edge(u, v):
                        current_attrs = G[u][v]
                        # Check if all specified attributes match
                        match = all(current_attrs.get(key) == value for key, value in attrs.items())
                        if match:
                            G.remove_edge(u, v)
                # Add new edge if specified
                if new_edge is not None:
                    u, v = new_edge[:2]
                    new_attrs = new_edge[2] if len(new_edge) > 2 else {}
                    G.add_edge(u, v, **new_attrs)
            applied += 1
    return G

def parse_output(text):
    # Initialize result dictionary
    result = {
        "GED_value": None,
        "time_ms": None,
        "nb_ops": None,
        "path": None,
    }

    # Extract initial value, time, and operations
    initial_match = re.search(r'^([\d.]+),\s+T:\s+(\d+)\s+millisecondsNB\s+ops\s+:\s+(\d+)', text)
    if initial_match:
        result["GED_value"] = float(initial_match.group(1))
        result["time_ms"] = int(initial_match.group(2))
        result["nb_ops"] = int(initial_match.group(3))

    # Extract path entries
    path_section = re.search(r'Path \[p=\[(.*?)\]\]', text, re.DOTALL)
    if path_section:
        result["path"] = path_section.group(1)
        # Split path entries while handling nested structures
        


    return result

def parse_node(node_str):
    # Parse node details like "V_1{18487, H7}'"
    if node_str == "null":
        return None
    node_match = re.match(r'([A-Za-z_]\w*)\{([^}]+)\}', node_str.replace("'", ""))
    if node_match:
        return {
            "id": node_match.group(1),
            "attributes": [attr.strip() for attr in node_match.group(2).split(',')]
        }
    return node_str

# total arguments
n = len(sys.argv)
print("Total arguments passed:", n)
 
# Arguments passed
print("\ntest-case:", sys.argv[0])
print("\nk-best:", sys.argv[1])
print("\ngraph-size:", sys.argv[2])
# Create a random graph using NetworkX

def random_graph(nb_nodes, density,init ):
    '''
    Generates a random graph with the specified number of nodes and density.
    '''
    G = nx.random_tree(nb_nodes, seed=42) #nx.fast_gnp_random_graph(nb_nodes+1, density,init)
    mapping = {i: i + 1 for i in G.nodes()}
    G = nx.relabel_nodes(G, mapping)
    #G.remove_node(0)
    #print(list(G.nodes))
    #print(list(G.edges))
    # Add random edge values to the graph
    for u, v in G.edges():
        G[u][v]['weight'] =  random.randint(1, 30) # Assigning a random weight to each edge
    nx.set_node_attributes(G, {node: {'mane':  'H'+str(random.randint(1,10))} for node in G.nodes()})
    return G
# Generate GXL code for the graph with edge values
def networx_to_GXL(G,file):
    '''
    Converts a NetworkX graph to GXL format and saves it to a file.'''
    gxl_graph = ET.Element('gxl')
    graph_element = ET.SubElement(gxl_graph, "graph")
    graph_element.set("id", "my_graph_id")
    for node, attr in G.nodes(data=True):
        node_element = ET.SubElement(graph_element, "node")
        node_element.set("id", str(node))
        for key, value in attr.items():
            attr_element = ET.SubElement(node_element, "attr")
            attr_element.set("name", str(key))
            value_element = ET.SubElement(attr_element, "string")
            value_element.text = str(value)
    #nx.set_node_attributes(G, {node: {'name': 'red'} for node in G.nodes()})
    for edge in G.edges():
        edge_element = ET.SubElement(graph_element, "edge")
        edge_element.set("from", str(edge[0]))
        edge_element.set("to", str(edge[1]))
        attr_element = ET.SubElement(edge_element, 'attr', name='weight')
        float_element = ET.SubElement(attr_element, 'int')
        float_element.text = str(G[edge[0]][edge[1]]['weight'])

    gxl_string = ET.tostring(gxl_graph, encoding='unicode')
    #print(gxl_string)
    # Write the GXL string to a file
    with open(file, 'w') as file:
        file.write(gxl_string)
    return 0



def node_subst_cost(node1, node2):
    if node1['mane'] == node2['mane']:
        return 0
    return 1


def node_del_cost(node):
    return 1 


def node_ins_cost(node):
    return 1 


def edge_subst_cost(node1, node2):
   
    if node1['weight'] == node2['weight']:
        return 0
    return 1


def edge_del_cost(node):
    return 1 


def edge_ins_cost(node):
    return 1  

def run_fast_ged(G1, G2, kbest, kbest_time, k, ggraph1, ggraph2):
    '''
    Runs the fast GED algorithm using Java and parses the output.
    '''
    best_parsed_data = None
    java_exe="java"
    jar_args=["1","1","1","1",ggraph1,ggraph2,"slurm_result/output.txt","MUTA",str(k)]

    cmd= [java_exe,"-jar" ]+["./bin/graph-ged-super.jar"]+jar_args
    run_process = subprocess.run(cmd, capture_output=True, text=True)
    run_process1 = subprocess.run(cmd, capture_output=True, text=True)
    run_process2 = subprocess.run(cmd, capture_output=True, text=True)
    run_process.stdout += run_process1.stdout
    run_process.stdout += run_process2.stdout
    if run_process.stderr != "":
        print(" f'Runtime Error:"+ run_process.stderr)
    # print( run_process.stdout)
    kged=0
    
    s0=run_process.stdout.splitlines()
    for line in s0:
        parsed_data = parse_output(line)
        if(parsed_data['GED_value'] is not None):
            #print(parsed_data)
           
            if best_parsed_data is None or kged < best_parsed_data['GED_value']:
                best_parsed_data = parsed_data
        return best_parsed_data


import time
net=[]
net_t=[]
kbest=[]
kbest_time=[]
#for density in range(9):
k=int(sys.argv[1])
graph_size=int(sys.argv[2])
iterations=int(sys.argv[3])
#random.seed(int(sys.argv[1]))
print("fast-GED K parameter:",k,"graph size:",graph_size)
for i in range(iterations):

    # Record the start time
    G=random_graph(graph_size,0,random.randint(1,100))
    networx_to_GXL(G, f"./data/ggraph1_{graph_size}.gxl")

    G2=random_graph(graph_size,0,random.randint(1,100))
    networx_to_GXL(G2,f"./data/ggraph2_{graph_size}.gxl")
    start_time = time.time() 
    # Calculate the elapsed time
    ged=nx.graph_edit_distance(G, G2, node_subst_cost=node_subst_cost, node_del_cost=node_del_cost, node_ins_cost=node_ins_cost,edge_subst_cost=edge_subst_cost, edge_del_cost=edge_del_cost, edge_ins_cost=edge_ins_cost)#,timeout=10000)
    end_time = time.time()    # Record the end time
    elapsed_time = end_time - start_time
    print("\n\nNetworkX:",ged,",T:", int(elapsed_time*1000), " milliseconds")


    fast_ged=run_fast_ged(G, G2, kbest, kbest_time, k, f"./data/ggraph1_{graph_size}.gxl", f"./data/ggraph2_{graph_size}.gxl")
    kged=float(fast_ged['GED_value'])
    kbest.append(kged)
    kbest_time.append(int(fast_ged["time_ms"]))
    print("FAS-GED:",fast_ged['GED_value'],",T:", int(fast_ged["time_ms"]), " milliseconds")
   # print("Edit Path:",fast_ged['path'])

    apply_edit_operations(G, fast_ged['path'], 5)
   
    #print(distance)  # GED score
  
    net.append(ged)
    net_t.append(elapsed_time*1000)

print("mean speedup:",mean(net_t)/mean(kbest_time),"mean deviation:",((mean(kbest)-mean(net))/mean(net))*100)
print("mean time netx,fast-ged:",mean(net_t), mean(kbest_time),"mean edit diatance netx,fast-ged:",mean(net), mean(kbest))
print("ged_netx"+str(net))
print("ged_kbest"+str(kbest))
nbmatch=0
for i in range(len(net)):
    if math.fabs(net[i] - kbest[i]) < 0.01:
        nbmatch += 1
print("reaching optimal result:", nbmatch)
