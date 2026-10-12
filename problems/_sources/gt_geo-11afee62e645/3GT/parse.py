from models import *
from ours import *


def parse_method(method, args,  d, aggregator_type,edge_input_dim,edge_hidden_dim,
                  num_step_message_passing,gconv_dp,edge_dp,nn_dp1,device):
    if method == 'mpnn':
        model = MPNN(aggregator_type=aggregator_type,
                     node_in_feats=d,
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
                     use_bn=args.use_bn, use_residual=args.ours_use_residual, use_graph=args.use_graph, use_weight=args.ours_use_weight, use_act=args.ours_use_act, graph_weight=args.graph_weight, gnn=mpnn, aggregate=args.aggregate,
                    edge_input_dim = edge_input_dim,
                    edge_hidden_dim = edge_hidden_dim,
                    num_step_message_passing= num_step_message_passing,
                    gconv_dp=gconv_dp,
                    edge_dp=edge_dp,
                    nn_dp1=nn_dp1)

        else:
            model = Ours(d, args.hidden_channels, c, num_layers=args.num_layers, alpha=args.alpha, dropout=args.dropout, num_heads=args.num_heads,
                     use_bn=args.use_bn, use_residual=args.ours_use_residual, use_graph=args.use_graph, use_weight=args.ours_use_weight, use_act=args.ours_use_act, graph_weight=args.graph_weight, aggregate=args.aggregate).to(device)
    else:
        raise ValueError(f'Invalid method {method}')
    return model


def parser_add_main_args(parser):
    # dataset and evaluation
    parser.add_argument('--device', type=int, default=0,
                        help='which gpu to use if any (default: 0)')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--cpu', action='store_true')
    parser.add_argument('--epochs', type=int, default=1000)
    # model
    parser.add_argument('--method', type=str, default='ours')
    parser.add_argument('--hidden_channels', type=int, default=32)
    parser.add_argument('--alpha', type=float, default=0.5,
                        help='weight for residual link')
    parser.add_argument('--use_bn', action='store_true', help='use layernorm')
    parser.add_argument('--use_residual', action='store_true',
                        help='use residual link for each GNN layer')
    parser.add_argument('--use_graph', action='store_true', help='use pos emb')
    parser.add_argument('--use_weight', action='store_true',
                        help='use weight for GNN convolution')

    parser.add_argument('--lr', type=float, default=0.01)
    parser.add_argument('--weight_decay', type=float, default=5e-4)
    parser.add_argument('--dropout', type=float, default=0.5)
    # ours
    parser.add_argument('--patience', type=int, default=200,
                        help='early stopping patience.')
    parser.add_argument('--graph_weight', type=float,
                        default=0.8, help='graph weight.')
    parser.add_argument('--ours_weight_decay', type=float,default=5e-4,
                         help='Ours\' weight decay. Default to weight_decay.')
    parser.add_argument('--ours_use_weight', action='store_true', help='use weight for trans convolution')
    parser.add_argument('--ours_use_residual', action='store_true', help='use residual link for each trans layer')
    parser.add_argument('--ours_use_act', action='store_true', help='use activation for each trans layer')
    parser.add_argument('--backbone', type=str, default='mpnn',
                        help='Backbone.')
    parser.add_argument('--ours_layers', type=int, default=2,help='gnn layer.')
    parser.add_argument('--ours_dropout', type=float, 
                        help='gnn dropout.')
    parser.add_argument('--aggregate', type=str, default='add',
                        help='aggregate type, add or cat.')
    parser.add_argument('--num_heads',type=int,default=1,help='nums of head')
    

    parser.add_argument('--node_embedding_size', type=int, default=128)
    parser.add_argument('--node_hidden_size', type=int, default=128)
    parser.add_argument('--edge_hidden_size', type=int, default=4)
    parser.add_argument('--fc_size', type=int, default=2)
    parser.add_argument('--init_method', nargs='?', default='xavier_normal',
                        help='1. tnormal for truncated_normal_initializer, 2.uniform for random_uniform_initializer 3.normal for random_normal_initializer, 4.xavier_normal, 5. xavier_uniform, 6.he_normal, 7.he_uniform')

    parser.add_argument('--print_flag', type=int, default=1)
    parser.add_argument('--num_step_message_passing', type=int, default=3)
    parser.add_argument('--regs', type=float, default=0.0005)
    parser.add_argument('--gnn_dropout', type=float, default=0.0)
    parser.add_argument('--edge_dropout', type=float, default=0.0)
    parser.add_argument('--nn_dropout1', type=float, default=0.0)
    parser.add_argument('--nn_dropout2', type=float, default=0.0)
    parser.add_argument('--aggregator_type', type=str, default='sum',
                        help='max,sum,mean')
    parser.add_argument('--loss1_weight', type=float, default=1)

def parser_add_default_args(args):
    if args.method=='ours':
        if args.ours_weight_decay is None:
            args.ours_weight_decay=args.weight_decay
        if args.ours_dropout is None:
            args.ours_dropout=args.dropout
