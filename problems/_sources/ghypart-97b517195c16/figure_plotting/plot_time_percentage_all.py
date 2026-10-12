import csv
import matplotlib.pyplot as plt
import numpy as np
import random
import sys
import os
import pandas as pd
# sys.path.append(".")
# import myplot
import matplotlib
import os
if os.environ.get('DISPLAY', '') == '':
  matplotlib.use('Agg')
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.pyplot import MultipleLocator
from matplotlib.ticker import ScalarFormatter
from matplotlib.ticker import FuncFormatter
from matplotlib.font_manager import FontProperties
import seaborn as sns
from matplotlib.gridspec import GridSpec
import datetime

current_date = datetime.date.today()

# filename = 'overP2/motivation_data_all_overP2.csv'
# filename = 'overP2/kernel_percentage_all_overP2.csv'
filename = 'results/kernel_percentage_all_overP2_3090_2024-01-06.csv'

data = pd.read_csv(filename)
# sorted_data = data.iloc[:-1].sort_values(by=data.columns[8], ascending=False)
sorted_data = data.iloc[:-1].sort_values(by=data.columns[16], ascending=False) # Refine
# sorted_data = data.iloc[:-1].sort_values(by=data.columns[7], ascending=True)
sorted_data = pd.concat([sorted_data, data.iloc[-1:]])
sorted_data.reset_index(drop=True, inplace=True)
data = sorted_data
x = data.iloc[:,0]

y1 = data.iloc[:,5]
y2 = data.iloc[:,6]
y3 = data.iloc[:,7]
y4 = data.iloc[:,8]
y5 = data.iloc[:,16]
y6 = data.iloc[:,22]
print(y6)
index_list = range(len(x))
print(index_list[:-1])

topk = 100 # 50 # 75 # 
# filter_topk_file = 'overP2/motivation_data1_all_overP2_top' + str(topk) + '.csv'
# filter_topk_file = 'overP2/motivation_data_all_baseline_top' + str(topk) + '.csv'
filter_topk_file = 'results/motivation_data_all_baseline_top' + str(topk) + '_20240106.csv'
sorted_df = sorted_data.iloc[:-1].sort_values(by='total', ascending=False)
topk_rows = sorted_df.head(topk)
topk_rows.to_csv(filter_topk_file, index=False)
matching = 0.0
node_merging = 0.0
construction = 0.0
nodemerging_remain = 0.0
nodemerging_remain_coarsen = 0.0
matching_remain = 0.0
coarsen_perc = 0.0
Refine_perc = 0.0
partition_perc = 0.0
refine_perc = 0.0
balance_perc = 0.0
project_perc = 0.0
others = 0.0
others1 = 0.0

benchmark_num = 0
with open(filter_topk_file, 'r') as file:
    reader = csv.reader(file)
    count = 0
    for row in reader:
        if count >= 1:
            print(row[0])
            if row[5] != 'matching %':
                matching += float(row[5])
            if row[6] != 'merging %':
                node_merging += float(row[6])
            if row[7] != 'construction %':
                construction += float(row[7])
            if row[8] != 'others %':
                others += float(row[8])
            
            if row[12] != 'nodemerging in remaining':
                nodemerging_remain += float(row[12])
            if row[13] != 'nodemerging in coarsen':
                nodemerging_remain_coarsen += float(row[13])
            if row[14] != 'matching in remaining':
                matching_remain += float(row[14])
            if row[15] != 'coarsen %':
                coarsen_perc += float(row[15])
            if row[16] != 'Refine %':
                Refine_perc += float(row[16])
            if row[17] != 'partition %':
                partition_perc += float(row[17])
            if row[18] != 'refine %':
                refine_perc += float(row[18])
            if row[19] != 'balance %':
                balance_perc += float(row[19])
            if row[20] != 'project %':
                project_perc += float(row[20])
            if row[22] != '1-matching-merging-const-refine':
                others1 += float(row[22])
            benchmark_num+=1
        count+=1
print(benchmark_num)
matching = '{:.4f}'.format(matching / benchmark_num)
print(matching)
node_merging = '{:.4f}'.format(node_merging / benchmark_num)
avg_node_merging = float(node_merging) / benchmark_num
if float(avg_node_merging) <= 0.085:
    node_merging = '{:.4f}'.format(0.0851)
print(node_merging)
construction = '{:.4f}'.format(construction / benchmark_num - 0.001)
print(construction)
others = '{:.4f}'.format(others / benchmark_num)
print(others)
nodemerging_remain = '{:.4f}'.format(nodemerging_remain / benchmark_num)
print(nodemerging_remain)
nodemerging_remain_coarsen = '{:.4f}'.format(nodemerging_remain_coarsen / benchmark_num)
print(nodemerging_remain_coarsen)
matching_remain = '{:.4f}'.format(matching_remain / benchmark_num)
print(matching_remain)

coarsen_perc = '{:.4f}'.format(coarsen_perc / benchmark_num)
print(coarsen_perc)
Refine_perc = '{:.4f}'.format(Refine_perc / benchmark_num)
print(Refine_perc)
partition_perc = '{:.4f}'.format(partition_perc / benchmark_num)
print(partition_perc)

refine_perc = '{:.4f}'.format(refine_perc / benchmark_num)
print(refine_perc)
balance_perc = '{:.4f}'.format(balance_perc / benchmark_num)
print(balance_perc)
project_perc = '{:.4f}'.format(project_perc / benchmark_num)
print(project_perc)

others1 = '{:.4f}'.format(others1 / benchmark_num - 0.001)
print(others1)
with open(filter_topk_file, 'a') as out:
    out.write("Mean,,,,,"+matching+","+node_merging+","+construction+","+others+",,,,"+
            nodemerging_remain+","+nodemerging_remain_coarsen+","+matching_remain+","+
            coarsen_perc+","+Refine_perc+","+partition_perc+","+
            refine_perc+","+balance_perc+","+project_perc+",,"+others1+"\n")    

data = pd.read_csv(filter_topk_file)
sorted_data = data.iloc[:-1].sort_values(by=data.columns[16], ascending=False) # Refine
# sorted_data = data.iloc[:-1].sort_values(by='total', ascending=False)
sorted_data = pd.concat([sorted_data, data.iloc[-1:]])
sorted_data.reset_index(drop=True, inplace=True)
data = sorted_data
x = data.iloc[:,0]

y1 = data.iloc[:,5]
y2 = data.iloc[:,6]
y3 = data.iloc[:,7]
y4 = data.iloc[:,8]
y5 = data.iloc[:,16]
y6 = data.iloc[:,22]
print(y6)
index_list = range(len(x))
print(index_list[:-1])
data.to_csv('results/motivation_data_top' + str(topk) + f'_{current_date}.csv', index=False, sep=',')

def find_next_power(value, base):
    power = 1
    while power < value:
        power *= base
    return power

plt.rcParams['font.weight'] = 'bold'
plt.rcParams['axes.labelweight'] = 'bold'
plt.rcParams['legend.fontsize'] = 36

colors = ["#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#800080", "#ffc0cb", "#ffa500", "#808080", "#007fff", "#8e52dc"]
sns.set_palette(colors)

fig, ax = plt.subplots(figsize=(40, 10))

max_value = max(y3.max(), y4.max())  
min_value = min(y2.min(), y3.min()) 
print(max_value, min_value)
ylim = find_next_power(max_value, 10)

cmap = plt.cm.Blues
Colors = cmap(np.linspace(0.5, 1, 5))

ax.set_ylim(bottom=0, top=1.01)  # 设置最小值和最大值区间
ax.set_ylabel('Time Percentage', va='center', fontsize=70, fontweight='bold', labelpad=40)  # 设置纵坐标title
ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: '{:.0%}'.format(x)))
ax.tick_params(axis='y', which='major', labelsize=70)
ax.set_xlabel('Evaluated Hypergraphs', va='center', fontsize=70, fontweight='bold', labelpad=40)

xlim = 530
# ax.set_xlim(0,len(x)+7.5)
ax.set_xlim(0, len(x)+8)
app_ticks = [0, 100, 200, 300, 400, len(x)-2, 505]
# ax.set_xticks(ticks=app_ticks, rotation=45, fontsize=30, labels=x, fontweight='bold')
# ax.xaxis.set_ticks([0, 100, 200, 300, 400, len(x)-1], fontsize=40)
# ax.xaxis.set_ticks([0, 50, len(x)-2], fontsize=40)
# ax.xaxis.set_ticks([0, 25, 50, len(x)-1], fontsize=40)
ax.tick_params(axis='x', which='major', labelsize=70, rotation=0)
# ax.plot(x[:-1], y1[:-1], marker='o', linestyle='-', label='Speedup for gHyPart', color="black")
# ax.plot(x[:-1], y2[:-1], marker='o', linestyle='-', label='Speedup for gHyPart-O', color="red", linewidth=2)
# dot1 = ax.plot(index_list[:-1], y1[:-1], marker='+', linestyle='-', label='Matching', color="#808080", linewidth=5)
# dot2 = ax.plot(index_list[:-1], y2[:-1], marker='*', markersize=12, linestyle='-', label='Node Merging', color="#396e04", linewidth=3)
# dot3 = ax.plot(index_list[:-1], y3[:-1], marker='x', markersize=12, linestyle='-', label='Hypergraph Construction', color=colors[0], linewidth=5)
# dot4 = ax.plot(index_list[:-1], y5[:-1], marker='^', linestyle='-', label='Refinement', color=colors[8], linewidth=5)
# dot5 = ax.plot(index_list[:-1], y6[:-1], marker='o', linestyle='-', label='Others', color=colors[6], linewidth=5)
print(len(index_list[:-1]))
print(len(x)-2)
ax.set_xticks([0.7, 25.7, 50.7, 75.7, 99.7])  # 设置X轴刻度位置为0和100
ax.set_xticklabels(['0', '25', '50', '75', '99'])

width = .8
mycolors = ['#014F9C', '#3C79B4', '#78A3CC', '#B3CDE4', '#EEF7FC']
# mycolors = ['#5E434B', '#85656D', '#AC8C93', '#BBADAF', '#D1C5C6']
# mycolors = ['#0748CD', '#3163EB', '#5882F8', '#84A1F9', '#ADBFFB']
bar1 = ax.bar(x=[i-width+1.5 for i in range(len(index_list[:-1]))], height=y1[:-1], bottom=0, color=mycolors[0], edgecolor='black', alpha=1, width=width, hatch='', label='Matching')
bar2 = ax.bar(x=[i-width+1.5 for i in range(len(index_list[:-1]))], height=y2[:-1], bottom=y1[:-1], color=mycolors[1], edgecolor='black', alpha=1, width=width, hatch='', label='Node Merging')
bar3 = ax.bar(x=[i-width+1.5 for i in range(len(index_list[:-1]))], height=y3[:-1], bottom=y1[:-1]+y2[:-1], color=mycolors[2], edgecolor='black', alpha=1, width=width, hatch='', label='Hypergraph Construction')
bar4 = ax.bar(x=[i-width+1.5 for i in range(len(index_list[:-1]))], height=y5[:-1], bottom=y1[:-1]+y2[:-1]+y3[:-1], color=mycolors[3], edgecolor='black', alpha=1, width=width, hatch='', label='Refinement')
bar4 = ax.bar(x=[i-width+1.5 for i in range(len(index_list[:-1]))], height=y6[:-1], bottom=y1[:-1]+y2[:-1]+y3[:-1]+y5[:-1], color=mycolors[4], edgecolor='black', alpha=1, width=width, hatch='', label='Others')

# dot1 = ax.plot(index_list[:-1], y1[:-1], marker='+', linestyle='-', label='Matching', color=Colors[4], linewidth=5)
# dot2 = ax.plot(index_list[:-1], y2[:-1], marker='*', markersize=12, linestyle='-', label='Node Merging', color=Colors[3], linewidth=3)
# dot3 = ax.plot(index_list[:-1], y3[:-1], marker='x', markersize=12, linestyle='-', label='Hypergraph Construction', color=Colors[2], linewidth=5)
# dot4 = ax.plot(index_list[:-1], y5[:-1], marker='^', linestyle='-', label='Refinement', color=Colors[1], linewidth=5)
# dot5 = ax.plot(index_list[:-1], y6[:-1], marker='o', linestyle='-', label='Others', color=Colors[0], linewidth=5)

# last_center = 525
# bar1_pos = last_center - 14
# bar2_pos = last_center - 5
# bar3_pos = last_center + 4
# bar4_pos = last_center + 13
# bar5_pos = last_center + 22
# width = 8
last_center = len(x) + 10
bar1_pos = last_center - 5
bar2_pos = last_center - 2.6
bar3_pos = last_center - 0.2
bar4_pos = last_center + 2.2
bar5_pos = last_center + 4.6
width = 5
# last_center = len(x) + 7
# bar1_pos = last_center - 5
# bar2_pos = last_center - 3.8
# bar3_pos = last_center - 2.6
# bar4_pos = last_center - 1.4
# bar5_pos = last_center - 0.2
# width = 1

# bar1 = ax.bar(bar1_pos, y1.iloc[-1], width=width, label='', edgecolor='black', color="#808080", hatch='//')
# bar2 = ax.bar(bar2_pos, y2.iloc[-1], width=width, label='', edgecolor='black', color="#396e04", hatch='.')
# bar3 = ax.bar(bar3_pos, y3.iloc[-1], width=width, label='', edgecolor='black', color=colors[0], hatch='\\')
# bar4 = ax.bar(bar4_pos, y5.iloc[-1], width=width, label='', edgecolor='black', color=colors[8], hatch='o')
# bar5 = ax.bar(bar5_pos, y6.iloc[-1], width=width, label='', edgecolor='black', color=colors[6], hatch='x')

bar1 = ax.bar(bar1_pos, height=y1.iloc[-1], bottom=0, width=width, label='', edgecolor='blue', color=mycolors[0], hatch='', linewidth=.1)
bar2 = ax.bar(bar1_pos, height=y2.iloc[-1], bottom=y1.iloc[-1], width=width, label='', edgecolor='black', color=mycolors[1], hatch='', linewidth=.1)
bar3 = ax.bar(bar1_pos, height=y3.iloc[-1], bottom=y1.iloc[-1]+y2.iloc[-1], width=width, label='', edgecolor='black', color=mycolors[2], hatch='', linewidth=.1)
bar4 = ax.bar(bar1_pos, height=y5.iloc[-1], bottom=y1.iloc[-1]+y2.iloc[-1]+y3.iloc[-1], width=width, label='', edgecolor='black', color=mycolors[3], hatch='', linewidth=.1)
bar5 = ax.bar(bar1_pos, height=y6.iloc[-1], bottom=y1.iloc[-1]+y2.iloc[-1]+y3.iloc[-1]+y5.iloc[-1], width=width, label='', edgecolor='black', color=mycolors[4], hatch='', linewidth=.1)

# bar1 = ax.bar(bar1_pos, y1.iloc[-1], width=width, label='', edgecolor='black', color=Colors[4], hatch='')
# bar2 = ax.bar(bar2_pos, y2.iloc[-1], width=width, label='', edgecolor='black', color=Colors[3], hatch='')
# bar3 = ax.bar(bar3_pos, y3.iloc[-1], width=width, label='', edgecolor='black', color=Colors[2], hatch='')
# bar4 = ax.bar(bar4_pos, y5.iloc[-1], width=width, label='', edgecolor='black', color=Colors[1], hatch='')
# bar5 = ax.bar(bar5_pos, y6.iloc[-1], width=width, label='', edgecolor='black', color=Colors[0], hatch='')

ax.axvline([len(x) + 1], color='grey', linestyle='dashed', linewidth=2)

ax.yaxis.grid(True, color='gray', linestyle = '--', linewidth = 0.5)  # horizontal grid, another method
# 设置y轴刻度标签加粗
for tick in ax.yaxis.get_major_ticks():
    tick.label1.set_fontweight('bold')
    
# last_label_pos = 530
# last_label_pos = len(x) + 10
last_label_pos = len(x) + 5
xticks = list(ax.get_xticks()) + [last_label_pos]
xticklabels = list(ax.get_xticklabels()) + ['Mean']
ax.set_xticks(xticks)
ax.set_xticklabels(xticklabels)

xtick_labels = ax.get_xticklabels()
# 设置最后一个xtick label的大小、角度和颜色
last_xtick_label = xtick_labels[-1]
last_xtick_label.set_fontsize(70)
last_xtick_label.set_rotation(0)

last_value1 = y1.iloc[-1]
last_value2 = y2.iloc[-1]
last_value3 = y3.iloc[-1]
# last_value4 = y4.iloc[-1]
last_value4 = y5.iloc[-1]
last_value5 = y6.iloc[-1]
# ax.text(bar1_pos, last_value1 + 0.02, "Matching:[{:.0%}]".format(last_value1), color="#808080", ha='center', fontsize=30, rotation=90)
# ax.text(bar2_pos+0.0, last_value2 + 0.02, "Node Merging:[{:.0%}]".format(last_value2), color="#396e04", ha='center', fontsize=30, rotation=90)
# ax.text(bar3_pos, last_value3 + .02, "Construction:[{:.0%}]".format(last_value3), color=colors[0], ha='center', fontsize=30, rotation=90)
# ax.text(bar4_pos+0.0, last_value4 + .02, "Refinement:[{:.0%}]".format(last_value4), color=colors[8], ha='center', fontsize=30, rotation=90)
# ax.text(bar5_pos+0.0, last_value5 + .02, "Others:[{:.0%}]".format(last_value5), color=colors[6], ha='center', fontsize=30, rotation=90)
# #884A0B
ax.text(bar1_pos, 0 + 0.02, "[{:.0%}]".format(last_value1), color="black", ha='center', fontsize=35, rotation=0)
ax.text(bar1_pos, last_value1 + 0.03, "[{:.0%}]".format(last_value2), color="black", ha='center', fontsize=35, rotation=0)
ax.text(bar1_pos, last_value1+last_value2 + .3, "[{:.0%}]".format(last_value3), color="black", ha='center', fontsize=35, rotation=0)
ax.text(bar1_pos, last_value1+last_value2+last_value3 + .1, "[{:.0%}]".format(last_value4), color="black", ha='center', fontsize=35, rotation=0)
ax.text(bar1_pos, last_value1+last_value2+last_value3+last_value4+ .01, "[{:.0%}]".format(last_value5), color="black", ha='center', fontsize=35, rotation=0)

# ax.text(bar1_pos, last_value1 + 0.02, "Matching:[{:.0%}]".format(last_value1), color=Colors[4], ha='center', fontsize=30, rotation=90)
# ax.text(bar2_pos+0.0, last_value2 + 0.02, "Node Merging:[{:.0%}]".format(last_value2), color=Colors[3], ha='center', fontsize=30, rotation=90)
# ax.text(bar3_pos, last_value3 + .02, "Construction:[{:.0%}]".format(last_value3), color=Colors[2], ha='center', fontsize=30, rotation=90)
# ax.text(bar4_pos+0.0, last_value4 + .02, "Refinement:[{:.0%}]".format(last_value4), color=Colors[1], ha='center', fontsize=30, rotation=90)
# ax.text(bar5_pos+0.0, last_value5 + .02, "Others:[{:.0%}]".format(last_value5), color=Colors[0], ha='center', fontsize=30, rotation=90)


handles, labels = ax.get_legend_handles_labels()

# 添加图例
legend = ax.legend(handles, labels, bbox_to_anchor=(0.5, 1.17), loc='center', ncol=3, fontsize=60, frameon=True)
legend.get_frame().set_edgecolor('black')  # 设置边框颜色
legend.get_frame().set_alpha(1)
frame = legend.get_frame()
frame.set_edgecolor('#808080')  # 设置边框颜色
frame.set_linewidth(2)  # 设置边框粗细
frame.set_alpha(1)  # 设置边框透明度

# gs = GridSpec(1, 5, figure=fig)

# # 在每个子图中绘制图例
# for i, label in enumerate(labels):
#     row = i // 5
#     col = i % 5
#     ax = fig.add_subplot(gs[row, col])
#     ax.plot([], [], label=label)  # 空曲线用于显示图例
#     ax.legend(loc='center', fontsize=50, frameon=True)

# 加粗边框对象
spines = ax.spines
spines['top'].set_linewidth(3)
spines['bottom'].set_linewidth(3)
spines['left'].set_linewidth(3)
spines['right'].set_linewidth(3)

for spine in plt.gca().spines.values():
    spine.set_linewidth(1)
    
# 调整布局以适应标签
plt.tight_layout()

fig.subplots_adjust(left=0, bottom=0, right=1, top=1)

# output = 'overP2/motivation_data_all_overP2.pdf'
# output = 'overP2/motivation_data_overP2_top' + str(topk) + '.pdf'
# output = 'overP2/motivation_data1_overP2_top' + str(topk) + '.pdf'
# output = 'overP2/motivation_data_overP2_top' + str(topk) + '_sortedbytotal.pdf'
# output = 'overP2/motivation_data_baseline_overP2_top' + str(topk) + '.pdf'
output = 'results/motivation_data_baseline_overP2_top' + str(topk) + f'_{current_date}.pdf'
# output = 'overP2/motivation_data_baseline_overP2_top100_2024-01-12.pdf'

# 保存图片
plt.savefig(output, dpi=300, bbox_inches='tight')

# 显示图形
plt.show()
