# -*- coding: utf-8 -*-
import torch.nn as nn
from lib.utils import *
import argparse
import numpy as np
import random, os
from lib.model import GAT
import copy
from torch.utils.tensorboard import SummaryWriter
import dgl
import torch.nn.functional as F

import matplotlib.pyplot as plt

from lib.utils import get_data_generator, dis_loss, geo2, save_cpt, init_network_weights,geo3

parser = argparse.ArgumentParser()
# parameters of initializing
parser.add_argument('--seed', type=int, default=1234, help='manual seed')
parser.add_argument('--model_name', type=str, default='GAT')
parser.add_argument('--dataset', type=str, default='Seoul', choices=["Shanghai", "New_York", "Los_Angeles","Hongkong","Tokyo","Seoul"],
                    help='which dataset to use')

# parameters of training
parser.add_argument("--beta", type=float, default=0.01, help="L0 regularization beta")
parser.add_argument('--beta1', type=float, default=0.9)
parser.add_argument('--beta2', type=float, default=0.999)

parser.add_argument('--lr', type=float, default=0.002)
parser.add_argument('--harved_epoch', type=int, default=5)
parser.add_argument('--early_stop_epoch', type=int, default=50)
parser.add_argument('--saved_epoch', type=int, default=5)
parser.add_argument('--load_epoch', type=int, default=100)

parser.add_argument('--device', type=str, default='cuda:0', help='Use gpu device(cuda:0、cuda:1、cpu)')

# parameters of GAT model
parser.add_argument('--dim_in', type=int, default=9, choices=[51, 30, 29,9], help="51 if Shanghai / 30 else")
parser.add_argument('--num_hidden', type=int, default=128, help="GAT hidden dimension")
parser.add_argument('--num_heads', type=str, default='2,2,2', help="GAT attention heads per layer (comma separated)")
parser.add_argument('--feat_drop', type=float, default=0, help="Feature dropout rate")
parser.add_argument('--attn_drop', type=float, default=0, help="Attention dropout rate")
parser.add_argument('--alpha', type=float, default=0.2, help="LeakyReLU alpha")
parser.add_argument('--bias_l0', type=float, default=0.0, help="L0 regularization bias")
parser.add_argument('--num_layers', type=int, default=1, help="Number of GAT hidden layers")
parser.add_argument('--residual', action='store_true', default=True, help="Use residual connection")
parser.add_argument('--l0', type=int, default=1, help="Use L0 regularization (1=yes, 0=no)")

opt = parser.parse_args()

opt.num_heads = list(map(int, opt.num_heads.split(',')))

if opt.seed:
    print("Random Seed: ", opt.seed)
    random.seed(opt.seed)
    torch.manual_seed(opt.seed)
    if torch.cuda.is_available() and 'cuda' in opt.device:
        torch.cuda.manual_seed(opt.seed)
        torch.cuda.manual_seed_all(opt.seed)
    
    torch.manual_seed(opt.seed)
    os.environ['PYTHONHASHSEED'] = str(opt.seed)
    np.random.seed(opt.seed)

    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.enabled = True

    dgl.random.seed(opt.seed)


torch.set_printoptions(threshold=float('inf'))


warnings.filterwarnings('ignore')

if 'cuda' in opt.device:
    gpu_id = int(opt.device.split(':')[-1])
    device = torch.device(opt.device)
else:
    device = torch.device('cpu')
print("Dataset: ", opt.dataset)

cuda = True if torch.cuda.is_available() else False
Tensor = torch.cuda.FloatTensor if cuda else torch.FloatTensor

'''load data'''
train_data = np.load("./datasets/{}/Clustering_s1234_graph70_train.npz".format(opt.dataset),
                     allow_pickle=True)
val_data = np.load("./datasets/{}/Clustering_s1234_graph70_val.npz".format(opt.dataset),
                     allow_pickle=True)
test_data = np.load("./datasets/{}/Clustering_s1234_graph70_test.npz".format(opt.dataset),
                    allow_pickle=True)

train_data, val_data, test_data = train_data["data"], val_data['data'], test_data["data"]
print("data loaded.")

train_data, val_data, test_data, ori_train_data, ori_val_data, ori_test_data = get_data_generator(
    opt, train_data, val_data, test_data, normal=2)

'''record loss result'''
log_dir = f"asset/log/{opt.dataset}_GAT.log"
os.makedirs(os.path.dirname(log_dir), exist_ok=True)
writer = SummaryWriter(log_dir=log_dir)

'''Build GAT model'''
model = GAT(
    in_dim=opt.dim_in,
    num_hidden=opt.num_hidden,
    num_classes=2,
    heads=opt.num_heads,
    activation=F.elu,
    feat_drop=opt.feat_drop,
    attn_drop=opt.attn_drop,
    alpha=opt.alpha,
    bias_l0=opt.bias_l0,
    num_layers=opt.num_layers,
    residual=opt.residual,
    l0=opt.l0
)

print(opt)
print("Original GAT model initialized.")
print(f"Model structure: {model}")

def init_gat_weights(m):
    if isinstance(m, nn.Linear):
        nn.init.xavier_normal_(m.weight.data, gain=1.414)
        if m.bias is not None:
            nn.init.zeros_(m.bias.data)
    elif isinstance(m, nn.Parameter):
        nn.init.xavier_normal_(m.data, gain=1.414)
    elif isinstance(m, nn.BatchNorm1d):
        nn.init.ones_(m.weight.data)
        nn.init.zeros_(m.bias.data)

model.apply(init_gat_weights)

model = model.to(device)

'''initiate criteria and optimizer'''
lr = opt.lr
optimizer = torch.optim.Adam(model.parameters(), lr=lr, betas=(opt.beta1, opt.beta2))
torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=0.5)

def build_graph(lm_X, tg_X, landmark_rtts):
    num_landmarks = len(lm_X)
    num_nodes = num_landmarks + 1
    
    tg_X = tg_X.squeeze(0)
    node_features = np.vstack([tg_X, lm_X])
    
    src_nodes = [0] * num_landmarks + list(range(1, num_landmarks + 1))
    dst_nodes = list(range(1, num_landmarks + 1)) + [0] * num_landmarks
    
    rtt_np = np.asarray(landmark_rtts, dtype=np.float32)

    edge_weights = np.exp(-rtt_np + 1e-12).tolist()
    edge_weights += edge_weights
    
    g = dgl.graph((src_nodes, dst_nodes)).to(device)
    
    g = dgl.add_self_loop(g)
    
    self_loop_weight = 0.0

    self_loop_weights = [self_loop_weight] * num_nodes

    edge_weights.extend(self_loop_weights)
    
    g.ndata['feat'] = torch.FloatTensor(node_features).to(device).clone()
    g.edata['rtt'] = torch.FloatTensor(edge_weights).unsqueeze(1).to(device).clone()
      
    return g, node_features

if __name__ == '__main__':
    losses = [np.inf]
    no_better_epoch = 0
    early_stop_epoch = 0


    val_mse_list = []
    val_rmse_list = []
    val_mae_list = []
    val_med_list = []
    test_mse_list = []
    test_rmse_list = []
    test_mae_list = []
    test_med_list = []
    
    best_val_test_error_list = []
    best_val_mae_value = np.inf
    best_val_epoch = 0

    for epoch in range(2000):
        print("\n" + "="*50)
        print("epoch {}/2000".format(epoch))
        print("="*50)
        
        total_loss, total_mae, train_num, MSE_loss, L0_loss = 0.0, 0.0, 0, 0.0, 0.0
        
        ## ----------- Train
        model.train()
        count = 0
        for i in range(len(train_data)):
            count += 1
            data = train_data[i]
            

            lm_X = data["lm_X"]
            tg_X = data["tg_X"]
            tg_Y = data["tg_Y"]
            y_max = data["y_max"]
            y_min = data["y_min"]
            landmark_rtts = data["landmark_rtts"]
            

            if len(landmark_rtts) == 0:
                print(f"Warning: The {i}th training sample has no RTT data, skipping")
                continue
            
            try:
                g, node_features = build_graph(lm_X, tg_X, landmark_rtts)
            except Exception as e:
                print(f"Error building graph (training sample {i}): {e}")
                continue
            

            inputs = Tensor(node_features).clone()
            
            optimizer.zero_grad()
            

            y_pred = model(g, inputs)
            

            y_pred_target = y_pred[0:1].clone()
            

            tg_Y_tensor = Tensor(tg_Y).clone().to(device)
            distance = dis_loss(tg_Y_tensor, y_pred_target, y_max, y_min)
            mse_loss = (distance ** 2).sum()
            

            l0_loss = 0.0
            if opt.l0 == 1:
                for layer in model.gat_layers:
                    if hasattr(layer, 'loss'):

                        if isinstance(layer.loss, torch.Tensor):

                            layer_loss = layer.loss.to(device)
                            l0_loss += layer_loss.item()
                        else:
                            l0_loss += float(layer.loss)
            
            total_batch_loss = mse_loss + opt.beta * l0_loss
            
            try:
                total_batch_loss.backward()
                optimizer.step()
            except Exception as e:
                print(f"Error during backpropagation (training sample {i}): {e}")
                continue
            
            MSE_loss += mse_loss.item()

            L0_loss += l0_loss

            total_loss += total_batch_loss.item()

            total_mae += distance.sum().item()
            train_num += len(tg_Y)
        
        if train_num == 0:
            print("Warning: No valid training data!")
            continue
        

        avg_total_loss = total_loss / train_num
        avg_mse_loss = MSE_loss / train_num
        avg_l0_loss = L0_loss / train_num if train_num > 0 else 0.0
        avg_mae = total_mae / train_num
        

        writer.add_scalar('mse_loss/Train', avg_mse_loss, epoch)
        writer.add_scalar('l0_loss/Train', avg_l0_loss, epoch)
        writer.add_scalar('total_loss/Train', avg_total_loss, epoch)
        writer.add_scalar('mae/Train', avg_mae, epoch)
        
        print("train: total_loss: {:.4f} mae: {:.4f} mse_loss: {:.4f} l0_loss: {:.4f}".format(
            avg_total_loss, avg_mae, avg_mse_loss, avg_l0_loss))

        # ----------- Validation
        val_total_mse, val_total_mae, val_num = 0.0, 0.0, 0
        val_dislist = []
        
        model.eval()
        with torch.no_grad():
            for i in range(len(val_data)):
                data = val_data[i]
                
                lm_X = data["lm_X"]
                tg_X = data["tg_X"]
                tg_Y = data["tg_Y"]
                y_max = data["y_max"]
                y_min = data["y_min"]
                landmark_rtts = data["landmark_rtts"]
                
                if len(landmark_rtts) == 0:
                    print(f"Warning: The {i}th validation sample has no RTT data, skipping")
                    continue
                

                try:
                    g, node_features = build_graph(lm_X, tg_X, landmark_rtts)
                except Exception as e:
                    print(f"Error building graph (validation sample {i}): {e}")
                    continue
                
                inputs = Tensor(node_features).clone()
                

                y_pred = model(g, inputs)
                y_pred_target = y_pred[0:1].clone()
                

                val_distance = geo2(Tensor(tg_Y).clone().to(device), y_pred_target, y_max, y_min)
                val_diss = val_distance.cpu().numpy()
                
                if val_diss[0] == 0.0 and len(val_diss) == 1:
                    continue
                

                val_dislist.extend(val_distance.cpu().detach().numpy())
                val_num += len(tg_Y)
                val_total_mse += (val_distance ** 2).sum().item()
                val_total_mae += val_distance.sum().item()
            
            if val_num > 0:
                val_avg_mse = val_total_mse / val_num
                val_avg_rmse = np.sqrt(val_avg_mse)
                val_avg_mae = val_total_mae / val_num
                
                writer.add_scalar('MAE/Val', val_avg_mae, epoch)
                writer.add_scalar('MSE/Val', val_avg_mse, epoch)
                writer.add_scalar('RMSE/Val', val_avg_rmse, epoch)
                
                print("val: mse: {:.4f}  rmse: {:.4f}  mae: {:.4f}".format(val_avg_mse, val_avg_rmse, val_avg_mae))
                val_dislist_sorted = sorted(val_dislist)
                val_median = val_dislist_sorted[int(len(val_dislist_sorted) / 2)] if val_dislist_sorted else 0
                print('val median:', val_median)

                val_mse_list.append(val_avg_mse)
                val_rmse_list.append(val_avg_rmse)
                val_mae_list.append(val_avg_mae)
                val_med_list.append(val_median)
            else:
                print("val: No valid data")
                val_avg_mae = np.inf


            if epoch > 0 and epoch % opt.saved_epoch == 0 and epoch < 1000:
                savepath = f"asset/model/{opt.dataset}_GAT_{epoch}.pth"
                save_cpt(model, optimizer, epoch, savepath)
                print("Save checkpoint!")

            batch_metric = val_avg_mae if val_num > 0 else np.inf
            if batch_metric <= np.min(losses):
                no_better_epoch = 0
                early_stop_epoch = 0
                print("Better MAE in epoch {}: {:.4f}".format(epoch, batch_metric))
            else:
                no_better_epoch += 1
                early_stop_epoch += 1

            losses.append(batch_metric)

            # ----------- Test
            test_total_mse, test_total_mae, test_num = 0.0, 0.0, 0
            test_dislist = []
            
            for i in range(len(test_data)):
                data = test_data[i]
                
                lm_X = data["lm_X"]
                tg_X = data["tg_X"]
                tg_Y = data["tg_Y"]
                y_max = data["y_max"]
                y_min = data["y_min"]
                landmark_rtts = data["landmark_rtts"]
                
                if len(landmark_rtts) == 0:
                    print(f"Warning: The {i}th test sample has no RTT data, skipping")
                    continue
                
                try:
                    g, node_features = build_graph(lm_X, tg_X, landmark_rtts)
                except Exception as e:
                    print(f"Error building graph (test sample {i}): {e}")
                    continue
                
                inputs = Tensor(node_features).clone()
                

                y_pred = model(g, inputs)
                y_pred_target = y_pred[0:1].clone()
                
                test_distance = geo2(Tensor(tg_Y).clone().to(device), y_pred_target, y_max, y_min)
                test_diss = test_distance.cpu().numpy()
                
                if test_diss[0] == 0.0 and len(test_diss) == 1:
                    continue
                
                test_dislist.extend(test_distance.cpu().detach().numpy())
                test_num += len(tg_Y)
                test_total_mse += (test_distance ** 2).sum().item()
                test_total_mae += test_distance.sum().item()
            
            if test_num > 0:
                test_avg_mse = test_total_mse / test_num
                test_avg_rmse = np.sqrt(test_avg_mse)
                test_avg_mae = test_total_mae / test_num
                
                writer.add_scalar('MAE/Test', test_avg_mae, epoch)
                writer.add_scalar('MSE/Test', test_avg_mse, epoch)
                writer.add_scalar('RMSE/Test', test_avg_rmse, epoch)
                
                print("Test: mse: {:.4f}  rmse: {:.4f}  mae: {:.4f}".format(test_avg_mse, test_avg_rmse, test_avg_mae))
                test_dislist_sorted = sorted(test_dislist)
                test_median = test_dislist_sorted[int(len(test_dislist_sorted) / 2)] if test_dislist_sorted else 0
                print('test median:', test_median)
                test_mse_list.append(test_avg_mse)
                test_rmse_list.append(test_avg_rmse)
                test_mae_list.append(test_avg_mae)
                test_med_list.append(test_median)
                

                if val_avg_mae < best_val_mae_value:
                    best_val_mae_value = val_avg_mae
                    best_val_epoch = epoch
                    best_val_test_error_list = test_dislist.copy()
                    print(f"Updated best val MAE: {best_val_mae_value:.4f} at epoch {epoch}, saved test error list with {len(test_dislist)} samples")
            else:
                print("Test: No valid data")

        if no_better_epoch % opt.harved_epoch == 0 and no_better_epoch != 0:
            lr /= 2
            print("learning rate changes to {}!".format(lr))
            optimizer = torch.optim.Adam(model.parameters(), lr=lr, betas=(opt.beta1, opt.beta2))
            no_better_epoch = 0

        if early_stop_epoch == opt.early_stop_epoch:
            savepath = f"asset/model/{opt.dataset}_GAT_best_{epoch}.pth"
            save_cpt(model, optimizer, epoch, savepath)
            print("Save best checkpoint!")

            log_file = f"asset/log/{opt.dataset}_GAT.txt"
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            f = open(log_file, 'a')
            f.write(f"\n*********Best epoch={epoch}*********\n")
            f.write(f"Model config: {opt}\n")
            if test_num > 0:
                f.write("test: mse: {:.3f}\trmse: {:.3f}\tmae: {:.3f}\tmedian: {:.3f}\n".format(
                    test_avg_mse, test_avg_rmse, test_avg_mae, test_median))
            if val_num > 0:
                f.write("val: mse: {:.3f}\trmse: {:.3f}\tmae: {:.3f}\tmedian: {:.3f}\n".format(
                    val_avg_mse, val_avg_rmse, val_avg_mae, val_median))
            f.close()
            break

    writer.close()
    val_mae_best = min(val_mae_list)
    min_indice = [idx for idx, mae in enumerate(val_mae_list) if mae == val_mae_best]
    print('---------------------------Final Best Results----------------------------')
    print('Test MSE Error:')
    print(test_mse_list[min_indice[0]])
    print('Test RMSE Error:')
    print(test_rmse_list[min_indice[0]])
    print('Test MAE Error:')
    print(test_mae_list[min_indice[0]])
    print('Test MED Error:')
    print(test_med_list[min_indice[0]])

    filepath = os.path.split(os.path.realpath(__file__))[0]
    from time import time

    stamp = int(time())
    result_path1 = filepath + '/output/' + str(stamp) + '_loss.txt'

    if not os.path.exists("./output/"):
        os.makedirs("./output/")

    fw1 = open(result_path1, 'w')
    perf_str = 'seed=%s,model_name=%s,dataset=%s,beta=%s,beta1=%s,beta2=%s,lr=%s, harved_epoch=%s,early_stop_epoch=%s,saved_epoch=%s,load_epoch=%s, dim_in=%s,num_hidden=%s,num_heads=%s,feat_drop=%s,attn_drop=%s,alpha=%s,bias_l0=%s,num_layers=%s,residual=%s,l0=%s,device=%s\n' \
               % (opt.seed, opt.model_name, opt.dataset, opt.beta, opt.beta1, opt.beta2,
                  opt.lr, opt.harved_epoch, opt.early_stop_epoch, opt.saved_epoch,
                  opt.load_epoch, opt.dim_in, opt.num_hidden ,opt.num_heads ,opt.feat_drop ,opt.attn_drop, opt.alpha ,opt.bias_l0, opt.num_layers, opt.residual, opt.l0,opt.device)
    fw1.write(perf_str)
    fw1.write('Best Epoch:'+ str(min_indice[0])+'\n')
    fw1.write('Val MAE Error:'+'\n')
    fw1.write(str(val_mae_best)+'\n')
    fw1.write('Test MSE Error:'+'\n')
    fw1.write(str(test_mse_list[min_indice[0]]) + '\n')
    fw1.write('Test RMSE Error:'+'\n')
    fw1.write(str(test_rmse_list[min_indice[0]]) + '\n')
    fw1.write('Test MAE Error:'+'\n')
    fw1.write(str(test_mae_list[min_indice[0]]) + '\n')
    fw1.write('Test MED Error:'+'\n')
    fw1.write(str(test_med_list[min_indice[0]]) + '\n')
    

    fw1.write('\n' + '='*60 + '\n')
    fw1.write('Best Validation MAE: ' + str(best_val_mae_value) + ' (Epoch: ' + str(best_val_epoch) + ')\n')
    fw1.write('Corresponding Test Error List (raw errors for each test sample):\n')
    fw1.write('Total number of test samples: ' + str(len(best_val_test_error_list)) + '\n')
    fw1.write('Test Error List (km):\n')
    for idx, error in enumerate(best_val_test_error_list):
        fw1.write(str(error) + ',')
    fw1.write('\n' + '='*60 + '\n')
    fw1.close()
    
    print("Training finished!")
    print(f"Best validation MAE: {best_val_mae_value:.4f} at epoch {best_val_epoch}")
    print(f"Saved {len(best_val_test_error_list)} test errors to output file")
