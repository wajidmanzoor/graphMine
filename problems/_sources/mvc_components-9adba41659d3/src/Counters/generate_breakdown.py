from pathlib import Path
from io import StringIO
import re

import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import matplotlib.ticker as mticker


FOLDER = Path(__file__).resolve().parent
OUTPUT_IMAGE = FOLDER / "breakdown.jpg"

PREFIX = "Counters_"
SUFFIX = ".txt"


categories = {
    "Reduction rules": [
        "Degree-two-triangle rule",
        "High-degree rule",
        "Degree-one rule",
        "Stopping condition",
    ],
    "Branching": [
        "Find max degree vertex",
        "Remove max-degree vertex",
        "Remove neighbors of max-degree vertex",
        "Components search",
    ],
    "Work distribution": [
        "Remove from worklist",
        "Add to worklist",
        "Pop from stack",
        "Push to stack",
        "Terminate",
    ],
    "Preprocessing": [
        "Reducing graph and inducing sub-graph",
        "Find boundaries",
    ],
}

base_colors = {
    "Reduction rules": "green",
    "Branching": "purple",
    "Work distribution": "orange",
    "Preprocessing": "blue",
}


def generate_shades(base_color, num_shades):
    cmap = {
        "green": plt.cm.Greens,
        "purple": plt.cm.Purples,
        "orange": plt.cm.Oranges,
        "blue": plt.cm.Blues,
    }[base_color]

    return [cmap(i / (num_shades + 1)) for i in range(1, num_shades + 1)]


feature_colors = {}
for category, features in categories.items():
    shades = generate_shades(base_colors[category], len(features))
    for feature, color in zip(features, shades):
        feature_colors[feature] = color


def parse_time_ms(line):
    match = re.search(r"([-+]?\d+(?:\.\d+)?)\s*ms", line)
    if match:
        return float(match.group(1))

    match = re.search(r"([-+]?\d+(?:\.\d+)?)", line)
    if match:
        return float(match.group(1))

    return 0.0


def read_counter_file(path):
    csv_lines = []
    reduce_and_induce_time = 0.0
    kernel_time = 0.0

    with path.open("r", encoding="utf-8") as file:
        for line in file:
            stripped = line.strip()

            if not stripped:
                continue

            if stripped.startswith("Reduce and Induce time:"):
                reduce_and_induce_time = parse_time_ms(stripped)
            elif stripped.startswith("Kernel time:"):
                kernel_time = parse_time_ms(stripped)
            elif "," in stripped:
                csv_lines.append(line)

    if not csv_lines:
        return None, reduce_and_induce_time, kernel_time

    df = pd.read_csv(StringIO("".join(csv_lines)))
    return df, reduce_and_induce_time, kernel_time


def get_graph_name(path):
    filename = path.name
    return filename[len(PREFIX):-len(SUFFIX)]


def build_data():
    data = {}
    total_times = {}

    counter_files = sorted(
        path for path in FOLDER.glob(f"{PREFIX}*{SUFFIX}")
        if path.is_file()
    )

    for counter_file in counter_files:
        df, reduce_and_induce_time, kernel_time = read_counter_file(counter_file)

        if df is None:
            continue

        available_columns = [
            col for col in feature_colors
            if col in df.columns and col != "Reducing graph and inducing sub-graph"
        ]

        total_time = reduce_and_induce_time + kernel_time
        if total_time > 0:
            reduce_percentage = (reduce_and_induce_time / total_time) * 100.0
            remaining_percentage = (kernel_time / total_time) * 100.0
        else:
            reduce_percentage = 0.0
            remaining_percentage = 100.0

        counter_sums = df[available_columns].sum()
        total_counter_cycles = counter_sums.sum()

        if total_counter_cycles > 0:
            percentages = (counter_sums / total_counter_cycles) * remaining_percentage
        else:
            percentages = counter_sums * 0.0

        percentages["Reducing graph and inducing sub-graph"] = reduce_percentage

        graph_name = get_graph_name(counter_file)
        data[graph_name] = percentages
        total_times[graph_name] = reduce_and_induce_time + kernel_time

    return data, total_times


def add_legends(fig, data_df):
    legend_boxes = []
    category_positions = [0.10, 0.46, 0.81, 1.135]

    for i, (category, features) in enumerate(categories.items()):
        handles = []
        labels = []

        for feature in features:
            if data_df.empty or feature in data_df.columns:
                handles.append(Line2D([0], [0], color=feature_colors[feature], lw=4))

                label = feature
                if label == "Reducing graph and inducing sub-graph":
                    label = "Reducing graph\nand inducing sub-graph"
                elif label == "Remove neighbors of max-degree vertex":
                    label = "Remove neighbors of\nmax-degree vertex"

                labels.append(label)

        if handles:
            legend = fig.legend(
                handles,
                labels,
                title=category,
                loc="upper center",
                bbox_to_anchor=(category_positions[i], -0.005),
                ncol=1,
                frameon=True,
                fontsize=24,
            )
            legend_boxes.append(legend)

    return legend_boxes


def main():
    data, total_times = build_data()

    plt.rcParams.update({
        "font.size": 24,
        "axes.labelsize": 24,
        "xtick.labelsize": 24,
        "ytick.labelsize": 24,
        "legend.fontsize": 24,
        "axes.titlesize": 24,
        "font.family": "DejaVu Sans",
    })

    fig, ax = plt.subplots(figsize=(16, 18))

    if data:
        data_df = pd.DataFrame(data).T.fillna(0.0)
        data_df = data_df.loc[
            sorted(data_df.index, key=lambda graph_name: total_times[graph_name])
        ]

        ordered_columns = [
            feature
            for features in categories.values()
            for feature in features
            if feature in data_df.columns
        ]
        if "Reducing graph and inducing sub-graph" in ordered_columns:
            ordered_columns.remove("Reducing graph and inducing sub-graph")
            ordered_columns.append("Reducing graph and inducing sub-graph")
        data_df = data_df[ordered_columns]

        data_df.plot(
            kind="bar",
            stacked=True,
            ax=ax,
            width=0.7,
            color=[feature_colors[feature] for feature in data_df.columns],
        )

        ax.get_legend().remove()
        plt.xticks(rotation=45, ha="right")
    else:
        data_df = pd.DataFrame()
        ax.set_xticks([])

    ax.set_ylim(0, 105)
    ax.yaxis.set_major_locator(mticker.MultipleLocator(10))
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, linestyle="--", linewidth=2, alpha=1)
    ax.set_ylabel("Percentage of total execution time")

    add_legends(fig, data_df)

    plt.subplots_adjust(bottom=0.18)
    plt.subplots_adjust(left=0.05, right=1.3)

    plt.savefig(OUTPUT_IMAGE, dpi=300, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()