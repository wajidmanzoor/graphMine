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

file = 'results/benchmarks_all_patterns_top100_3090_2024-01-08.csv'
# data = pd.read_csv('benchmarks.csv')
# x = data.iloc[:,0]
# y1 = data.iloc[:,13]
# y2 = data.iloc[:,14]
data = pd.read_csv(file)
# data = data.sort_values(by=data.columns[18])
# sorted_data = data.iloc[:-1].sort_values(by=data.columns[18])
# sorted_data = data.iloc[:-1].sort_values(by=data.columns[16])
# sorted_data = data.iloc[:-1].sort_values(by=data.columns[32])
sorted_data = data.iloc[:-1].sort_values(by=data.columns[31])
# sorted_data = data.iloc[:-1].sort_values(by=data.columns[30])
data['ratio'] = data.iloc[:,30][:-1] / data.iloc[:,29][:-1]
# sorted_data = data.iloc[:-1].sort_values(by='ratio')
sorted_data = pd.concat([sorted_data, data.iloc[-1:]])
sorted_data.reset_index(drop=True, inplace=True)
# print(sorted_data)
data = sorted_data
x = data.iloc[:,0]
# y1 = data.iloc[:,17]
# y2 = data.iloc[:,18]
# y1 = data.iloc[:,15]
# y2 = data.iloc[:,16]
y1 = data.iloc[:,31]
y2 = data.iloc[:,32]
print(x, y1, y2)
# x.iloc[:-1] = x.index[:-1]
# data.iloc[:, 0] = x
# data.to_csv(file, index=False)

# x_modified = x.copy()
# x_modified.iloc[:-1] = x_modified.index[:-1]
# print(x)
# print(x[:-1])
# x = data.iloc[:,0]

index_list = range(len(x))
print(index_list[:-1])
def find_next_power(value, base):
    power = 1
    while power < value:
        power *= base
    return power

# 设置全局字体属性
plt.rcParams['font.weight'] = 'bold'
plt.rcParams['axes.labelweight'] = 'bold'
plt.rcParams['legend.fontsize'] =  30
plt.rcParams['legend.frameon'] =  True
# print(plt.rcParams.keys())

# 设置自定义的调色板
colors = ["#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#800080", "#ffc0cb", "#ffa500", "#808080", "#007fff", "#8e52dc"]
sns.set_palette(colors)

fig, ax = plt.subplots(figsize=(30, 11))

# plt.hist(y1, bins=20, color='blue', alpha=0.5)  # 使用蓝色填充  
# plt.hist(y2, bins=20, color='red', alpha=0.5)  # 使用红色填充  

max_value = max(y1.max(), y2.max())  
min_value = min(y1.min(), y2.min()) 
print(max_value, min_value)
ylim = find_next_power(max_value, 10)

second_min_value = y1.nsmallest(2).iloc[-1]
print(second_min_value)

print(ylim)
ax.set_yscale('log', base=10)  # 设置纵坐标为log2刻度
ax.set_ylim(0, ylim)  # 设置纵坐标起始值为0
# ax.yaxis.set_ticks([0.1, 1, 10, 100, 1000, 1e4, ylim], fontsize=40)
# ax.yaxis.set_ticks([0.1, 1, 10, 100, 1000], fontsize=40)
ax.tick_params(axis='y', which='major', labelsize=50)
ax.set_ylabel('Speedup over ɢHʏPᴀʀᴛ-B', va='center', fontsize=48, fontweight='bold', labelpad=50)  # 设置纵坐标title
ax.set_xlabel('Hypergraphs', va='center', fontsize=50, fontweight='bold', labelpad=40)


print(len(x))
xlim = 550
powerlaw = 75
topk = 100
filter = len(x)-1 # 91 #
# ax.set_xlim(0, len(x)+50)
# ax.set_xlim(0,len(x)+6.5)
ax.set_xlim(0,len(x)+12)
# ax.set_xlim(0,len(x)+15)
# ax.set_xticks(ticks=app_ticks, rotation=45, fontsize=30, labels=x, fontweight='bold')
# ax.xaxis.set_ticks([0, 100, 200, 300, 400, len(x)-2], fontsize=40)
# ax.xaxis.set_ticks([0, 10, 20, 30, 40, 50, 60, powerlaw-1], fontsize=40)
ax.xaxis.set_ticks([0, 20, 40, 60, 80, topk-1], fontsize=40)
# ax.xaxis.set_ticks([0, 50, 100, filter-1], fontsize=40)
ax.tick_params(axis='x', which='major', labelsize=50, rotation=0)
# ax.plot(x[:-1], y1[:-1], marker='o', linestyle='-', label='Speedup for gHyPart', color="black")
# ax.plot(x[:-1], y2[:-1], marker='o', linestyle='-', label='Speedup for gHyPart-O', color="red", linewidth=2)
# ax.plot(index_list[:-1], y1[:-1], marker='o', markersize = 8, linestyle='-', label='Speedup for ɢHʏPᴀʀᴛ', color="black", linewidth=2)
# ax.plot(index_list, y1, marker='o', markersize = 8, linestyle='-', label='Speedup for ɢHʏPᴀʀᴛ', color="black", linewidth=2)
# ax.plot(index_list[:-1], y2[:-1], marker='^', markersize = 8, linestyle='-', label='Speedup for ɢHʏPᴀʀᴛ-O', color="red", linewidth=2)

ax.set_xticks([0.7, 25.7, 50.7, 75.7, 99.7])  # 设置X轴刻度位置为0和100
ax.set_xticklabels(['0', '25', '50', '75', '99'])
width = .8
mycolors = ['#014F9C', '#3C79B4', '#78A3CC', '#B3CDE4', '#EEF7FC']
bar1 = ax.bar(x=[i-width+1.5 for i in range(len(index_list[:-1]))], height=y1[:-1], bottom=0, color=mycolors[0], edgecolor='black', alpha=1, width=width, hatch='', label='')


'''
ax.set_yscale('linear')
ax.set_ylim(0, 1.01)
ax.tick_params(axis='y', which='major', labelsize=36)
ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: '{:.0%}'.format(x)))
ax.set_xlim(0, len(x)+50)
# ax.set_ylabel('Speedup Ratio \n[ɢHʏPᴀʀᴛ/ɢHʏPᴀʀᴛ-O]', va='center', fontsize=40, fontweight='bold', labelpad=50)  # 设置纵坐标title
# ax.plot(index_list[:-1], y1[:-1] / y2[:-1], marker='o', markersize = 8, linestyle='-', label='', color="red", linewidth=2)
ax.plot(index_list[:-1], data.iloc[:,30][:-1] / data.iloc[:,29][:-1], marker='o', markersize = 8, linestyle='-', label='t(ɢHʏPᴀʀᴛ-O)/t(ɢHʏPᴀʀᴛ)', color="grey", linewidth=2)
# ax.plot(index_list[:-1], data.iloc[:,30][:-1] / data.iloc[:,2][:-1], marker='o', markersize = 8, linestyle='-', label='t(ɢHʏPᴀʀᴛ-O)/t(ɢHʏPᴀʀᴛ-B)', color="blue", linewidth=2)
ax.set_ylabel('Performance \nNormalized to ɢHʏPᴀʀᴛ-O', va='center', fontsize=40, fontweight='bold', labelpad=50)  # 设置纵坐标title
'''
# ax.fill_between(index_list[:-1], y1[:-1], color=colors[7], alpha=.5) 
# ax.fill_between(index_list[:-1], y2[:-1], color=colors[6], alpha=.5) 

# ax.fill_between(index_list[:-1], y1[:-1] / y2[:-1], alpha=.5)
area = np.trapz(y1[:-1] / y2[:-1], index_list[:-1])
print(area)
# ax.text(len(x) / 2, 0.5, f'Area Ratio: {area:.2f} / {len(x)-1} = {area/(len(x)-1):.2%}', ha='center', va='center', fontsize=30, color='black')
# last_value1 = gmean(data.iloc[:,30][:-1] / data.iloc[:,29][:-1])

# plt.annotate(f'Max: ({max_x:.2f}, {max_y:.2f})', xy=(max_x, max_y), xytext=(max_x + 0.1, max_y + 0.1),
#              arrowprops=dict(facecolor='black', arrowstyle='->'))

# last_center = 525
# bar1_pos = last_center - 3
# bar2_pos = last_center + 7
# width = 24 # 12 #
# last_center = len(x)+0.5
# bar1_pos = last_center + 3
# bar2_pos = last_center + 5.3
# width = 3.5
# last_center = len(x)+1.5
# bar1_pos = last_center + 3
# bar2_pos = last_center + 5.3
width = 7
# last_center = len(x)+5.5
# bar1_pos = last_center + 3
# bar2_pos = last_center + 5.3
# width = 6.5
# ax.bar(bar1_pos, y1.iloc[-1], width=width, label='', edgecolor='black', color=colors[7], hatch='')
# ax.bar(bar2_pos, y2.iloc[-1], width=width, label='', edgecolor='black', color='red', hatch='.')

# ax.bar(bar1_pos + 7, last_value1, width=width, label='', edgecolor='black', color=colors[7], hatch='')

ax.bar(len(x) + 6.5, y1.iloc[-1], width=width, label='', edgecolor='black', color=mycolors[0], hatch='')

ax.axvline([len(x) + 1], color='grey', linestyle='dashed', linewidth=2)

ax.yaxis.grid(True, color='gray', linestyle = '--', linewidth = 0.5)  # horizontal grid, another method
# 设置y轴刻度标签加粗
for tick in ax.yaxis.get_major_ticks():
    tick.label1.set_fontweight('bold')
    
# last_label_pos = 530
# xticks = list(plt.xticks()[0]) + [last_label_pos]
# xticklabels = list(plt.xticks()[1]) + ['GMean']
# plt.xticks(xticks, xticklabels)

# # last_label_pos = len(x)+3.5
last_label_pos = len(x)+7
# last_label_pos = len(x)+8.5
xticks = list(ax.get_xticks()) + [last_label_pos]
xticklabels = list(ax.get_xticklabels()) + ['GMean']
ax.set_xticks(xticks)
ax.set_xticklabels(xticklabels)

xtick_labels = ax.get_xticklabels()
# 设置最后一个xtick label的大小、角度和颜色
last_xtick_label = xtick_labels[-1]
last_xtick_label.set_fontsize(50)  # 设置大小为12
last_xtick_label.set_rotation(0)  # 设置角度为45度
# last_xtick_label.set_color('black')  # 设置颜色为红色

last_value1 = y1.iloc[-1]
# last_value2 = y2.iloc[-1]
# ax.text(bar1_pos, last_value1 + 1, "ɢHʏPᴀʀᴛ:[{:.2f}]".format(last_value1), color='black', ha='center', fontsize=30, rotation=90)
# ax.text(bar2_pos+0.5, last_value2 + 1, "ɢHʏPᴀʀᴛ-O:[{:.2f}]".format(last_value2), color='red', ha='center', fontsize=30, rotation=90)
# ax.text(bar1_pos, last_value1 + 5, "ɢHʏPᴀʀᴛ:[{:.2f}]".format(last_value1), color='black', ha='center', fontsize=30, rotation=90)
# ax.text(bar2_pos, last_value2 + 5, "ɢHʏPᴀʀᴛ-O:[{:.2f}]".format(last_value2), color='red', ha='center', fontsize=30, rotation=90)

ax.text(len(x) + 6.5, last_value1 + 1, "{:.2f}".format(last_value1), color='black', ha='center', fontsize=40, rotation=0)

ax.text(len(x)-3, max(y1[:-1])+50, "{:.2f}".format(max(y1[:-1])), color='black', ha='center', fontsize=40, rotation=0)

print(last_value1)
# ax.text(bar1_pos + 7, 0.5, "{:.1%}".format(last_value1), color='black', ha='center', fontsize=40, rotation=90)

# 显示图例  
# plt.legend()
# handles, labels = ax.get_legend_handles_labels()
# legend = ax.legend(handles, labels, bbox_to_anchor=(0.79, 0.90), loc='center', ncol=2, frameon=True)
# # legend = ax.legend(handles, labels, bbox_to_anchor=(0.5, 1.08), loc='center', ncol=2, frameon=True)
# frame = legend.get_frame()
# frame.set_edgecolor('#808080')  # 设置边框颜色
# frame.set_linewidth(2)  # 设置边框粗细
# frame.set_alpha(1)  # 设置边框透明度

# 加粗边框对象
spines = ax.spines
spines['top'].set_linewidth(5)
spines['bottom'].set_linewidth(5)
spines['left'].set_linewidth(5)
spines['right'].set_linewidth(5)  

# 调整布局以适应标签
plt.tight_layout()

output = f'results/benchmarks_all_patterns_top100_3090_{current_date}.pdf'

# 保存图片
plt.savefig(output, dpi=300, bbox_inches='tight')

# 显示图形  
plt.show()
