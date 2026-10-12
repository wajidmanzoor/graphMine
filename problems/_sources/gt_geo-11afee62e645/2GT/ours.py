import math
import os
from multiprocessing.sharedctypes import Value

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from  models import MPNN
from models import GCN
from torch_geometric.utils import degree
from torch_sparse import SparseTensor, matmul


def full_attention_conv(qs, ks, vs, output_attn=False):
    # normalize input
    qs = qs / torch.norm(qs, p=2)  # [N, H, M]
    ks = ks / torch.norm(ks, p=2)  # [L, H, M]
    N = qs.shape[0]
    #print(vs.shape)

    # numerator
    #kvs = torch.einsum("lhm,lhd->hmd", ks, vs)
    #attention_num = torch.einsum("nhm,hmd->nhd", qs, kvs)  # [N, H, D]
    with torch.backends.cuda.sdp_kernel(enable_flash=True,enable_math=True,enable_mem_efficient=True):
        kvs = torch.einsum("lhm,lhd->hmd", ks, vs)
        attention_num = torch.einsum("nhm,hmd->nhd", qs, kvs)  # [N, H, D]
        #attention_num=F.scaled_dot_product_attention(qs,ks,vs)
    attention_num += N * vs

    # denominator
    all_ones = torch.ones([ks.shape[0]]).to(ks.device)
    #ks_sum = torch.einsum("lhm,l->hm", ks, all_ones)
    #attention_normalizer = torch.einsum("nhm,hm->nh", qs, ks_sum)  # [N, H]
    with torch.backends.cuda.sdp_kernel(enable_flash=True,enable_math=True,enable_mem_efficient=True):
        ks_sum = torch.einsum("lhm,l->hm", ks, all_ones)
        attention_normalizer = torch.einsum("nhm,hm->nh", qs, ks_sum)  # [N, H]
        #attention_normalizer=F.scaled_dot_product_attention(qs,ks,all_ones)
    

    # attentive aggregated results
    attention_normalizer = torch.unsqueeze(
        attention_normalizer, len(attention_normalizer.shape))  # [N, H, 1]
    attention_normalizer += torch.ones_like(attention_normalizer) * N
    attn_output = attention_num / attention_normalizer  # [N, H, D]

    # compute attention for visualization if needed
    if output_attn:
        attention=torch.einsum("nhm,lhm->nlh", qs, ks).mean(dim=-1) #[N, N]
        normalizer=attention_normalizer.squeeze(dim=-1).mean(dim=-1,keepdims=True) #[N,1]
        attention=attention/normalizer


    if output_attn:
        return attn_output, attention
    else:
        return attn_output


class TransConvLayer(nn.Module):
    '''
    transformer with fast attention
    '''

    def __init__(self, in_channels,
                 out_channels,
                 num_heads,
                 use_weight=True):
        super().__init__()
        self.Wk = nn.Linear(in_channels, out_channels * num_heads)
        self.Wq = nn.Linear(in_channels, out_channels * num_heads)
        if use_weight:
            self.Wv = nn.Linear(in_channels, out_channels * num_heads)

        self.out_channels = out_channels
        self.num_heads = num_heads
        self.use_weight = use_weight

    def reset_parameters(self):
        self.Wk.reset_parameters()
        self.Wq.reset_parameters()
        if self.use_weight:
            self.Wv.reset_parameters()

    def forward(self, query_input, source_input, edge_index=None, edge_weight=None, output_attn=False):
        # feature transformation
        query = self.Wq(query_input).reshape(-1,
                                             self.num_heads, self.out_channels)
        key = self.Wk(source_input).reshape(-1,
                                            self.num_heads, self.out_channels)
        if self.use_weight:
            value = self.Wv(source_input).reshape(-1,
                                                  self.num_heads, self.out_channels)
        else:
            value = source_input.reshape(-1, 1, self.out_channels)

        # compute full attentive aggregation
        if output_attn:
            attention_output, attn = full_attention_conv(
                query, key, value, output_attn)  # [N, H, D]
        else:
            attention_output = full_attention_conv(
                query, key, value)  # [N, H, D]

        final_output = attention_output
        final_output = final_output.mean(dim=1)

        if output_attn:
            return final_output, attn
        else:
            return final_output


class TransConv(nn.Module):
    def __init__(self, in_channels, hidden_channels, num_layers=2, num_heads=1,
                 alpha=0.5, dropout=0.5, use_bn=True, use_residual=True, use_weight=True, use_act=False):
        super().__init__()

        self.convs = nn.ModuleList()
        self.fcs = nn.ModuleList()
        self.fcs.append(nn.Linear(in_channels, hidden_channels))
        self.bns = nn.ModuleList()
        self.bns.append(nn.LayerNorm(hidden_channels))
        for i in range(num_layers):
            self.convs.append(
                TransConvLayer(hidden_channels, hidden_channels, num_heads=num_heads, use_weight=use_weight))
            self.bns.append(nn.LayerNorm(hidden_channels))

        self.dropout = dropout
        self.activation = F.relu
        self.use_bn = use_bn
        self.residual = use_residual
        self.alpha = alpha
        self.use_act=use_act

    def reset_parameters(self):
        for conv in self.convs:
            conv.reset_parameters()
        for bn in self.bns:
            bn.reset_parameters()
        for fc in self.fcs:
            fc.reset_parameters()

    def forward(self, data):
        #x = data.graph['node_feat']
        x = data
        #edge_index = data.graph['edge_index']
        #edge_weight = data.graph['edge_weight'] if 'edge_weight' in data.graph else None
        layer_ = []

        # input MLP layer
        x = self.fcs[0](x)
        if self.use_bn:
            x = self.bns[0](x)
        x = self.activation(x)
        x = F.dropout(x, p=self.dropout, training=self.training)

        layer_.append(x)

        for i, conv in enumerate(self.convs):
            # graph convolution with full attention aggregation
            x = conv(x, x)
            if self.residual:
                x = self.alpha * x + (1-self.alpha) * layer_[i]
            if self.use_bn:
                x = self.bns[i+1](x)
            if self.use_act:
                x = self.activation(x) 
            x = F.dropout(x, p=self.dropout, training=self.training)
            layer_.append(x)

        return x

    def get_attentions(self, x):
        layer_, attentions = [], []
        x = self.fcs[0](x)
        if self.use_bn:
            x = self.bns[0](x)
        x = self.activation(x)
        layer_.append(x)
        for i, conv in enumerate(self.convs):
            x, attn = conv(x, x, output_attn=True)
            attentions.append(attn)
            if self.residual:
                x = self.alpha * x + (1 - self.alpha) * layer_[i]
            if self.use_bn:
                x = self.bns[i + 1](x)
            layer_.append(x)
        return torch.stack(attentions, dim=0)  # [layer num, N, N]

class TransConv2(nn.Module):
    def __init__(self, in_channels, hidden_channels, num_layers=2, num_heads=1,
                 alpha=0.5, dropout=0.5, use_bn=True, use_residual=True, use_weight=True, use_act=False):
        super().__init__()

        self.convs = nn.ModuleList()
        self.bns = nn.ModuleList()
        self.bns.append(nn.LayerNorm(hidden_channels))
        for i in range(num_layers):
            self.convs.append(
                TransConvLayer(hidden_channels, hidden_channels, num_heads=num_heads, use_weight=use_weight))
            self.bns.append(nn.LayerNorm(hidden_channels))

        self.dropout = dropout
        self.activation = F.relu
        self.use_bn = use_bn
        self.residual = use_residual
        self.alpha = alpha
        self.use_act=use_act

    def reset_parameters(self):
        for conv in self.convs:
            conv.reset_parameters()
        for bn in self.bns:
            bn.reset_parameters()

    def forward(self, data):
        #x = data.graph['node_feat']
        x = data
        layer_ = []

        # input MLP layer
        if self.use_bn:
            x = self.bns[0](x)
        x = self.activation(x)
        x = F.dropout(x, p=self.dropout, training=self.training)

        layer_.append(x)

        for i, conv in enumerate(self.convs):

            x = conv(x, x)
            if self.residual:
                x = self.alpha * x + (1-self.alpha) * layer_[i]
            if self.use_bn:
                x = self.bns[i+1](x)
            if self.use_act:
                x = self.activation(x) 
            x = F.dropout(x, p=self.dropout, training=self.training)
            layer_.append(x)

        return x

    def get_attentions(self, x):
        layer_, attentions = [], []
        if self.use_bn:
            x = self.bns[0](x)
        x = self.activation(x)
        layer_.append(x)
        for i, conv in enumerate(self.convs):
            x, attn = conv(x, x, output_attn=True)
            attentions.append(attn)
            if self.residual:
                x = self.alpha * x + (1 - self.alpha) * layer_[i]
            if self.use_bn:
                x = self.bns[i + 1](x)
            layer_.append(x)
        return torch.stack(attentions, dim=0)  # [layer num, N, N]


class SGFormer(nn.Module):
    def __init__(self, in_channels, hidden_channels, out_channels, num_layers=2, num_heads=1, 
                 alpha=0.5, dropout=0.5, use_bn=True, use_residual=True, use_weight=True, use_graph=True, use_act=False, graph_weight=0.8, gnn=None, aggregate='add'):
        super().__init__()
        self.trans_conv=TransConv(in_channels,hidden_channels,num_layers,num_heads,alpha,dropout,use_bn,use_residual,use_weight)
        self.gnn=gnn
        self.use_graph=use_graph
        self.graph_weight=graph_weight
        self.use_act=use_act

        self.aggregate=aggregate

        if aggregate=='add':
            self.fc=nn.Linear(hidden_channels,out_channels)
        elif aggregate=='cat':
            self.fc=nn.Linear(2*hidden_channels,out_channels)
        else:
            raise ValueError(f'Invalid aggregate type:{aggregate}')
        
        self.params1=list(self.trans_conv.parameters())
        self.params2=list(self.gnn.parameters()) if self.gnn is not None else []
        self.params2.extend(list(self.fc.parameters()) )

        self.geo_fc = nn.Linear(out_channels,2)
        self.params3 = list(self.geo_fc.parameters())
        #self.params3 = list(self.geo_fc.parameters())

    def forward(self,data):
        x1=self.trans_conv(data)
        if self.use_graph:
            x2=self.gnn(data)
            if self.aggregate=='add':
                x=self.graph_weight*x2+(1-self.graph_weight)*x1
            else:
                x=torch.cat((x1,x2),dim=1)
        else:
            x=x1
        x=self.fc(x)
        return x
    
    def get_attentions(self, x):
        attns=self.trans_conv.get_attentions(x) # [layer num, N, N]

        return attns

    def reset_parameters(self):
        self.trans_conv.reset_parameters()
        self.geo_fc.reset_parameters()
        if self.use_graph:
            self.gnn.reset_parameters()

class SGFormer1(nn.Module):
    def __init__(self, in_channels, hidden_channels, num_layers=2, num_heads=1, 
                 alpha=0.5, dropout=0.5, use_bn=True, use_residual=True, use_weight=True, use_graph=True, use_act=False, graph_weight=0.8, gnn=None, aggregate='add',                 
                 edge_input_dim = 9,
                    edge_hidden_dim = 18,
                    num_step_message_passing= 3,
                    gconv_dp=0,
                    edge_dp=0,
                    nn_dp1=0):
        super().__init__()
        self.trans_conv=TransConv(in_channels,hidden_channels,num_layers,num_heads,alpha,dropout,use_bn,use_residual,use_weight)
        self.trans_conv2 = TransConv2(hidden_channels,hidden_channels,num_layers,num_heads,alpha,dropout,use_bn,use_residual,use_weight)
        self.trans_conv3 = TransConv2(hidden_channels,hidden_channels,num_layers,num_heads,alpha,dropout,use_bn,use_residual,use_weight)

        self.gnn=gnn
        self.gnn2 = MPNN(aggregator_type='sum',
                     node_in_feats=hidden_channels,
                     node_hidden_dim= hidden_channels,
                    edge_input_dim = edge_input_dim,
                    edge_hidden_dim = edge_hidden_dim,
                    num_step_message_passing= num_step_message_passing,
                    gconv_dp=gconv_dp,
                    edge_dp=edge_dp,
                    nn_dp1=nn_dp1)
        self.use_graph=use_graph
        self.graph_weight=graph_weight
        self.use_act=use_act

        self.aggregate=aggregate
        
        self.params1=list(self.trans_conv.parameters())
        self.params2=list(self.gnn.parameters()) 


        self.geo_fc = nn.Linear(hidden_channels,2)
        self.params3 = list(self.geo_fc.parameters())
        self.params4=list(self.trans_conv2.parameters())
        #self.params5=list(self.trans_conv3.parameters())
        #self.bn = nn.BatchNorm1d(hidden_channels)
        #self.params6 = list(self.bn.parameters())
        self.params7= list(self.gnn2.parameters()) 

    def forward(self,G,node_feat, edge_attr_tensor,data):

        x2=self.gnn(G, node_feat, edge_attr_tensor)
        x1=self.trans_conv(data)

        if self.use_graph:

            if self.aggregate=='add':
                #x = x2
                x=self.graph_weight*x2+(1-self.graph_weight)*x1
            else:
                x=torch.cat((x1,x2),dim=1)
        else:
            x=self.trans_conv(data)

        x3=self.gnn2(G, x, edge_attr_tensor)
        x4=self.trans_conv2(x)
        #x1=self.bn(x1)
        if self.use_graph:

            if self.aggregate=='add':
                #x = x2
                x=self.graph_weight*x3+(1-self.graph_weight)*x4
            else:
                x=torch.cat((x3,x4),dim=1)
        else:
            x=self.trans_conv2(x)

        #x = self.bn(x)
        x=torch.sigmoid(self.geo_fc(x))
        return x
    
    def get_attentions(self, x):
        attns=self.trans_conv.get_attentions(x) # [layer num, N, N]

        return attns

    def reset_parameters(self):
        self.trans_conv.reset_parameters()

        self.geo_fc.reset_parameters()
        self.trans_conv2.reset_parameters()

        if self.use_graph:
            self.gnn.reset_parameters()
