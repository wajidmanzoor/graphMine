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
import datetime

current_date = datetime.date.today()

# file = 'overP2/benchmarks_top100_thread_utilization.csv'
file = 'results/benchmarks_top100_thread_utilization_2024-01-08.csv'
file1 = 'results/motivation_data_top100_2024-01-15.csv'

data = pd.read_csv(file)
sorted_data = data.iloc[:-1].sort_values(by=data.columns[2], ascending=False)
sorted_data = pd.concat([sorted_data, data.iloc[-1:]])
sorted_data.reset_index(drop=True, inplace=True)
data = sorted_data
data1 = pd.read_csv(file1)
'''
data['total'] = None
for index, row in data.iterrows():
    dataset_value = row['dataset']
    # print(dataset_value)
    matching_row = data1.loc[data1['dataset'] == dataset_value]
    # print(matching_row)
    if not matching_row.empty:
        total_value = matching_row.iloc[0]['total']
        data.at[index, 'total'] = total_value
data['Refine %'] = None
for index, row in data.iterrows():
    dataset_value = row['dataset']
    # print(dataset_value)
    matching_row = data1.loc[data1['dataset'] == dataset_value]
    # print(matching_row)
    if not matching_row.empty:
        total_value = matching_row.iloc[0]['Refine %']
        data.at[index, 'Refine %'] = total_value
        
# sorted_data = data.iloc[:-1].sort_values(by='total', ascending=True)
# sorted_data = pd.concat([sorted_data, data.iloc[-1:]])
# sorted_data.reset_index(drop=True, inplace=True)
sorted_data = data.iloc[:-1].sort_values(by='Refine %', ascending=False)
sorted_data = pd.concat([sorted_data, data.iloc[-1:]])
sorted_data.reset_index(drop=True, inplace=True)
sorted_data.to_csv('sorted_top100_thread_utilization.csv', index=False)
data = sorted_data
'''
x = data.iloc[:,0]
y = data.iloc[:,2]

index_list = range(len(x))

plt.rcParams['font.weight'] = 'bold'
plt.rcParams['axes.labelweight'] = 'bold'
plt.rcParams['legend.fontsize'] = 36

colors = ["#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#800080", "#ffc0cb", "#ffa500", "#808080", "#007fff", "#8e52dc"]

fig, ax = plt.subplots(figsize=(36, 10))

ax.set_ylim(bottom=0, top=1.01)  # 设置最小值和最大值区间
ax.set_ylabel('Thread Utilization', va='center', fontsize=60, fontweight='bold', labelpad=40)  # 设置纵坐标title
ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: '{:.0%}'.format(x)))
ax.tick_params(axis='y', which='major', labelsize=60)
ax.set_xlabel('Evaluated Hypergraphs', va='center', fontsize=60, fontweight='bold', labelpad=40)

ax.set_xlim(0, len(x)+10)
ax.xaxis.set_ticks([0, 25, 50, 75, len(x)-2], fontsize=40)
ax.tick_params(axis='x', which='major', labelsize=60, rotation=0)
# dot1 = ax.plot(index_list[:-1], y[:-1], marker='o', markersize=10, linestyle='-', label='', color="black", alpha=.8, linewidth=5)

ax.set_xticks([0.7, 25.7, 50.7, 75.7, 99.7])  # 设置X轴刻度位置为0和100
ax.set_xticklabels(['0', '25', '50', '75', '99'])
width = .8
mycolors = ['#014F9C', '#3C79B4', '#78A3CC', '#B3CDE4', '#EEF7FC']
bar1 = ax.bar(x=[i-width+1.5 for i in range(len(index_list[:-1]))], height=y[:-1], bottom=0, color=mycolors[0], edgecolor='black', alpha=1, width=width, hatch='', label='')


width = 6
# bar1 = ax.bar(len(x) + 5.5, y.iloc[-1], width=width, label='', edgecolor='black', color="black", alpha=.8, hatch='/')
bar1 = ax.bar(len(x) + 5.5, y.iloc[-1], width=width, label='', edgecolor='black', color=mycolors[0], alpha=1, hatch='')

ax.axvline([len(x) + .5], color='grey', linestyle='dashed', linewidth=2)

ax.yaxis.grid(True, color='gray', linestyle = '--', linewidth = 0.5)  # horizontal grid, another method
# 设置y轴刻度标签加粗
for tick in ax.yaxis.get_major_ticks():
    tick.label1.set_fontweight('bold')

last_label_pos = len(x) + 5.5
xticks = list(ax.get_xticks()) + [last_label_pos]
xticklabels = list(ax.get_xticklabels()) + ['GMean']
ax.set_xticks(xticks)
ax.set_xticklabels(xticklabels)

xtick_labels = ax.get_xticklabels()
# 设置最后一个xtick label的大小、角度和颜色
last_xtick_label = xtick_labels[-1]
last_xtick_label.set_fontsize(60)
last_xtick_label.set_rotation(0)

last_value1 = y.iloc[-1]
# ax.text(last_label_pos+0.0, last_value1 + .02, "{:.0%}".format(last_value1), color='black', ha='center', fontsize=50, rotation=0)
ax.text(last_label_pos+0.0, last_value1/2, "{:.0%}".format(last_value1), color='white', ha='center', fontsize=50, rotation=0)

handles, labels = ax.get_legend_handles_labels()

# 添加图例
# legend = ax.legend(handles, labels, bbox_to_anchor=(0.45, 1.05), loc='center', ncol=5, frameon=True)
# legend.get_frame().set_edgecolor('black')  # 设置边框颜色
# legend.get_frame().set_alpha(0.8)

spines = ax.spines
spines['top'].set_linewidth(3)
spines['bottom'].set_linewidth(3)
spines['left'].set_linewidth(3)
spines['right'].set_linewidth(3)

# 调整布局以适应标签
plt.tight_layout()

fig.subplots_adjust(left=0, bottom=0, right=1, top=1)

# output = 'overP2/benchmarks_top100_thread_utilization.pdf'
output = f'results/benchmarks_top100_thread_utilization_{current_date}.pdf'

# 保存图片
plt.savefig(output, dpi=300, bbox_inches='tight')

# 显示图形
plt.show()


