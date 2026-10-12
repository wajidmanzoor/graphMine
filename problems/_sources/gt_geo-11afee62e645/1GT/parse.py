from models import *
from ours import *

##我修改的代码
def parse_method(method, args,  d, aggregator_type,edge_input_dim,edge_hidden_dim,
                  num_step_message_passing,gconv_dp,edge_dp,nn_dp1,device):#C表示类别
    if method == 'mpnn':
        model = MPNN(aggregator_type=aggregator_type,
                     node_in_feats=d,#不知道对不对，先这么写着
                     node_hidden_dim= args.hidden_channels,
                    edge_input_dim = edge_input_dim,
                    edge_hidden_dim = edge_hidden_dim,
                    num_step_message_passing= num_step_message_passing,
                    gconv_dp=gconv_dp,
                    edge_dp=edge_dp,
                    nn_dp1=nn_dp1)
    elif method == 'ours':
        if args.use_graph:
            mpnn=parse_method(args.backbone, args, d, aggregator_type,edge_input_dim,edge_hidden_dim,
                  num_step_message_passing,gconv_dp,edge_dp,nn_dp1,device)
            model = SGFormer1(d, args.hidden_channels, num_layers=args.ours_layers, alpha=args.alpha, dropout=args.ours_dropout, num_heads=args.num_heads,
                     use_bn=args.use_bn, use_residual=args.ours_use_residual, use_graph=args.use_graph, use_weight=args.ours_use_weight, use_act=args.ours_use_act, graph_weight=args.graph_weight, gnn=mpnn, aggregate=args.aggregate)
        #目前修改到这里，接下来需要修改SGFormer
        else:
            model = Ours(d, args.hidden_channels, c, num_layers=args.num_layers, alpha=args.alpha, dropout=args.dropout, num_heads=args.num_heads,
                     use_bn=args.use_bn, use_residual=args.ours_use_residual, use_graph=args.use_graph, use_weight=args.ours_use_weight, use_act=args.ours_use_act, graph_weight=args.graph_weight, aggregate=args.aggregate).to(device)
    else:
        raise ValueError(f'Invalid method {method}')
    return model


def parser_add_main_args(parser):
    # dataset and evaluation
    parser.add_argument('--device', type=int, default=0,
                        help='which gpu to use if any (default: 0)')#必定选择的参数
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--cpu', action='store_true')#不选
    parser.add_argument('--epochs', type=int, default=1000)#轮数，可选择的参数
    # model
    parser.add_argument('--method', type=str, default='ours')#方法，必定选择的参数
    parser.add_argument('--hidden_channels', type=int, default=32)#输入到SGFormer的节点隐藏层大小，一般必选[32,64,128,256]
    parser.add_argument('--alpha', type=float, default=0.5,
                        help='weight for residual link')#残差链接的比率，可以用来调参[0.3,0.5,0.7]
    parser.add_argument('--use_bn', action='store_true', help='use layernorm') #可选择的参数，基本上也属于必选择参数[YES ,NO]
    parser.add_argument('--use_residual', action='store_true',
                        help='use residual link for each GNN layer')#基本没用
    parser.add_argument('--use_graph', action='store_true', help='use pos emb')#必定选择的参数
    parser.add_argument('--use_weight', action='store_true',
                        help='use weight for GNN convolution')#可选择的参数,基本上不选，一般用our_use_weight
    
    # training
    parser.add_argument('--lr', type=float, default=0.01)#学习率，可以用来调参
    parser.add_argument('--weight_decay', type=float, default=5e-4)#权重衰减，可选择的参数[5e-4,1e-3,5e-3]
    parser.add_argument('--dropout', type=float, default=0.5) #可选择的参数,基本上没啥用，不用调了。

    # ours
    parser.add_argument('--patience', type=int, default=200,
                        help='early stopping patience.')#早停率
    parser.add_argument('--graph_weight', type=float,
                        default=0.8, help='graph weight.') #必选参数，重点！[0.6,0.7,0.8,0.9,0.95]
    parser.add_argument('--ours_weight_decay', type=float,default=5e-4,
                         help='Ours\' weight decay. Default to weight_decay.')#权重衰减，建议使用[5e-3,0.001,5e-4]
    parser.add_argument('--ours_use_weight', action='store_true', help='use weight for trans convolution') #是否使用V的权重，可以使用。建议使用--ours_use_weight，可调参
    parser.add_argument('--ours_use_residual', action='store_true', help='use residual link for each trans layer')#是否使用残差连接，建议使用
    parser.add_argument('--ours_use_act', action='store_true', help='use activation for each trans layer')#是否使用激活函数？可选可不选[Yes , No]
    parser.add_argument('--backbone', type=str, default='mpnn',
                        help='Backbone.')#使用的GNN方法
    parser.add_argument('--ours_layers', type=int, default=2,help='gnn layer.')#注意力机制的层数,可调[1,2,3]
    parser.add_argument('--ours_dropout', type=float, 
                        help='gnn dropout.')#MLP和Transformer的随机置0比率，可以调参[0,0.1,0.2,0.3]
    parser.add_argument('--aggregate', type=str, default='add',
                        help='aggregate type, add or cat.')#SGFormer中的聚合方式
    parser.add_argument('--num_heads',type=int,default=1,help='nums of head')#可选择的参数
    #parser.add_argument('--no_feat_norm',action='store_true')
    
    #我修改的代码
    parser.add_argument('--node_embedding_size', type=int, default=128)#初始化的节点特征维度
    parser.add_argument('--node_hidden_size', type=int, default=128)#节点隐藏层的维度，可调参，也可不调
    parser.add_argument('--edge_hidden_size', type=int, default=4)#边特征隐藏层的维度，可调
    parser.add_argument('--fc_size', type=int, default=2) #貌似用不上，这个不调了
    parser.add_argument('--init_method', nargs='?', default='xavier_normal',
                        help='1. tnormal for truncated_normal_initializer, 2.uniform for random_uniform_initializer 3.normal for random_normal_initializer, 4.xavier_normal, 5. xavier_uniform, 6.he_normal, 7.he_uniform')
    #这个貌似也没什么用，不调了
    parser.add_argument('--print_flag', type=int, default=1)#是否打印出来，这个没调的必要
    parser.add_argument('--num_step_message_passing', type=int, default=3)  # GNN的几层卷积，可调。[3,4,5]
    parser.add_argument('--regs', type=float, default=0.0005)  # l2正则化选项貌似也没有用到，不用调了
    parser.add_argument('--gnn_dropout', type=float, default=0.0)  # MPNN的dropout比率，可调[0,0.1,0.2]
    parser.add_argument('--edge_dropout', type=float, default=0.0)  # MPNN边特征dropout比率[0,0.1,0.2]
    parser.add_argument('--nn_dropout1', type=float, default=0.0)  # 实际上nn_dropout1没有用上，可以不调，不用管
    parser.add_argument('--nn_dropout2', type=float, default=0.0)  # 没有用处，不用管
    parser.add_argument('--aggregator_type', type=str, default='sum',
                        help='max,sum,mean')  # mean”、“sum”、“max”、“min”和“lstm” #MPNN的聚合类型，可以调参
    parser.add_argument('--loss1_weight', type=float, default=1)  # 经度和纬度重要性比例，建议不调，因为没有权重的差异！

def parser_add_default_args(args):
    if args.method=='ours':
        if args.ours_weight_decay is None:
            args.ours_weight_decay=args.weight_decay
        if args.ours_dropout is None:
            args.ours_dropout=args.dropout
