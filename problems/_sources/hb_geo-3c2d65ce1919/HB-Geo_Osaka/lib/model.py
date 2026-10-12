import torch
import torch.nn as nn
import dgl.function as fn
from dgl.nn.pytorch import edge_softmax
import numpy as np
import torch.nn.functional as F

sig = nn.Sigmoid()
hardtanh = nn.Hardtanh(0,1)
gamma = -0.1
zeta = 1.1
beta = 0.66
eps = 1e-20
const1 = beta*np.log(-gamma/zeta + eps)

def l0_train(logAlpha, min_val, max_val):
    U = torch.rand(logAlpha.size()).type_as(logAlpha) + eps
    s = sig((torch.log(U / (1 - U)) + logAlpha) / beta)
    s_bar = s * (zeta - gamma) + gamma
    mask = F.hardtanh(s_bar, min_val, max_val)
    return mask

def l0_test(logAlpha, min_val, max_val):
    s = sig(logAlpha/beta)
    s_bar = s * (zeta - gamma) + gamma
    mask = F.hardtanh(s_bar, min_val, max_val)
    return mask

def get_loss2(logAlpha):
    return sig(logAlpha - const1)


class GraphAttention(nn.Module):
    def __init__(self,
                 in_dim,
                 out_dim,
                 num_heads,
                 feat_drop,
                 attn_drop,
                 alpha,
                 bias_l0,
                 residual=False,
                 l0=0, 
                 min_val=0):
        super(GraphAttention, self).__init__()
        self.num_heads = num_heads
        self.fc = nn.Linear(in_dim, num_heads * out_dim, bias=False)
        if feat_drop:
            self.feat_drop = nn.Dropout(feat_drop)
        else:
            self.feat_drop = lambda x : x
        if attn_drop:
            self.attn_drop = nn.Dropout(attn_drop)
        else:
            self.attn_drop = lambda x : x
        self.attn_l = nn.Parameter(torch.Tensor(size=(1, 1, out_dim)))
        self.attn_r = nn.Parameter(torch.Tensor(size=(1, 1, out_dim)))
        self.bias_l0 = nn.Parameter(torch.FloatTensor([bias_l0]))

        nn.init.xavier_normal_(self.fc.weight.data, gain=1.414)
        nn.init.xavier_normal_(self.attn_l.data, gain=1.414)
        nn.init.xavier_normal_(self.attn_r.data, gain=1.414)
        self.leaky_relu = nn.LeakyReLU(alpha)
        self.softmax = edge_softmax
        self.residual = residual
        self.num = 0
        self.l0 = l0
        self.loss = 0
        self.dis = []
        self.min_val = min_val
        if residual:
            if in_dim != out_dim:
                self.res_fc = nn.Linear(in_dim, num_heads * out_dim, bias=False)
                nn.init.xavier_normal_(self.res_fc.weight.data, gain=1.414)
            else:
                self.res_fc = None

    def forward(self, g, inputs, edges="__ALL__", skip=0):
        self.loss = 0
        # prepare
        h = self.feat_drop(inputs)
        ft = self.fc(h).reshape((h.shape[0], self.num_heads, -1))
        a1 = (ft * self.attn_l).sum(dim=-1).unsqueeze(-1)
        a2 = (ft * self.attn_r).sum(dim=-1).unsqueeze(-1)
        g.ndata.update({'ft' : ft, 'a1' : a1, 'a2' : a2})


        if skip == 0:
            g.apply_edges(self.edge_attention, edges)
            if self.l0 == 1:
                ind = g.nodes()
                g.apply_edges(self.loop, edges=(ind, ind))
            self.edge_softmax(g)

            if self.l0 == 1:
                g.apply_edges(self.norm)

            edges = g.edata['a'].squeeze().nonzero().squeeze()


        g.edata['a_drop'] = self.attn_drop(g.edata['a'])
        self.num = (g.edata['a'] > 0).sum()
        g.update_all(fn.u_mul_e('ft', 'a_drop', 'ft'), fn.sum('ft', 'ft'))
        ret = g.ndata['ft']


        if self.residual:
            if self.res_fc is not None:
                resval = self.res_fc(h).reshape((h.shape[0], self.num_heads, -1))
            else:
                resval = torch.unsqueeze(h, 1)
            ret = resval + ret
        return ret, edges

    def edge_attention(self, edges):
        if self.l0 == 0:
            m = self.leaky_relu(edges.src['a1'] + edges.dst['a2'])
        else:
            tmp = edges.src['a1'] + edges.dst['a2']
            logits = tmp + self.bias_l0

            if self.training:
                m = l0_train(logits, 0, 1)
            else:
                m = l0_test(logits, 0, 1)
            self.loss = get_loss2(logits[:,0,:]).sum()
        return {'a': m}

    def norm(self, edges):
        # normalize attention
        a = edges.data['a'] / edges.dst['z']
        return {'a' : a}

    def loop(self, edges):
        # set attention to itself as 1
        return {'a': torch.pow(edges.data['a'], 0)}

    def normalize(self, g, logits):
        _logits_name = "_logits"
        _normalizer_name = "_norm"

        g.edata[_logits_name] = logits

        g.update_all(fn.copy_e(_logits_name, _logits_name),
                     fn.sum(_logits_name, _normalizer_name))

        return g.edata.pop(_logits_name), g.ndata.pop(_normalizer_name)

    def edge_softmax(self, g):

        if self.l0 == 0:
            scores = self.softmax(g, g.edata.pop('a'))
        else:
            scores, normalizer = self.normalize(g, g.edata.pop('a'))
            g.ndata['z'] = normalizer[:,0,:].unsqueeze(1)

        g.edata['a'] = scores[:,0,:].unsqueeze(1)

class GAT(nn.Module):
    def __init__(self,
                 in_dim,
                 num_hidden,
                 num_classes,
                 heads,
                 activation,
                 feat_drop,
                 attn_drop,
                 alpha,
                 bias_l0,
                 num_layers,
                 residual=False, 
                 l0=0):
        super(GAT, self).__init__()
        self.num_layers = num_layers
        self.gat_layers = nn.ModuleList()
        self.activation = activation
        self.bn_layers = nn.ModuleList()
        
        self.gat_layers.append(GraphAttention(
            in_dim, num_hidden, heads[0], feat_drop, attn_drop, alpha,
            bias_l0, False, l0=l0, min_val=0))
        
        # hidden layers
        for l in range(1, num_layers):
            # due to multi-head, the in_dim = num_hidden * num_heads
            self.gat_layers.append(GraphAttention(
                num_hidden * heads[l-1], num_hidden, heads[l],
                feat_drop, attn_drop, alpha, bias_l0, residual, l0=l0, min_val=0))
            self.bn_layers.append(nn.BatchNorm1d(num_hidden))
        
        self.bn_layers.append(nn.BatchNorm1d(num_hidden))
        
        # output projection
        self.gat_layers.append(GraphAttention(
            num_hidden * heads[-2], num_hidden, heads[-1],
            feat_drop, attn_drop, alpha, bias_l0, residual, l0=l0))

        self.y_linear = nn.Linear(num_hidden, 2)
        self.bn = nn.BatchNorm1d(num_hidden)
        self.bn_1 = nn.BatchNorm1d(num_hidden)

    def forward(self, g, inputs):
        h = inputs
        edges = "__ALL__"
        

        h, edges = self.gat_layers[0](g, h, edges)
        h = self.activation(h.flatten(1))
        

        for l in range(1, self.num_layers):
            h, _ = self.gat_layers[l](g, h, edges, skip=1)
            h = self.activation(h.flatten(1))

        # output projection
        logits, _ = self.gat_layers[-1](g, h, edges, skip=1)
        logits = logits.mean(1)

        y_bn = self.bn(logits)
        y_bn = torch.sigmoid(y_bn)
        y_sigmoid = torch.sigmoid(self.y_linear(y_bn))

        return y_sigmoid
