import csv
import random
import matplotlib.pyplot as plt
import numpy as np
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
from adjustText import adjust_text
from scipy.stats import gmean
import matplotlib.image as mpimg
import datetime

current_date = datetime.date.today()

# file = 'overP2/benchmarks_all_nodemerging_procedure_overP2_240104.csv'
# file = 'overP2/benchmarks_all_nodemerging_top100_240104.csv'
# file = 'overP2/benchmarks_all_construction_procedure_overP2_240104.csv'
# file = 'overP2/benchmarks_all_construction_top100_240104.csv'
file = 'results/benchmarks_all_nodemerging_procedure_overP2_240108.csv'
# file = 'overP2/benchmarks_all_construction_procedure_overP2_240108.csv'

# 读取CSV文件
data = pd.read_csv(file)
sorted_data = data.iloc[:-1].sort_values(by='p3_speedup')
sorted_data = pd.concat([sorted_data, data.iloc[-1:]])
sorted_data.reset_index(drop=True, inplace=True)
data = sorted_data

# 提取需要绘制箱线图的列数据
column_data1 = data['p2_speedup'][:-1]
column_data2 = data['p3_speedup'][:-1]
base_time = data['baseline'][:-1]
p2_time = data['p2_kernel'][:-1]
p3_time = data['p3_kernel'][:-1]

# column_data2 = data['p3_speedup'][:-1]
# column_data1 = data['p2b_speedup'][:-1]
# base_time = data['base_p2'][:-1]
# p3_time = data['p3_kernel'][:-1]
# p2_time = data['p2b_kernel'][:-1]

self_speedup = base_time / base_time

# 计算geometric mean
geometric_mean = np.exp(np.mean(np.log(column_data1)))
print(len(column_data1))
print(geometric_mean)
# 计算最大值、最小值和方差
maximum = np.max(column_data1)
minimum = np.min(column_data1)
variance = np.var(column_data1)
print(maximum, minimum)
# 计算分位数
quartiles = np.percentile(column_data1, [25, 50, 75])
lower_quartile, median, upper_quartile = quartiles

iqr = upper_quartile - lower_quartile
lower_bound = lower_quartile - 1.5 * iqr
upper_bound = upper_quartile + 1.5 * iqr

# 标记离群值的索引
outliers = np.where((column_data1 < lower_bound) | (column_data1 > upper_bound))[0]
print(len(outliers))
# 打印离群值的位置
# print("离群值的位置：")
# for outlier in outliers:
#     print(outlier, column_data1[outlier])

plt.rcParams['font.weight'] = 'bold'
plt.rcParams['axes.labelweight'] = 'bold'
plt.rcParams['legend.fontsize'] =  35
plt.rcParams['legend.frameon'] =  True

# fig, ax = plt.subplots(figsize=(25, 7))
# fig, ax = plt.subplots(figsize=(33, 9))
fig = plt.figure(figsize=(30, 8))
spec = fig.add_gridspec(1, 2, width_ratios=[2, 1])
ax = fig.add_subplot(spec[0, 0])
ax2 = fig.add_subplot(spec[0, 1])
index_list = range(len(self_speedup))

ax.set_yscale('log', base=10)
ax.tick_params(axis='y', which='major', labelsize=40)
ax.set_ylabel('Kernel Speedup', va='center', fontsize=50, fontweight='bold', labelpad=30)
# ax.set_ylabel('Kernel Speedup over P2', va='center', fontsize=30, fontweight='bold', labelpad=30)

ax.set_ylim(0.01, 1e2)
# ax.set_xlabel('Node Merging', va='center', fontsize=30, fontweight='bold', labelpad=30)
# ax.set_xlabel('Node Merging (Top 100)', va='center', fontsize=30, fontweight='bold', labelpad=30)
ax.set_xlabel('Hypergraphs', va='center', fontsize=50, fontweight='bold', labelpad=30)
ax.set_xlim(0, len(self_speedup))
ax.xaxis.set_ticks([0, 100, 200, 300, 400, 499], fontsize=40)
ax.tick_params(axis='x', which='major', labelsize=40, rotation=0)

cmap = plt.cm.Blues
colors = cmap(np.linspace(0.5, 1, 4))
darken_factor = 0.2
darkened_color = colors[0] * (1 - darken_factor)
ax.plot(index_list, self_speedup, marker='o', markersize=4, linestyle='-', label='P1', color=colors[0], linewidth=2)
ax.plot(index_list, column_data1, marker='*', markersize=4, linestyle='-', label='P2', color=colors[1], linewidth=2)
ax.plot(index_list, column_data2, marker='x', markersize=4, linestyle='-', label='P3', color=colors[2], linewidth=2)

# ax.plot(index_list, self_speedup, marker='o', markersize=4, linestyle='-', label='P2', color=colors[0], linewidth=2)
# ax.plot(index_list, column_data1, marker='*', markersize=4, linestyle='-', label='P2b', color=colors[1], linewidth=2)
# ax.plot(index_list, column_data2, marker='*', markersize=4, linestyle='-', label='P3', color=colors[2], linewidth=2)

# ax.set_ylim(0.01, 1e4)
# ax.yaxis.set_ticks([0.01, 1, 1e2, 1e4], fontsize=40)
# ax.set_xlabel('Hypergraph Construction', va='center', fontsize=30, fontweight='bold', labelpad=30)
# ax.set_ylim(0.1, 1e4)
# ax.set_xlabel('Hypergraph Construction (Top 100)', va='center', fontsize=30, fontweight='bold', labelpad=30)

# x_tick_labels = ['P2', 'P3']
# x_tick_labels = ['P2b', 'P3']
# x_values = np.arange(0, len(x_tick_labels))
# ax.set_xticks(ticks=[i for i in range(len(x_tick_labels))], rotation=0, fontsize=30, labels=x_tick_labels, fontweight='bold')
# ax.set_xlim(-.5, 3)

# 绘制箱线图
# ax.boxplot([column_data1, column_data2], positions=x_values, widths=.2, boxprops={'linewidth': 2}, 
#                                                              whiskerprops={'linewidth': 2},
#                                                              capprops={'linewidth': 2})

# ax.set_xticks(x_values)
# ax.set_xticklabels(x_tick_labels)

ax.yaxis.grid(True, color='gray', linestyle = '--', linewidth = 0.5)  # horizontal grid, another method
# 设置y轴刻度标签加粗
for tick in ax.yaxis.get_major_ticks():
    tick.label1.set_fontweight('bold')

# ax.axhline(y=1, xmin=0, xmax=.65, color='grey', linestyle='dashed', linewidth=2)

# ax.axhline(y=geometric_mean, xmin=0.11, xmax=.175, color='red', linestyle='-', linewidth=2)

# ax.axvline([1.8], color='grey', linestyle='dashed', linewidth=2)

# 添加额外信息到图表
# ax.text(0.52, geometric_mean, f'GeoMean: {geometric_mean:.2f}', ha='right', fontsize=20, va='center', color='red')
# ax.text(0.13, maximum, f'Max: {maximum:.2f}', ha='left', fontsize=20, va='center')
# ax.text(0.13, minimum, f'Min: {minimum:.2f}', ha='left', fontsize=20, va='center')
# ax.text(0.13, lower_quartile, f'Q1: {lower_quartile:.2f}', ha='left', fontsize=15, va='center')
# ax.text(0.13, median, f'Median: {median:.2f}', ha='left', fontsize=15, va='center')
# ax.text(0.13, upper_quartile, f'Q3: {upper_quartile:.2f}', ha='left', fontsize=15, va='center')

ax.text(501, max(column_data2), f'Max: {max(column_data2):.2f}', ha='left', fontsize=40, va='center')
# ax.text(501, max(column_data1), f'Max: {max(column_data1):.2f}', ha='left', fontsize=40, va='center')

geometric_mean2 = np.exp(np.mean(np.log(column_data2)))
print(len(column_data2))
print(geometric_mean2)
# 计算最大值、最小值和方差
maximum2 = np.max(column_data2)
minimum2 = np.min(column_data2)
variance2 = np.var(column_data2)
print(maximum2, minimum2)
# 计算分位数
quartiles2 = np.percentile(column_data2, [25, 50, 75])
lower_quartile2, median2, upper_quartile2 = quartiles2

# ax.axhline(y=geometric_mean2, xmin=0.395, xmax=0.46, color='red', linestyle='-', linewidth=2)

# ax.text(1.52, geometric_mean2, f'GeoMean: {geometric_mean2:.2f}', ha='right', fontsize=20, va='center', color='red')
# ax.text(1.13, maximum2, f'Max: {maximum2:.2f}', ha='left', fontsize=20, va='center')
# ax.text(1.13, minimum2, f'Min: {minimum2:.2f}', ha='left', fontsize=20, va='center')
# ax.text(1.13, lower_quartile2, f'Q1: {lower_quartile2:.2f}', fontsize=15, ha='left', va='center')
# ax.text(1.13, median2, f'Median: {median2:.2f}', ha='left', fontsize=15, va='center')
# ax.text(1.13, upper_quartile2, f'Q3: {upper_quartile2:.2f}', fontsize=15, ha='left', va='center')

count_col1 = np.sum((base_time == np.min([base_time, p2_time, p3_time], axis=0)).astype(int))
count_col2 = np.sum((p2_time == np.min([base_time, p2_time, p3_time], axis=0)).astype(int))
count_col3 = np.sum((p3_time == np.min([base_time, p2_time, p3_time], axis=0)).astype(int))

indices = np.where((base_time == np.min([base_time, p2_time, p3_time], axis=0)))[0]
print(indices)
for i in indices:
    print(data['dataset'][i])

# 输出结果
print("Count of minimum values belonging to column 1:", count_col1)
print("Count of minimum values belonging to column 2:", count_col2)
print("Count of minimum values belonging to column 3:", count_col3)

# colors = ["#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#800080", "#ffc0cb", "#ffa500", "#808080", "#007fff", "#8e52dc"]

# img = mpimg.imread('overP2/best_pattern_counting_construction.jpg')  # 替换为您的图片路径
# ax2.imshow(img)
# ax2.axis('off')
# ax2.set_title('Right Subplot')
# ax2.tick_params(axis='both', which='both', length=0, labelsize=0)
# ax2.yaxis.set_major_locator(plt.NullLocator())
# ax2.xaxis.set_major_locator(plt.NullLocator())

labels = ['P1', 'P2', 'P3']
# labels = ['P2', 'P2b', 'P3']
counts = [count_col1, count_col2, count_col3]
# colors = ['deepskyblue', 'dodgerblue', 'steelblue']
explode = [0.1, 0, 0]

wedges, _, autotexts = ax2.pie([count_col1, count_col2, count_col3],
        labels=labels, # 设置饼图标签
        colors=[colors[0], colors[1], colors[2]], # 设置饼图颜色
        # explode=(0, 0.2, 0, 0), # 第二部分突出显示，值越大，距离中心越远
        # autopct='%.2f%%', # 格式化输出百分比
        startangle=45, 
        wedgeprops={'edgecolor': 'white', 'linewidth': 2},
        textprops={'fontsize': 40, 'fontweight': 'bold', 'color': 'black'},
        autopct=lambda pct: f'{int(round(pct*sum(counts)/100))}'
       )
for autotext in autotexts:
    autotext.set_color('white')
    
value_props = {'fontsize': 35, 'fontweight': 'bold'}
plt.setp(autotexts, **value_props)
# label_props = {'fontsize': 20, 'fontweight': 'bold'}
# plt.setp(ax2.patches, **label_props)
ax2.set_xlim([-1.2, 1.2])
ax2.set_ylim([-1.2, 1.2])
ax2.set_aspect(0.5)
# 设置图例
# ax2.legend(wedges, labels, loc='best')

# 设置标题
# ax2.set_title('Pie Chart')
# ax2.set_title('xxxx')
# ax2.set_xlabel('Best Pattern Counting', va='center', fontsize=30, fontweight='bold', labelpad=30)
ax2.axis('equal')
ax2.set_aspect('equal')  # 设置饼图的纵横比，保持图形为正圆形
# 调整饼图的大小
box = ax2.get_position()
# ax2.set_position([box.x0, box.y0, box.width * 1.5, box.height]) 

ax2.xaxis.set_visible(False)
ax2.yaxis.set_visible(False) #隐藏包括轴标签的坐标轴
ax2.xaxis.set_ticks([])
ax2.yaxis.set_ticks([]) #在 Matplotlib 中隐藏坐标轴
ax2.xaxis.set_ticklabels([])
ax2.yaxis.set_ticklabels([]) #在 Matplotlib 中隐藏轴标签/文本

spines2 = ax2.spines
spines2['top'].set_linewidth(5)
spines2['bottom'].set_linewidth(5)
spines2['left'].set_linewidth(5)
spines2['right'].set_linewidth(5)

title_font = {'fontsize': 20, 'fontweight': 'bold'}
# ax2.set_title('Best Pattern Counting', **title_font)
# ax2.title.set_position([0.5, -1000])
# plt.title('# of hypergraphs performs \nbest for each pattern', y=-0.23, fontsize=45, fontweight='bold')
# ax2 = ax.twinx()
# ax2.set_yscale('linear')
# # ax2.set_ylim(0, 500)
# ax2.set_ylim(0, 100)
# ax2.tick_params(axis='y', which='major', labelsize=30)
# ax2.set_ylabel('# of Hypergraphs (best)', va='center', fontsize=30, fontweight='bold', labelpad=30)

# ax2.bar(2.0, count_col1, width=.3, label='P1', edgecolor='black', color=colors[9], hatch='/')
# ax2.bar(2.4, count_col2, width=.3, label='P2', edgecolor='black', color=colors[7], hatch='')
# ax2.bar(2.8, count_col3, width=.3, label='P3', edgecolor='black', color=colors[6], hatch='\\')

# ax2.bar(2.0, count_col1, width=.3, label='P2', edgecolor='black', color=colors[9], hatch='/')
# ax2.bar(2.4, count_col2, width=.3, label='P2b', edgecolor='black', color=colors[7], hatch='')
# ax2.bar(2.8, count_col3, width=.3, label='P3', edgecolor='black', color=colors[6], hatch='\\')

# handles, labels = ax2.get_legend_handles_labels()
# legend = ax2.legend(handles, labels, bbox_to_anchor=(1.0, 1.0), loc='upper right', ncol=1, fontsize=20, frameon=True)
# frame = legend.get_frame()
# frame.set_edgecolor('#808080')  # 设置边框颜色
# frame.set_linewidth(1)  # 设置边框粗细
# frame.set_alpha(1)  # 设置边框透明度
# frame.set_linestyle('dashed')

handles, labels = ax.get_legend_handles_labels()
legend = ax.legend(handles, labels, bbox_to_anchor=(0.5, 0.90), loc='center', ncol=5, fontsize=40, frameon=True)
frame = legend.get_frame()
frame.set_edgecolor('#808080')  # 设置边框颜色
frame.set_linewidth(2)  # 设置边框粗细
frame.set_alpha(1)  # 设置边框透明度

spines = ax.spines
spines['top'].set_linewidth(5)
spines['bottom'].set_linewidth(5)
spines['left'].set_linewidth(5)
spines['right'].set_linewidth(5)  

# 调整布局以适应标签
plt.tight_layout()

# output = 'overP2/benchmarks_all_nodemerging_240104.pdf'
# output = 'overP2/benchmarks_all_nodemerging_top100_240104.pdf'
# output = 'overP2/benchmarks_all_construction_240104.pdf'
# output = 'overP2/benchmarks_all_construction_top100_240104.pdf'

# output = 'overP2/benchmarks_all_nodemerging_240105.pdf'
# output = 'overP2/benchmarks_all_construction_240105.pdf'
output = 'results/benchmarks_all_nodemerging_240108.pdf'
# output = 'overP2/benchmarks_all_construction_240108.pdf'

# 保存图片
plt.savefig(output, dpi=300, bbox_inches='tight')

# 显示图表
plt.show()
