import sys
sys.path.append('../')
import input_header as input

def run_pattern(out, file_path, our_impl, patterns, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel5 1 -usenewkernel1_2_3 1 -usenewkernel12 0 -newParBaseK12 1 -useMemOpt 1 > " + LOG, shell=True)
    with open(LOG, 'r') as file:
        reader = input.csv.reader(file)
        cur = []
        for row in reader:
            if row and "Total execution time (s)" in row[0]:
                our_impl.append(float(row[0][26:]))
            if row and "pattern for K12" in row[0]:
                cur.append(row[1])
                cur.append(row[2])
            if row and "pattern for K1K2K3K5" in row[0]:
                cur.append(row[1])
                cur.append(row[2])
            if row and "pattern for K4K6" in row[0]:
                cur.append(row[1])
                cur.append(row[2])
        patterns['p2_k12'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.flush()
    
def run_pattern_p2(out, file_path, our_impl, patterns, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel5 1 -usenewkernel1_2_3 1 \
                        -useKernel4Opt 1 -useKernel6Opt 1 -useP2ForK4 1 -useP2ForK6 1 \
                        -usenewkernel12 0 -newParBaseK12 1 -useMemOpt 1 > " + LOG, shell=True)
    with open(LOG, 'r') as file:
        reader = input.csv.reader(file)
        cur = []
        for row in reader:
            if row and "Total execution time (s)" in row[0]:
                our_impl.append(float(row[0][26:]))
            if row and "pattern for K12" in row[0]:
                cur.append(row[1])
                cur.append(row[2])
            if row and "pattern for K1K2K3K5" in row[0]:
                cur.append(row[1])
                cur.append(row[2])
            if row and "pattern for K4K6" in row[0]:
                cur.append(row[1])
                cur.append(row[2])
        patterns['p2_k12_p2_k4_k6'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.flush()
    
def run_pattern_p3(out, file_path, our_impl, patterns, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel5 1 -usenewkernel1_2_3 1 \
                        -useKernel4Opt 1 -useKernel6Opt 1 \
                        -usenewkernel12 0 -newParBaseK12 1 -useMemOpt 1 > " + LOG, shell=True)
    with open(LOG, 'r') as file:
        reader = input.csv.reader(file)
        cur = []
        for row in reader:
            if row and "Total execution time (s)" in row[0]:
                our_impl.append(float(row[0][26:]))
            if row and "pattern for K12" in row[0]:
                cur.append(row[1])
                cur.append(row[2])
            if row and "pattern for K1K2K3K5" in row[0]:
                cur.append(row[1])
                cur.append(row[2])
            if row and "pattern for K4K6" in row[0]:
                cur.append(row[1])
                cur.append(row[2])
        patterns['p2_k12_p3_k4_split_k6'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.flush()