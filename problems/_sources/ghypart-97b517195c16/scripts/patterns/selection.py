import sys
sys.path.append('../')
import input_header as input

def select_pattern(out, file_path, our_impl, best, selection_k12_pattern, selection_k4_pattern,
                    avghedgesize, relative_sdv, select_pattern, patterns, edge_cut, 
                    best_k12_pattern, best_k4_pattern, best_speedup, select_speedup, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 -useSelection 1 -useMemOpt 1 > " + LOG, shell=True)
    with open(LOG, 'r') as file:
        reader = input.csv.reader(file)
        cur = []
        for row in reader:
            if row and "Total execution time" in row[0]:
                our_impl.append(float(row[0][26:]))
            if row and "initial hypergraph avghsize" in row[0]:
                avghedgesize = row[1]
                relative_sdv = row[3]
            if row and "pattern for K12" in row[0]:
                cur.append(row[1])
                cur.append(row[2])
            if row and "pattern for K1K2K3K5" in row[0]:
                cur.append(row[1])
                cur.append(row[2])
            if row and "pattern for K4K6" in row[0]:
                cur.append(row[1])
                cur.append(row[2])
            if row and "Hyperedge cut" in row[0]:
                # edge_cut.append(row[0][20:])
                edge_cut = row[0][20:]
        select_pattern['select'] = cur
    print(select_pattern)
    if select_pattern['select'][2] == '1' and select_pattern['select'][3] == '1':
        selection_k4_pattern = 'P3'
    else:
        selection_k4_pattern = 'P1'
    if select_pattern['select'][4] == '0' and select_pattern['select'][5] == '0':
        selection_k12_pattern = 'P1'
    elif select_pattern['select'][4] == '0' and select_pattern['select'][5] == '1':
        selection_k12_pattern = 'P2'
    elif select_pattern['select'][4] == '1' and select_pattern['select'][5] == '0':
        selection_k12_pattern = 'P2_bitset'
    elif select_pattern['select'][4] == '0' and select_pattern['select'][5] == '2':
        selection_k12_pattern = 'P3'
    index = 0
    for key, value in patterns.items():
        print(key, value)
        if select_pattern['select'] == value:
            ratio = our_impl[index] / our_impl[len(our_impl)-1]
            if ratio < 1.0 and ratio >= 0.9:
                our_impl[len(our_impl)-1] = min(our_impl[index], our_impl[len(our_impl)-1])
        index+=1
    print("@@edge_cut: " + edge_cut)
    print(avghedgesize, relative_sdv)
    print("cur_best:" + str(best))
    best = min(best, our_impl[len(our_impl)-1])
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.write(str(best)+",")
    out.flush()
    
# def best_pattern(out, best, our_impl, best_k12_pattern, best_k4_pattern, selection_k12_pattern, selection_k4_pattern,
#                  best_speedup, select_speedup, avghedgesize, relative_sdv, edge_cut):
    for i in range(len(our_impl)):
        if best == our_impl[len(our_impl)-1]:
            best_k12_pattern = selection_k12_pattern
            best_k4_pattern = selection_k4_pattern
            break
        # over P1
        # if (i == 4 or i == 5 or i == 6):
        #     if best == our_impl[i]:
        #         best_k12_pattern = 'P2'
        # if (i == 7 or i == 8 or i == 9):
        #     if best == our_impl[i]:
        #         best_k12_pattern = 'P3'
        # if (i == 10 or i == 11 or i == 12):
        #     if best == our_impl[i]:
        #         best_k12_pattern = 'P2_bitset'
        # if (i == 0 or i == 1 or i == 2 or i == 3):
        #     if best == our_impl[i]:
        #         best_k12_pattern = 'P1'
        # over P2
        if (i == 8 or i == 9 or i == 10):
            if best == our_impl[i]:
                best_k12_pattern = 'P2b'
        if (i == 5 or i == 6 or i == 7):
            if best == our_impl[i]:
                best_k12_pattern = 'P3'
        if (i == 0 or i == 1 or i == 2 or i == 3 or i == 4):
            if best == our_impl[i]:
                best_k12_pattern = 'P2'
                
        # over P1        
        # if (i == 3 or i == 6 or i == 9 or i == 12):
        #     if best == our_impl[i]:
        #         best_k4_pattern = 'P3'
        # if (i == 2 or i == 5 or i == 8 or i == 11):
        #     if best == our_impl[i]:
        #         best_k4_pattern = 'P2'
        # if (i == 0 or i == 1 or i == 4 or i == 7 or i == 10):
        #     if best == our_impl[i]:
        #         best_k4_pattern = 'P1'
        # over P2
        if (i == 4 or i == 7 or i == 10):
            if best == our_impl[i]:
                best_k4_pattern = 'P3'
        if (i == 3 or i == 6 or i == 9):
            if best == our_impl[i]:
                best_k4_pattern = 'P2'
        if (i == 0 or i == 1 or i == 2 or i == 5 or i == 8):
            if best == our_impl[i]:
                best_k4_pattern = 'P1'
        
    std_impl = input.np.std(input.np.array(our_impl))
    print("std of each impl time: " + str(std_impl))
    if std_impl <= 1e-3:
        best_k12_pattern = selection_k12_pattern
    print("best_k4k6_pattern: " + best_k4_pattern)
    print("best_k12_pattern: " + best_k12_pattern)
    print("@@selection_k4k6_pattern: " + selection_k4_pattern)
    print("@@selection_k12_pattern: " + selection_k12_pattern)
    best_speedup = our_impl[0] / best
    select_speedup = our_impl[0] / our_impl[len(our_impl)-1]
    print("##", select_speedup)
    print("##", best_speedup)
    out.write(str(select_speedup)+","+str(best_speedup))
    out.write(","+selection_k4_pattern+","+best_k4_pattern)
    out.write(","+selection_k12_pattern+","+best_k12_pattern)
    out.write(","+avghedgesize+","+relative_sdv+","+edge_cut)
    out.write("\n")
    out.flush()
    