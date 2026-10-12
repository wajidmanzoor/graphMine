from __future__ import print_function
import numpy as np
import torch
import warnings
import torch.nn as nn
import random
import matplotlib.pyplot as plt
import copy
from math import radians, cos, sin, asin, sqrt
warnings.filterwarnings(action='once')


class DataPerturb:
    def __init__(self, eta=1):
        self.eta = eta
        self.loss = torch.nn.MSELoss(reduction='sum')

    def perturb(self, model, data):
        # original
        lm_X, lm_Y, tg_X, tg_Y, lm_delay, tg_delay = data

        # obtain new graph representation
        _, ori_graph_feature = model(lm_X, lm_Y, tg_X,
                                     tg_Y, lm_delay,
                                     tg_delay)

        # add Gaussian data perturb
        new_lm_X, new_lm_Y, new_tg_X, new_tg_Y, new_lm_delay, new_tg_delay = lm_X.clone(), lm_Y.clone(), \
                                                                             tg_X.clone(), tg_Y.clone(), \
                                                                             lm_delay.clone(), tg_delay.clone()
        new_lm_X[:, -16:] += self.eta * torch.normal(0, torch.ones_like(new_lm_X[:, -16:]) * new_lm_X[:, -16:]).cuda()
        new_tg_X[:, -16:] += self.eta * torch.normal(0, torch.ones_like(new_tg_X[:, -16:]) * new_tg_X[:, -16:]).cuda()
        new_lm_delay += self.eta * torch.normal(0, torch.ones_like(new_lm_delay) * new_lm_delay).cuda()
        new_tg_delay += self.eta * torch.normal(0, torch.ones_like(new_tg_delay) * new_tg_delay).cuda()

        # obtain new graph representation
        _, new_graph_feature = model(new_lm_X, new_lm_Y, new_tg_X,
                                     new_tg_Y, new_lm_delay,
                                     new_tg_delay)

        data_loss = self.loss(ori_graph_feature, new_graph_feature)
        return data_loss


class ParaPerturb:
    def __init__(self, zeta=1, mu=0.4, step=3):
        self.zeta = zeta
        self.mu = mu
        self.step = step
        self.ori_model = None
        self.model = None
        self.vice_model = None
        self.emb_backup = {}

        self.loss = torch.nn.MSELoss(reduction='mean')

    def load_model(self, model):
        self.ori_model = model
        self.model = copy.deepcopy(model)
        self.vice_model = copy.deepcopy(model)
        for name, param in self.model.named_parameters():
            self.emb_backup[name] = param.data.clone()

    def random_attack(self, data):
        lm_X, lm_Y, tg_X, tg_Y, lm_delay, tg_delay = data

        _, ori_graph_feature = self.model(lm_X, lm_Y, tg_X,
                                          tg_Y, lm_delay,
                                          tg_delay)

        # perturb with Gaussian noise
        for (_, adv_param), (_, param) in zip(self.vice_model.named_parameters(), self.model.named_parameters()):
            adv_param.data = param.data + self.zeta * torch.normal(0, torch.abs(torch.ones_like(param.data) * param.data)).cuda()

        _, new_graph_feature = self.vice_model(lm_X, lm_Y, tg_X,
                                               tg_Y, lm_delay,
                                               tg_delay)

        random_para_loss = self.loss(new_graph_feature, ori_graph_feature)
        random_para_loss.backward()

    def attack(self):
        for (_, adv_param), (name, param) in zip(self.vice_model.named_parameters(), self.model.named_parameters()):
            if adv_param.grad is not None:
                norm = torch.norm(adv_param.grad)
            else:
                norm = 0
            if norm != 0 and not torch.isnan(norm):
                r_at = self.mu * adv_param.grad / norm
                adv_param.data.add_(r_at)
                param.data = self.project(name, adv_param.data)

    def project(self, param_name, param_data):
        r = param_data - self.emb_backup[param_name]
        if torch.norm(r) > 2 * self.zeta * torch.norm(self.emb_backup[param_name]):
            r = 2 * self.zeta * torch.norm(self.emb_backup[param_name]) * r / torch.norm(r)
        return self.emb_backup[param_name] + r

    def attack_loss(self, data, is_last_one=False):
        lm_X, lm_Y, tg_X, tg_Y, lm_delay, tg_delay = data

        if not is_last_one:
            _, ori_graph_feature = self.model(lm_X, lm_Y, tg_X,
                                              tg_Y, lm_delay,
                                              tg_delay)

            _, new_graph_feature = self.vice_model(lm_X, lm_Y, tg_X,
                                                   tg_Y, lm_delay,
                                                   tg_delay)
        else:
            _, ori_graph_feature = self.ori_model(lm_X, lm_Y, tg_X,
                                                  tg_Y, lm_delay,
                                                  tg_delay)

            _, new_graph_feature = self.vice_model(lm_X, lm_Y, tg_X,
                                                   tg_Y, lm_delay,
                                                   tg_delay)
        attack_loss = self.loss(new_graph_feature, ori_graph_feature)
        return attack_loss

    def perturb(self, model, data):
        # initialize model, using deepcopy to prevent model from losing gradient of previous data perturbation
        self.load_model(model)

        # initialize perturbation with Gaussian noise
        self.random_attack(data)

        # inner maximization
        for t in range(self.step):
            self.attack()
            self.vice_model.zero_grad()
            self.model.zero_grad()
            attack_loss = self.attack_loss(data, is_last_one=(t == self.step - 1))
            # print(t, attack_loss)
            if t != (self.step - 1):
                attack_loss.backward()
            else:
                pass
        return attack_loss


class MaxMinLogRTTScaler():
    def __init__(self):
        self.min = 0.
        self.max = 1.

    def transform(self, data):
        data_o = np.array(data)
        data_o = np.log(data_o + 1)
        return (data_o - self.min) / (self.max - self.min)


class MaxMinRTTScaler():
    def __init__(self):
        self.min = 0.
        self.max = 1.

    def transform(self, data):
        data_o = np.array(data)
        # data_o = np.log(data_o + 1)
        return (data_o - self.min) / (self.max - self.min)


class MaxMinLogScaler():
    def __init__(self):
        self.min = 0.
        self.max = 1.

    def transform(self, data):
        data[data != 0] = -np.log(data[data != 0] + 1)
        max = torch.from_numpy(self.max).type_as(data).to(data.device) if torch.is_tensor(data) else self.max
        min = torch.from_numpy(self.min).type_as(data).to(data.device) if torch.is_tensor(data) else self.min
        data[data != 0] = (data[data != 0] - min) / (max - min)
        return data

    def inverse_transform(self, data):
        max = torch.from_numpy(self.max).type_as(data).to(data.device) if torch.is_tensor(data) else self.max
        min = torch.from_numpy(self.min).type_as(data).to(data.device) if torch.is_tensor(data) else self.min
        data = data * (max - min) + min
        return np.exp(data)


class MaxMinScaler():
    def __init__(self):
        self.min = 0.
        self.max = 1.

    def fit(self, data):
        data_o = np.array(data)
        self.max = data_o.max()
        self.min = data_o.min()

    def transform(self, data):
        max = torch.from_numpy(self.max).type_as(data).to(data.device) if torch.is_tensor(data) else self.max
        min = torch.from_numpy(self.min).type_as(data).to(data.device) if torch.is_tensor(data) else self.min
        return (data - min) / (max - min)

    def inverse_transform(self, data):
        # max = torch.from_numpy(self.max).type_as(data).to(data.device) if torch.is_tensor(data) else self.max
        # min = torch.from_numpy(self.min).type_as(data).to(data.device) if torch.is_tensor(data) else self.min
        return data * (self.max - self.min) + self.min


#data_train, data_val ,data_test = graph_normal(data_train, normal=normal), graph_normal(data_val, normal=normal), graph_normal(data_test, normal=normal)

def geo3(tgY, preY, max, min):
    tgY = tgY.float()
    preY = preY.float()
    
    if not isinstance(max, torch.Tensor):
        max = torch.tensor(max, dtype=tgY.dtype, device=tgY.device)
    if not isinstance(min, torch.Tensor):
        min = torch.tensor(min, dtype=tgY.dtype, device=tgY.device)
    
    scale = (max - min + 1e-12)
    tgY_denorm = tgY * scale + min
    preY_denorm = preY * scale + min
    
    tgY_rad = torch.deg2rad(tgY_denorm)
    preY_rad = torch.deg2rad(preY_denorm)
    
    dlon = preY_rad[:, 0] - tgY_rad[:, 0]
    dlat = preY_rad[:, 1] - tgY_rad[:, 1]
    
    a = (torch.sin(dlat / 2) ** 2 + 
         torch.cos(tgY_rad[:, 1]) * torch.cos(preY_rad[:, 1]) * torch.sin(dlon / 2) ** 2)
    
    a = torch.clamp(a, 0.0, 1.0)
    
    distance = 2 * torch.asin(torch.sqrt(a)) * 6371.0  # 公里
    
    return distance

def graph_normal(graphs, normal=2):
    if normal == 2:
        for g in graphs:

            X = np.concatenate((g["lm_X"], g["tg_X"]), axis=0)


            g["lm_X"] = (g["lm_X"] - X.min(axis=0)) / (X.max(axis=0) - X.min(axis=0) + 1e-12)
            g["tg_X"] = (g["tg_X"] - X.min(axis=0)) / (X.max(axis=0) - X.min(axis=0) + 1e-12)


            Y = np.concatenate((g["lm_Y"], g["tg_Y"]), axis=0)

            g["lm_Y"] = (g["lm_Y"] - Y.min(axis=0)) / (Y.max(axis=0) - Y.min(axis=0) + 1e-12)
            g["tg_Y"] = (g["tg_Y"] - Y.min(axis=0)) / (Y.max(axis=0) - Y.min(axis=0) + 1e-12)


            g["y_max"], g["y_min"] = Y.max(axis=0), Y.min(axis=0)


    elif normal == 1:
        for g in graphs:
            X = np.concatenate((g["lm_X"], g["tg_X"]), axis=0).squeeze(axis=1)

            g["lm_X"] = (g["lm_X"].squeeze(axis=1) - X.min(axis=0)) / (X.max(axis=0) - X.min(axis=0) + 1e-12)
            g["tg_X"] = (g["tg_X"].squeeze(axis=1) - X.min(axis=0)) / (X.max(axis=0) - X.min(axis=0) + 1e-12)

            Y = np.concatenate((g["lm_Y"], g["tg_Y"]), axis=0).squeeze(axis=1)
            g["lm_Y"] = (g["lm_Y"].squeeze(axis=1) - Y.min(axis=0)) / (Y.max(axis=0) - Y.min(axis=0) + 1e-12)
            g["tg_Y"] = (g["tg_Y"].squeeze(axis=1) - Y.min(axis=0)) / (Y.max(axis=0) - Y.min(axis=0) + 1e-12)
            g["center"] = (g["center"] - Y.min(axis=0)) / (Y.max(axis=0) - Y.min(axis=0) + 1e-12)


            g["y_max"], g["y_min"] = [1, 1], [0, 0]

    return graphs

def graph_normal2(train_graphs,val_graphs,test_graphs,normal=2):
    if normal == 2:
        X_all = np.concatenate((train_graphs[0]["lm_X"],train_graphs[0]["tg_X"]),axis=0)
        
        Y_all = np.concatenate((train_graphs[0]["lm_Y"],train_graphs[0]["tg_Y"]),axis=0)


        for i in range(1,len(train_graphs)):
            X_all = np.concatenate((X_all,train_graphs[i]["lm_X"],train_graphs[i]["tg_X"]),axis=0)
            Y_all = np.concatenate((Y_all,train_graphs[i]["lm_Y"],train_graphs[i]["tg_Y"]),axis=0)
            if i%100 ==1:
                print(i)
        for i in range(0,len(val_graphs)):
            X_all = np.concatenate((X_all,val_graphs[i]["lm_X"],val_graphs[i]["tg_X"]),axis=0)
            Y_all = np.concatenate((Y_all,val_graphs[i]["lm_Y"],val_graphs[i]["tg_Y"]),axis=0)
            if i%100 ==1:
                print(i)
        for i in range(0,len(test_graphs)):
            X_all = np.concatenate((X_all,test_graphs[i]["lm_X"],test_graphs[i]["tg_X"]),axis=0)
            Y_all = np.concatenate((Y_all,test_graphs[i]["lm_Y"],test_graphs[i]["tg_Y"]),axis=0)
            if i%100 ==1:
                print(i)
        X_all_max = X_all.max(axis=0)
        X_all_min = X_all.min(axis=0)
        Y_all_max = Y_all.max(axis=0)
        Y_all_min = Y_all.min(axis=0)
        i = 0
        for g in train_graphs:
            i+=1
            if i%100 ==1 :
                print(i)
            g["lm_X"] = (g["lm_X"] - X_all_min) / (X_all_max - X_all_min + 1e-12)
            g["tg_X"] = (g["tg_X"] - X_all_min) / (X_all_max - X_all_min + 1e-12)
            g["lm_Y"] = (g["lm_Y"] - Y_all_min) / (Y_all_max - Y_all_min + 1e-12)
            g["tg_Y"] = (g["tg_Y"] - Y_all_min) / (Y_all_max - Y_all_min + 1e-12)
            g["y_max"], g["y_min"] = Y_all_max, Y_all_min
        for g in val_graphs:
            i+=1
            if i%100 ==1 :
                print(i)
            g["lm_X"] = (g["lm_X"] - X_all_min) / (X_all_max - X_all_min + 1e-12)
            g["tg_X"] = (g["tg_X"] - X_all_min) / (X_all_max - X_all_min + 1e-12)
            g["lm_Y"] = (g["lm_Y"] - Y_all_min) / (Y_all_max - Y_all_min + 1e-12)
            g["tg_Y"] = (g["tg_Y"] - Y_all_min) / (Y_all_max - Y_all_min + 1e-12)
            g["y_max"], g["y_min"] = Y_all_max, Y_all_min
        for g in test_graphs:
            i+=1
            if i%100 ==1 :
                print(i)
            g["lm_X"] = (g["lm_X"] - X_all_min) / (X_all_max - X_all_min + 1e-12)
            g["tg_X"] = (g["tg_X"] - X_all_min) / (X_all_max - X_all_min + 1e-12)
            g["lm_Y"] = (g["lm_Y"] - Y_all_min) / (Y_all_max - Y_all_min + 1e-12)
            g["tg_Y"] = (g["tg_Y"] - Y_all_min) / (Y_all_max - Y_all_min + 1e-12)
            g["y_max"], g["y_min"] = Y_all_max, Y_all_min


    return train_graphs,val_graphs,train_graphs

def get_data_generator(opt, data_train, data_val, data_test,normal=2):
    # load data
    data_train = np.array(data_train)
    data_val = np.array(data_val)
    data_test = np.array(data_test)
    origindata_train = copy.deepcopy(data_train)
    origindata_val = copy.deepcopy(data_val)
    origindata_test = copy.deepcopy(data_test)

    data_train, data_val ,data_test = graph_normal(data_train, normal=normal), graph_normal(data_val, normal=normal), graph_normal(data_test, normal=normal)


    return data_train, data_val, data_test,origindata_train,origindata_test,origindata_val



def geo(tgY,preY):
    # lng1,lat1,lng2,lat2 = (120.12802999999997,30.28708,115.86572000000001,28.7427)
    tgY =tgY.tolist()
    preY =preY.tolist()
    Ylen = len(tgY)
    dis = []
    for i in range(Ylen):
        lng1, lat1, lng2, lat2 = map(radians, [float(tgY[i][0]), float(tgY[i][1]), float(preY[i][0]), float(preY[i][1])])
        dlon = lng2 - lng1
        dlat = lat2 - lat1
        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        distance = 2 * asin(sqrt(a)) * 6371 * 1000
        distance = round(distance / 1000, 3)
        dis.append(distance)
    return dis

def geo2(tgY,preY,max,min):
    # lng1,lat1,lng2,lat2 = (120.12802999999997,30.28708,115.86572000000001,28.7427) # longtitude first latitude second.

    tgY[:, 0] = tgY[:, 0] * (max[0] - min[0] +1e-12) + min[0]
    tgY[:, 1] = tgY[:, 1] * (max[1] - min[1] +1e-12) + min[1]
    preY[:, 0] = preY[:, 0] * (max[0] - min[0] +1e-12) + min[0]
    preY[:, 1] = preY[:, 1] * (max[1] - min[1] +1e-12) + min[1]




    #preY = preY * (max - min + 1e-12) + min
    tgY = torch.deg2rad(tgY)
    preY = torch.deg2rad(preY)

    dlon = preY[:,0] - tgY[:,0]
    dlat = preY[:,1] - tgY[:,1]

    a = torch.sin(dlat / 2) ** 2 + torch.cos(tgY[:,1]) * torch.cos(preY[:,1]) * torch.sin(dlon / 2) ** 2
    distance = 2 * torch.asin(torch.sqrt(a)) * 6371 * 1000

    distance = torch.round(distance / 1000, decimals=3)

    return distance


def geodistance(lng1, lat1, lng2, lat2):
    # lng1,lat1,lng2,lat2 = (120.12802999999997,30.28708,115.86572000000001,28.7427)
    lng1, lat1, lng2, lat2 = map(radians, [float(lng1), float(lat1), float(lng2), float(lat2)])
    dlon = lng2 - lng1
    dlat = lat2 - lat1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    distance = 2 * asin(sqrt(a)) * 6371 * 1000
    distance = round(distance / 1000, 3)
    return distance

def dis_loss(y, y_pred, max, min):
    y[:, 0] = y[:, 0] * (max[0] - min[0] +1e-12 )
    y[:, 1] = y[:, 1] * (max[1] - min[1]+1e-12 )
    y_pred[:, 0] = y_pred[:, 0] * (max[0] - min[0]+ 1e-12 )
    y_pred[:, 1] = y_pred[:, 1] * (max[1] - min[1] +1e-12 )
    

    distance = torch.sqrt((((y - y_pred) * 100) * ((y - y_pred) * 100)).sum(dim=1))
    return distance

# save checkpoint of model
def save_cpt(model, optim, epoch, save_path):
    """
    save checkpoint, for inference/re-training
    :return:
    """
    model.eval()
    torch.save(
        {
            'epoch': epoch,
            'model_state_dict': model.state_dict(),
            'optimizer_state_dict': optim.state_dict()
        },
        save_path
    )

def get_adjancy(func, delay, hop, nodes):
    cuda = True if torch.cuda.is_available() else False
    Tensor = torch.cuda.FloatTensor if cuda else torch.FloatTensor

    hops = []
    delays = []
    x1 = []
    x2 = []
    for i in range(len(nodes) - 1):
        for j in range(i + 1, len(nodes)):
            delays.append(delay[i, j])
            hops.append(hop[i, j])
            x1.append(nodes[i].cpu().detach().numpy())
            x2.append(nodes[j].cpu().detach().numpy())
    dis = func(Tensor(delays), Tensor(hops), Tensor(x1), Tensor(x2))
    A = torch.zeros_like(delay)
    index = 0
    for i in range(len(nodes) - 1):
        for j in range(i + 1, len(nodes)):
            A[i, j] = dis[index]
            index += 1
    return A


def print_model_parm_nums(model, str):
    total_num = sum([param.nelement() for param in model.parameters()])
    print('{} params: {}'.format(str, total_num))


def init_network_weights(net, std=0.1):
    for m in net.modules():
        if isinstance(m, nn.Linear):
            nn.init.normal_(m.weight, mean=0, std=std)
            # nn.init.constant_(m.bias, val=0)


def get_device(tensor):
    device = torch.device("cpu")
    if tensor.is_cuda:
        device = tensor.get_device()
    return device


def get_MSE(pred, real):
    return np.mean(np.power(real - pred, 2))


def get_MAE(pred, real):
    return np.mean(np.abs(real - pred))


def draw_cdf(ds_sort):
    last, index = min(ds_sort), 0
    x = []
    y = []
    while index < len(ds_sort):
        x.append([last, ds_sort[index]])
        y.append([index / len(ds_sort), index / len(ds_sort)])

        if index < len(ds_sort):
            last = ds_sort[index]
        index += 1
    plt.figure(figsize=(8, 6))
    plt.plot(np.array(x).reshape(-1, 1).squeeze(),
             np.array(y).reshape(-1, 1).squeeze(),
             c='k',
             lw=2,
             ls='-')
    plt.xlabel('Geolocation Error(km)')
    plt.ylabel('Cumulative Probability')
    plt.grid()
    plt.show()
