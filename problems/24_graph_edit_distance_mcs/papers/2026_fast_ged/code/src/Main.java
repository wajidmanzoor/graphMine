import org.jgrapht.UndirectedGraph;

import java.io.BufferedReader;
import java.io.FileReader;
import java.io.IOException;
import java.io.PrintWriter;
import java.util.Stack;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class Main {
    private static float cost_node_sub = 0;
    private static float cost_node_del_ins = 0;

    private static float cost_edge_sub = 0;
    private static float cost_edge_del_ins = 0;

    private static String file_g1 = null;
    private static String file_g2 = null;
    public static JGraphTtoGPU g1Gpu = null;
    public static JGraphTtoGPU g2Gpu = null;
    private static PrintWriter out = null;
    public static Stack[] stackTable = new Stack[1000000000];

    private static String separator = ";";
    public static int k_best;
    public static int dinamique;

    public static void main(String[] args) throws IOException {
        String pathname_result_output_file = null;
        String test_benchmark = null;
        int amount_RunTime_S = 0;

        if (args.length >= 9) {
            try {
                cost_node_sub = Float.parseFloat(args[0]);
                cost_node_del_ins = Float.parseFloat(args[1]);
                cost_edge_sub = Float.parseFloat(args[2]);
                cost_edge_del_ins = Float.parseFloat(args[3]);

                file_g1 = args[4];
                file_g2 = args[5];

                Pattern pattern = Pattern.compile("\"([^\"]*)\"");
                Matcher matcher = pattern.matcher(file_g1);
                while (matcher.find()) {
                    file_g1 = matcher.group(1);
                }

                matcher = pattern.matcher(file_g2);
                while (matcher.find()) {
                    file_g2 = matcher.group(1);
                }

                pathname_result_output_file = args[6];
                test_benchmark = args[7];
                amount_RunTime_S =0;// Integer.parseInt(args[8]);
                dinamique =0;// Integer.parseInt(args[9]);
                if (dinamique == 0) {
                    k_best = Integer.parseInt(args[8]);
                } else {
                    k_best = 3;
                }
                if (k_best < 1) {
                    System.err.println("k_best must be greater than or equal to 1.");
                    System.exit(1);
                }
            } catch (NumberFormatException e) {
                System.err.println("Argument : " + e.getMessage() + " must be an integer.");
                System.exit(1);
            }
        }

        JGraphTtoGPU.CrreateGpuContex();

        UndirectedGraph<Vertex, Edge> g1 = null;
        UndirectedGraph<Vertex, Edge> g2 = null;

        if (test_benchmark.equals("PATH")) {
            g1 = Import_JGraphT_From_GXL.import_simple_graph(file_g1);
            g2 = Import_JGraphT_From_GXL.import_simple_graph(file_g2);

        } else if (test_benchmark.equals("GREC")) {
            g1 = Import_JGraphT_From_GXL.import_simple_graph_from_GREC_GED(file_g1);
            g2 = Import_JGraphT_From_GXL.import_simple_graph_from_GREC_GED(file_g2);
        } else if (test_benchmark.equals("PROT")) {
            g1 = Import_JGraphT_From_GXL.GxlReader(file_g1);
        } else if (test_benchmark.equals("MUTA")) {
            g1 = Import_JGraphT_From_GXL.import_simple_graph_from_MUTA_GED(file_g1);
            g2 = Import_JGraphT_From_GXL.import_simple_graph_from_MUTA_GED(file_g2);
        } else if (test_benchmark.equals("CMU")) {
            g1 = Import_JGraphT_From_GXL.import_simple_graph_from_CMU_GED(file_g1);
            g2 = Import_JGraphT_From_GXL.import_simple_graph_from_CMU_GED(file_g2);
        } else if (test_benchmark.equals("NETX")) {
            g1 = Import_JGraphT_From_GXL.GxlReader(file_g1);
            g2 = Import_JGraphT_From_GXL.GxlReader(file_g2);
        } else {
            g1 = Import_JGraphT_From_GXL.import_simple_graph_from_MUTA_GED(file_g1);
            g2 = Import_JGraphT_From_GXL.import_simple_graph_from_MUTA_GED(file_g2);
        }

        if (g1 == null) {
            System.out.println("Can't Load the First Graph : " + file_g1);
            return;
        } else {
            g1Gpu = new JGraphTtoGPU();
            g1Gpu.set_data(g1);
            g1Gpu.set_gpu_data(g1);
        }

        GPU_GED_BB_DF exact_GED = new GPU_GED_BB_DF(amount_RunTime_S);
        GED_Operations_Cost.setAll_Operations_cost(cost_node_sub, cost_node_del_ins, cost_node_del_ins * 1, cost_edge_sub, cost_edge_del_ins * 1, cost_edge_del_ins, 1);
        GED_Operations_Cost.setIs_Weight(true);
        GED_Operations_Cost.setIs_Label(false);

        g2Gpu = new JGraphTtoGPU();
        g2Gpu.set_data(g2);
        g2Gpu.set_gpu_data(g2);

        long startTime = System.nanoTime();
        double editDistance = exact_GED.computeGED(g1, g2);
        try (PrintWriter writer = new PrintWriter(pathname_result_output_file)) {
            writer.println(exact_GED.optimal_Path.toString());
        } catch (IOException e) {
            System.err.println("Error writing to file: " + e.getMessage());
        }
        System.out.println(exact_GED.optimal_Path.toString());
        long endTime = System.nanoTime();
        long elapsedTime = endTime - startTime;

        g2Gpu.free_gpu_data();
        g1Gpu.free_gpu_data();
    }
}
