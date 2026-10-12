import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import GCNConv
from torch import nn
from dgl.nn.pytorch import GraphConv,NNConv
import os
import dgl
import random as rd

class GCN(nn.Module):
    def __init__(self, in_channels, hidden_channels, out_channels, num_layers=2,
                 dropout=0.5, save_mem=True, use_bn=True):
        super(GCN, self).__init__()

        self.convs = nn.ModuleList()
        # self.convs.append(
        #     GCNConv(in_channels, hidden_channels, cached=not save_mem, normalize=not save_mem))
        self.convs.append(
            GCNConv(in_channels, hidden_channels, cached=not save_mem))

        self.bns = nn.ModuleList()
        self.bns.append(nn.BatchNorm1d(hidden_channels))
        for _ in range(num_layers - 2):
            # self.convs.append(
            #     GCNConv(hidden_channels, hidden_channels, cached=not save_mem, normalize=not save_mem))
            self.convs.append(
                GCNConv(hidden_channels, hidden_channels, cached=not save_mem))
            self.bns.append(nn.BatchNorm1d(hidden_channels))

        # self.convs.append(
        #     GCNConv(hidden_channels, out_channels, cached=not save_mem, normalize=not save_mem))
        self.convs.append(
            GCNConv(hidden_channels, out_channels, cached=not save_mem))

        self.dropout = dropout
        self.activation = F.relu
        self.use_bn = use_bn

    def reset_parameters(self):
        for conv in self.convs:
            conv.reset_parameters()
        for bn in self.bns:
            bn.reset_parameters()

    def forward(self, data):
        x = data.graph['node_feat']
        edge_index=data.graph['edge_index']
        edge_weight=data.graph['edge_weight'] if 'edge_weight' in data.graph else None
        for i, conv in enumerate(self.convs[:-1]):
            if edge_weight is None:
                x = conv(x, edge_index)
            else:
                x=conv(x,edge_index,edge_weight)
            if self.use_bn:
                x = self.bns[i](x)
            x = self.activation(x)
            x = F.dropout(x, p=self.dropout, training=self.training)
        x = self.convs[-1](x, data.graph['edge_index'])
        return x

class MPNN(nn.Module):
    def __init__(self, aggregator_type,node_in_feats, node_hidden_dim, edge_input_dim, edge_hidden_dim,num_step_message_passing,gconv_dp,edge_dp,nn_dp1):

        super(MPNN, self).__init__()
        self.lin0 = nn.Linear(node_in_feats, node_hidden_dim)#65,32
        self.num_step_message_passing=num_step_message_passing
        edge_network = nn.Sequential(

            nn.Linear(edge_input_dim, edge_hidden_dim),
            nn.ReLU(),
            nn.Dropout(p=edge_dp),
            nn.Linear(edge_hidden_dim, node_hidden_dim * node_hidden_dim),
            nn.Dropout(p=edge_dp))#1-4-32x32

        self.conv = NNConv(in_feats=node_hidden_dim,#32
               out_feats=node_hidden_dim,#32
               edge_func=edge_network,#32x32
               aggregator_type=aggregator_type)



        self.y_linear = nn.Linear(node_hidden_dim, 2)#4-4
        self.bn = nn.BatchNorm1d(node_hidden_dim)



        self.gnn_dropout = nn.Dropout(p=gconv_dp)#dropout
        self.nn_dropout = nn.Dropout(p=nn_dp1)
        # self.nn_dropout2 = nn.Dropout(p=nn_dp2)

    def forward(self, g, n_feat, e_feat):
        out = torch.relu(self.lin0(n_feat))  # (B1, H1)

        for i in range(self.num_step_message_passing):
            out = torch.relu(self.conv(g, out, e_feat))
            out = self.gnn_dropout(out)# (B1, H1)

        y_bn = self.bn(out)

        return y_bn

