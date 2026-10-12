from pathlib import Path
import csv

FOLDER = Path(__file__).resolve().parent
OUTPUT_FILE = FOLDER / "nodes_visited.csv"
PREFIX = "NODES_PER_SM_"
SUFFIX = ".txt"


def sum_numbers_in_file(path):
    total = 0

    with path.open("r", newline="") as file:
        reader = csv.reader(file)

        for row in reader:
            for cell in row:
                cell = cell.strip()

                if cell.isdigit():
                    total += int(cell)

    return total


def get_graph_name(path):
    filename = path.name
    return filename[len(PREFIX):-len(SUFFIX)]


def main():
    txt_files = sorted(
        path for path in FOLDER.glob("*.txt")
        if path.name.startswith(PREFIX) and path.name.endswith(SUFFIX)
    )

    with OUTPUT_FILE.open("w", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(["Graph", "Nodes Visited"])

        for txt_file in txt_files:
            graph_name = get_graph_name(txt_file)
            nodes_visited = sum_numbers_in_file(txt_file)

            writer.writerow([graph_name, nodes_visited])


if __name__ == "__main__":
    main()