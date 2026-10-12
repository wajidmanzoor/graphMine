import csv
from sys import argv

txt_file = argv[1]
csv_file = argv[2]
header = ['From Node ID', 'To Node ID', 'Weight']
with open(txt_file, "r") as in_text:
    in_reader = csv.reader(in_text, delimiter = '\t')
    with open(csv_file, "w") as out_csv:
        out_writer = csv.writer(out_csv)
        out_writer.writerow(header)
        data_list = list(csv.reader(in_text, delimiter = '\t'))
        data_list = data_list[4:]
        for row in data_list:
            out_writer.writerow(row)

