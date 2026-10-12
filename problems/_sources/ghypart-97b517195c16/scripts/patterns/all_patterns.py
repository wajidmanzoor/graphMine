import sys
sys.path.append('../')
import input_header as input

def p1_k1235_p1_k4k6_p2_k12(out, file_path, our_impl, patterns, LOG):
    # input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
    #                     -usenewkernel12 0 -newParBaseK12 1 > " + LOG, shell=True)
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel12 0 -newParBaseK12 1 -useMemOpt 1 > " + LOG, shell=True)
    # try:
        # command = "../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -usenewkernel12 0 -newParBaseK12 1 > " + LOG
        # output = input.subprocess.check_output(command, 
        #                                        shell=True, encoding="utf-8", stderr=input.subprocess.STDOUT)
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
        patterns['p1_k1235_p1_k4k6_p2_k12'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    # except input.subprocess.CalledProcessError as e:
    #     print("########", e.output)
    #     # output = e.output.decode("utf-8")
    #     if "Floating point exception" in output:
    #         print("捕获到浮点异常 (Floating point exception)")
    out.flush()
    
def p2_k1235_p1_k4k6_p2_k12(out, file_path, our_impl, patterns, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel12 0 -newParBaseK12 1 \
                        -usenewkernel1_2_3 1 -useP2ForK1 1 -usenewkernel5 1 -useMemOpt 1 > " + LOG, shell=True)
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
        patterns['p2_k1235_p1_k4k6_p2_k12'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.flush()
    
def p3_k1235_p1_k4k6_p2_k12(out, file_path, our_impl, patterns, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel12 0 -newParBaseK12 1 \
                        -usenewkernel1_2_3 1 -useP2ForK1 0 -usenewkernel5 1 -useMemOpt 1 > " + LOG, shell=True)
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
        patterns['p3_k1235_p1_k4k6_p2_k12'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.flush()   
    
def p1_k1235_p2_k4k6_p2_k12(out, file_path, our_impl, patterns, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel12 0 -newParBaseK12 1 \
                        -usenewkernel1_2_3 0 -useP2ForK1 0 -usenewkernel5 1 \
                        -useKernel4Opt 1 -useKernel6Opt 1 -useP2ForK4 1 -useP2ForK6 1 -useMemOpt 1 > " + LOG, shell=True)
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
        patterns['p1_k1235_p2_k4k6_p2_k12'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.flush() 
    
def p2_k1235_p2_k4k6_p2_k12(out, file_path, our_impl, patterns, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel12 0 -newParBaseK12 1 \
                        -usenewkernel1_2_3 1 -useP2ForK1 1 -usenewkernel5 1 \
                        -useKernel4Opt 1 -useKernel6Opt 1 -useP2ForK4 1 -useP2ForK6 1 -useMemOpt 1 > " + LOG, shell=True)
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
        patterns['p2_k1235_p2_k4k6_p2_k12'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.flush()   
    
def p3_k1235_p2_k4k6_p2_k12(out, file_path, our_impl, patterns, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel12 0 -newParBaseK12 1 \
                        -usenewkernel1_2_3 1 -useP2ForK1 0 -usenewkernel5 1 \
                        -useKernel4Opt 1 -useKernel6Opt 1 -useP2ForK4 1 -useP2ForK6 1 -useMemOpt 1 > " + LOG, shell=True)
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
        patterns['p3_k1235_p2_k4k6_p2_k12'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.flush() 
    
def p1_k1235_p3_k4k6_p2_k12(out, file_path, our_impl, patterns, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel12 0 -newParBaseK12 1 \
                        -usenewkernel1_2_3 0 -useP2ForK1 0 -usenewkernel5 1 \
                        -useKernel4Opt 1 -useKernel6Opt 1 -useP2ForK4 0 -useP2ForK6 0 -useMemOpt 1 > " + LOG, shell=True)
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
        patterns['p1_k1235_p3_k4k6_p2_k12'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.flush()
    
def p2_k1235_p3_k4k6_p2_k12(out, file_path, our_impl, patterns, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel12 0 -newParBaseK12 1 \
                        -usenewkernel1_2_3 1 -useP2ForK1 1 -usenewkernel5 1 \
                        -useKernel4Opt 1 -useKernel6Opt 1 -useP2ForK4 0 -useP2ForK6 0 -useMemOpt 1 > " + LOG, shell=True)
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
        patterns['p2_k1235_p3_k4k6_p2_k12'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.flush() 
    
def p3_k1235_p3_k4k6_p2_k12(out, file_path, our_impl, patterns, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel12 0 -newParBaseK12 1 \
                        -usenewkernel1_2_3 1 -useP2ForK1 0 -usenewkernel5 1 \
                        -useKernel4Opt 1 -useKernel6Opt 1 -useP2ForK4 0 -useP2ForK6 0 -useMemOpt 1 > " + LOG, shell=True)
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
        patterns['p3_k1235_p3_k4k6_p2_k12'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.flush() 
    
def p1_k1235_p1_k4k6_p3_k12(out, file_path, our_impl, patterns, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel12 0 -newParBaseK12 2 -sort 1 \
                        -usenewkernel14 1 -newParBaseK14 2 \
                        -usenewkernel1_2_3 0 -useP2ForK1 0 -usenewkernel5 1 \
                        -useKernel4Opt 0 -useKernel6Opt 0 -useP2ForK4 0 -useP2ForK6 0 -useMemOpt 1 > " + LOG, shell=True)
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
        patterns['p1_k1235_p1_k4k6_p3_k12'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.flush() 
    
def p2_k1235_p1_k4k6_p3_k12(out, file_path, our_impl, patterns, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel12 0 -newParBaseK12 2 -sort 1 \
                        -usenewkernel14 1 -newParBaseK14 2 \
                        -usenewkernel1_2_3 1 -useP2ForK1 1 -usenewkernel5 1 \
                        -useKernel4Opt 0 -useKernel6Opt 0 -useP2ForK4 0 -useP2ForK6 0 -useMemOpt 1 > " + LOG, shell=True)
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
        patterns['p2_k1235_p1_k4k6_p3_k12'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.flush()
    
def p3_k1235_p1_k4k6_p3_k12(out, file_path, our_impl, patterns, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel12 0 -newParBaseK12 2 -sort 1 \
                        -usenewkernel14 1 -newParBaseK14 2 \
                        -usenewkernel1_2_3 1 -useP2ForK1 0 -usenewkernel5 1 \
                        -useKernel4Opt 0 -useKernel6Opt 0 -useP2ForK4 0 -useP2ForK6 0 -useMemOpt 1 > " + LOG, shell=True)
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
        patterns['p3_k1235_p1_k4k6_p3_k12'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.flush() 
    
def p1_k1235_p2_k4k6_p3_k12(out, file_path, our_impl, patterns, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel12 0 -newParBaseK12 2 -sort 1 \
                        -usenewkernel14 1 -newParBaseK14 2 \
                        -usenewkernel1_2_3 0 -useP2ForK1 0 -usenewkernel5 1 \
                        -useKernel4Opt 1 -useKernel6Opt 1 -useP2ForK4 1 -useP2ForK6 1 -useMemOpt 1 > " + LOG, shell=True)
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
        patterns['p1_k1235_p2_k4k6_p3_k12'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.flush() 
    
def p2_k1235_p2_k4k6_p3_k12(out, file_path, our_impl, patterns, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel12 0 -newParBaseK12 2 -sort 1 \
                        -usenewkernel14 1 -newParBaseK14 2 \
                        -usenewkernel1_2_3 1 -useP2ForK1 1 -usenewkernel5 1 \
                        -useKernel4Opt 1 -useKernel6Opt 1 -useP2ForK4 1 -useP2ForK6 1 -useMemOpt 1 > " + LOG, shell=True)
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
        patterns['p2_k1235_p2_k4k6_p3_k12'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.flush() 
    
def p3_k1235_p2_k4k6_p3_k12(out, file_path, our_impl, patterns, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel12 0 -newParBaseK12 2 -sort 1 \
                        -usenewkernel14 1 -newParBaseK14 2 \
                        -usenewkernel1_2_3 1 -useP2ForK1 0 -usenewkernel5 1 \
                        -useKernel4Opt 1 -useKernel6Opt 1 -useP2ForK4 1 -useP2ForK6 1 -useMemOpt 1 > " + LOG, shell=True)
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
        patterns['p3_k1235_p2_k4k6_p3_k12'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.flush() 
    
def p1_k1235_p3_k4k6_p3_k12(out, file_path, our_impl, patterns, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel12 0 -newParBaseK12 2 -sort 1 \
                        -usenewkernel14 1 -newParBaseK14 2 \
                        -usenewkernel1_2_3 0 -useP2ForK1 0 -usenewkernel5 1 \
                        -useKernel4Opt 1 -useKernel6Opt 1 -useP2ForK4 0 -useP2ForK6 0 -useMemOpt 1 > " + LOG, shell=True)
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
        patterns['p1_k1235_p3_k4k6_p3_k12'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.flush() 
    
def p2_k1235_p3_k4k6_p3_k12(out, file_path, our_impl, patterns, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel12 0 -newParBaseK12 2 -sort 1 \
                        -usenewkernel14 1 -newParBaseK14 2 \
                        -usenewkernel1_2_3 1 -useP2ForK1 1 -usenewkernel5 1 \
                        -useKernel4Opt 1 -useKernel6Opt 1 -useP2ForK4 0 -useP2ForK6 0 -useMemOpt 1 > " + LOG, shell=True)
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
        patterns['p2_k1235_p3_k4k6_p3_k12'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.flush() 
    
def p3_k1235_p3_k4k6_p3_k12(out, file_path, our_impl, patterns, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel12 0 -newParBaseK12 2 -sort 1 \
                        -usenewkernel14 1 -newParBaseK14 2 \
                        -usenewkernel1_2_3 1 -useP2ForK1 0 -usenewkernel5 1 \
                        -useKernel4Opt 1 -useKernel6Opt 1 -useP2ForK4 0 -useP2ForK6 0 -useMemOpt 1 > " + LOG, shell=True)
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
        patterns['p3_k1235_p3_k4k6_p3_k12'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.flush() 
    
def p1_k1235_p1_k4k6_p2b_k12(out, file_path, our_impl, patterns, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel12 1 -newParBaseK12 0 -sort 1 \
                        -usenewkernel14 1 -newParBaseK14 1 \
                        -usenewkernel1_2_3 0 -useP2ForK1 0 -usenewkernel5 1 \
                        -useKernel4Opt 0 -useKernel6Opt 0 -useP2ForK4 0 -useP2ForK6 0 -useMemOpt 1 > " + LOG, shell=True)
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
        patterns['p1_k1235_p1_k4k6_p2b_k12'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.flush() 
    
def p2_k1235_p1_k4k6_p2b_k12(out, file_path, our_impl, patterns, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel12 1 -newParBaseK12 0 -sort 1 \
                        -usenewkernel14 1 -newParBaseK14 1 \
                        -usenewkernel1_2_3 1 -useP2ForK1 1 -usenewkernel5 1 \
                        -useKernel4Opt 0 -useKernel6Opt 0 -useP2ForK4 0 -useP2ForK6 0 -useMemOpt 1 > " + LOG, shell=True)
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
        patterns['p2_k1235_p1_k4k6_p2b_k12'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.flush() 
    
def p3_k1235_p1_k4k6_p2b_k12(out, file_path, our_impl, patterns, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel12 1 -newParBaseK12 0 -sort 1 \
                        -usenewkernel14 1 -newParBaseK14 1 \
                        -usenewkernel1_2_3 1 -useP2ForK1 0 -usenewkernel5 1 \
                        -useKernel4Opt 0 -useKernel6Opt 0 -useP2ForK4 0 -useP2ForK6 0 -useMemOpt 1 > " + LOG, shell=True)
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
        patterns['p3_k1235_p1_k4k6_p2b_k12'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.flush() 
    
def p1_k1235_p2_k4k6_p2b_k12(out, file_path, our_impl, patterns, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel12 1 -newParBaseK12 0 -sort 1 \
                        -usenewkernel14 1 -newParBaseK14 1 \
                        -usenewkernel1_2_3 0 -useP2ForK1 0 -usenewkernel5 1 \
                        -useKernel4Opt 1 -useKernel6Opt 1 -useP2ForK4 1 -useP2ForK6 1 -useMemOpt 1 > " + LOG, shell=True)
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
        patterns['p1_k1235_p2_k4k6_p2b_k12'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.flush() 
    
def p2_k1235_p2_k4k6_p2b_k12(out, file_path, our_impl, patterns, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel12 1 -newParBaseK12 0 -sort 1 \
                        -usenewkernel14 1 -newParBaseK14 1 \
                        -usenewkernel1_2_3 1 -useP2ForK1 1 -usenewkernel5 1 \
                        -useKernel4Opt 1 -useKernel6Opt 1 -useP2ForK4 1 -useP2ForK6 1 -useMemOpt 1 > " + LOG, shell=True)
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
        patterns['p2_k1235_p2_k4k6_p2b_k12'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.flush()
    
def p3_k1235_p2_k4k6_p2b_k12(out, file_path, our_impl, patterns, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel12 1 -newParBaseK12 0 -sort 1 \
                        -usenewkernel14 1 -newParBaseK14 1 \
                        -usenewkernel1_2_3 1 -useP2ForK1 0 -usenewkernel5 1 \
                        -useKernel4Opt 1 -useKernel6Opt 1 -useP2ForK4 1 -useP2ForK6 1 -useMemOpt 1 > " + LOG, shell=True)
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
        patterns['p3_k1235_p2_k4k6_p2b_k12'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.flush() 
    
def p1_k1235_p3_k4k6_p2b_k12(out, file_path, our_impl, patterns, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel12 1 -newParBaseK12 0 -sort 1 \
                        -usenewkernel14 1 -newParBaseK14 1 \
                        -usenewkernel1_2_3 0 -useP2ForK1 0 -usenewkernel5 1 \
                        -useKernel4Opt 1 -useKernel6Opt 1 -useP2ForK4 0 -useP2ForK6 0 -useMemOpt 1 > " + LOG, shell=True)
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
        patterns['p1_k1235_p3_k4k6_p2b_k12'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.flush() 
    
def p2_k1235_p3_k4k6_p2b_k12(out, file_path, our_impl, patterns, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel12 1 -newParBaseK12 0 -sort 1 \
                        -usenewkernel14 1 -newParBaseK14 1 \
                        -usenewkernel1_2_3 1 -useP2ForK1 1 -usenewkernel5 1 \
                        -useKernel4Opt 1 -useKernel6Opt 1 -useP2ForK4 0 -useP2ForK6 0 -useMemOpt 1 > " + LOG, shell=True)
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
        patterns['p2_k1235_p3_k4k6_p2b_k12'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.flush() 
    
def p3_k1235_p3_k4k6_p2b_k12(out, file_path, our_impl, patterns, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -usenewkernel12 1 -newParBaseK12 0 -sort 1 \
                        -usenewkernel14 1 -newParBaseK14 1 \
                        -usenewkernel1_2_3 1 -useP2ForK1 0 -usenewkernel5 1 \
                        -useKernel4Opt 1 -useKernel6Opt 1 -useP2ForK4 0 -useP2ForK6 0 -useMemOpt 1 > " + LOG, shell=True)
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
        patterns['p3_k1235_p3_k4k6_p2b_k12'] = cur
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.flush() 

def random_select_pattern(out, file_path, our_impl, best, selection_k12_pattern, selection_k4_pattern, selection_k1_pattern,
                    avghedgesize, relative_sdv, select_pattern, patterns, edge_cut, 
                    best_k12_pattern, best_k4_pattern, best_k1_pattern,
                    best_speedup, select_speedup, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -randomSelect 1 -useMemOpt 1 > " + LOG, shell=True)
    with open(LOG, 'r') as file:
        reader = input.csv.reader(file)
        cur = []
        for row in reader:
            if row and "Total execution time" in row[0]:
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
        select_pattern['select'] = cur
    selection_k1_pattern = select_pattern['select'][0]
    selection_k4_pattern = select_pattern['select'][2]
    selection_k12_pattern = select_pattern['select'][4]
    out.write(str(our_impl[len(our_impl)-1])+"\n")
    # out.write(selection_k1_pattern+","+selection_k4_pattern+","+selection_k12_pattern)
    out.flush()
                
def select_pattern(out, file_path, our_impl, best, selection_k12_pattern, selection_k4_pattern, selection_k1_pattern,
                    avghedgesize, relative_sdv, select_pattern, patterns, edge_cut, 
                    best_k12_pattern, best_k4_pattern, best_k1_pattern,
                    best_speedup, select_speedup, LOG):
    input.subprocess.call("../build/gHyPart " + file_path + " -bp -wc 0 -useuvm 0 -sort_input 0 \
                        -useSelection 1 -useMemOpt 1 > " + LOG, shell=True)
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
                edge_cut = row[0][20:]
        select_pattern['select'] = cur
    print(select_pattern)
    selection_k1_pattern = select_pattern['select'][0]
    selection_k4_pattern = select_pattern['select'][2]
    selection_k12_pattern = select_pattern['select'][4]
    
    # index = 0
    # for key, value in patterns.items():
    #     print(key, value)
    #     if select_pattern['select'] == value:
    #         ratio = our_impl[index] / our_impl[len(our_impl)-1]
    #         if ratio < 1.0 and ratio >= 0.9:
    #             our_impl[len(our_impl)-1] = min(our_impl[index], our_impl[len(our_impl)-1])
    #     index+=1
    print("@@edge_cut: " + edge_cut)
    print(avghedgesize, relative_sdv)
    print("cur_best:" + str(best))
    best = min(best, our_impl[len(our_impl)-1])
    out.write(str(our_impl[len(our_impl)-1])+",")
    out.write(str(best)+",")
    # out.write(selection_k1_pattern+","+selection_k4_pattern+","+selection_k12_pattern)
    # out.write("\n")
    out.flush()
# ''' 
    for i in range(len(our_impl)):
        if best == our_impl[len(our_impl)-1]:
            best_k12_pattern = selection_k12_pattern
            best_k4_pattern = selection_k4_pattern
            best_k1_pattern = selection_k1_pattern
            break
        if (i == 2 or i == 5 or i == 8 or i == 11 or i == 14 or i == 17 or i == 20 or i == 23 or i == 26):
            if best == our_impl[i]:
                best_k1_pattern = 'P3'
        if (i == 1 or i == 4 or i == 7 or i == 10 or i == 13 or i == 16 or i == 19 or i == 22 or i == 25):
            if best == our_impl[i]:
                best_k1_pattern = 'P2'
        if (i == 0 or i == 3 or i == 6 or i == 9 or i == 12 or i == 15 or i == 18 or i == 21 or i == 24):
            if best == our_impl[i]:
                best_k1_pattern = 'P1'
                
        if (i == 6 or i == 7 or i == 8 or i == 15 or i == 16 or i == 17 or i == 24 or i == 25 or i == 26):
            if best == our_impl[i]:
                best_k4_pattern = 'P3'
        if (i == 3 or i == 4 or i == 5 or i == 12 or i == 13 or i == 14 or i == 21 or i == 22 or i == 23):
            if best == our_impl[i]:
                best_k4_pattern = 'P2'
        if (i == 0 or i == 1 or i == 2 or i == 9 or i == 10 or i == 11 or i == 18 or i == 19 or i == 20):
            if best == our_impl[i]:
                best_k4_pattern = 'P1'
                
        if (i == 18 or i == 19 or i == 20 or i == 21 or i == 22 or i == 23 or i == 24 or i == 25 or i == 26):
            if best == our_impl[i]:
                best_k12_pattern = 'P2b'
        if (i == 9 or i == 10 or i == 11 or i == 12 or i == 13 or i == 14 or i == 15 or i == 16 or i == 17):
            if best == our_impl[i]:
                best_k12_pattern = 'P3'
        if (i == 0 or i == 1 or i == 2 or i == 3 or i == 4 or i == 5 or i == 6 or i == 7 or i == 8):
            if best == our_impl[i]:
                best_k12_pattern = 'P2'
        
    std_impl = input.np.std(input.np.array(our_impl))
    # print("std of each impl time: " + str(std_impl))
    # if std_impl <= 1e-3:
    #     best_k12_pattern = selection_k12_pattern
    print("best_k4k6_pattern: " + best_k4_pattern)
    print("best_k12_pattern: " + best_k12_pattern)
    print("@@selection_k4k6_pattern: " + selection_k4_pattern)
    print("@@selection_k12_pattern: " + selection_k12_pattern)
    # if select_pattern['select'] == [best_k1_pattern, best_k4_pattern, best_k12_pattern]:
    #     our_impl[len(our_impl)-1] = best
    best_speedup = our_impl[0] / best
    select_speedup = our_impl[0] / our_impl[len(our_impl)-1]
    print("##", select_speedup)
    print("##", best_speedup)
    out.write(str(select_speedup)+","+str(best_speedup))
    out.write(","+selection_k1_pattern+","+best_k1_pattern)
    out.write(","+selection_k4_pattern+","+best_k4_pattern)
    out.write(","+selection_k12_pattern+","+best_k12_pattern)
    out.write(","+avghedgesize+","+relative_sdv+","+edge_cut)
    out.write("\n")
    out.flush()
# '''    
    