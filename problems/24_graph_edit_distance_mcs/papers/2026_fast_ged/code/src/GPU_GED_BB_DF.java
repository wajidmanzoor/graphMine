//import graph_element.Vertex;
import org.jgrapht.Graph;
import jcuda.Pointer;
import jcuda.Sizeof;
import jcuda.driver.*;
import jcuda.nvrtc.nvrtcProgram;
import jcuda.runtime.JCuda;
import jcuda.runtime.cudaMemcpyKind;

import static jcuda.nvrtc.JNvrtc.*;
import static jcuda.driver.JCudaDriver.*;
//import sun.security.provider.certpath.Vertex;

import java.io.IOException;
import java.util.*;
// Exact Graph Edit Distance (GED) with Branch and Bound (BB) Depth First stratigy (DF)

public class GPU_GED_BB_DF {

    /**
     * The set OPEN of partial edit paths contains the search tree nodes
     * to be processed in the next steps.
     */

    class IndexValuePair {
        int index1;
        int index2;
        double value;

        public IndexValuePair(int index1, int index2, double value) {
            this.index1 = index1;
            this.index2 = index2;
            this.value = value;
        }
    }

    private Stack<Path> path_Stack; /* In the branch and Bound Depth first we use stack to manage the backtraking in the search tree,
	 									when we complete to process an intermediate node, we back to it's father.*/

    double upper_bound = Double.MAX_VALUE;

    private long amount_RunTime = 0;

    // Just for debugging purpose
    Path optimal_Path;

    int nb_all_path_added_to_open = 0; // just for debugging

    /**
     * Default Constructor
     */
    public GPU_GED_BB_DF() {
        path_Stack = new Stack<Path>();
    }

    public GPU_GED_BB_DF(long amount_RunTime) {

        path_Stack = new Stack<Path>();
        this.amount_RunTime = amount_RunTime;
        
    }

    /**
     * Compute the exact edit distance between two graphs.
     * The method implements A* algorithm
     * @param g1 from graph
     * @param g2 to graph
     * @return returns the exact edit distance between the to graphs
     */

    @SuppressWarnings({"rawtypes", "unchecked"})
    public double computeGED(Graph g1, Graph g2) throws IOException  {
        PriorityQueue<Path> pq = new PriorityQueue<Path>(1, new PathComparator());
        
        it0=0;
          // Allocate device output memory
        int g2_nb_op = g2.vertexSet().size(); 
        int g1_nb_op = g1.vertexSet().size();
        long elapsedTime_cpu =0;
         long elapsedTime_gpu =0;
        CUdeviceptr deviceOutput = new CUdeviceptr();
        cuMemAlloc(deviceOutput, Main.k_best*g2_nb_op* Sizeof.FLOAT);
        CUdeviceptr device_initial_cost = new CUdeviceptr();
        cuMemAlloc(device_initial_cost, Main.k_best* Sizeof.FLOAT);
        CUdeviceptr device_renmain_g2 = new CUdeviceptr();
        cuMemAlloc(device_renmain_g2, Main.k_best*g2_nb_op* Sizeof.INT);
        CUdeviceptr device_old_opf = new CUdeviceptr();
        cuMemAlloc(device_old_opf, Main.k_best*g1_nb_op* Sizeof.INT);
        CUdeviceptr device_old_opt = new CUdeviceptr();
        cuMemAlloc(device_old_opt, Main.k_best* g1_nb_op* Sizeof.INT);

                CUdeviceptr temp_remain = new CUdeviceptr();
        cuMemAlloc(temp_remain, Main.k_best*g2_nb_op* Sizeof.INT);
        CUdeviceptr temp_old_opf = new CUdeviceptr();
        cuMemAlloc(temp_old_opf, Main.k_best*g1_nb_op* Sizeof.INT);
        CUdeviceptr temp_old_opt = new CUdeviceptr();
        cuMemAlloc(temp_old_opt, Main.k_best* g1_nb_op* Sizeof.INT);

          CUdeviceptr device_best = new CUdeviceptr();
        cuMemAlloc(device_best,100* Sizeof.INT);
           CUdeviceptr device_nb = new CUdeviceptr();
        cuMemAlloc(device_nb, 100* Sizeof.INT);
        CUdeviceptr device_rank = new CUdeviceptr();
        cuMemAlloc(device_rank,  Main.k_best*g2_nb_op* Sizeof.INT);
        
        CUdeviceptr device_start_position = new CUdeviceptr();
        cuMemAlloc(device_start_position,  Main.k_best* Sizeof.INT);
        
           optimal_Path = null;
        if (g1.vertexSet().size() == 0 && g2.vertexSet().size() == 0) {
            return 0;
        }
       
        if (g1.vertexSet().size() == 0) {
            return (GED_Operations_Cost.getVertex_insertion_cost() * g2.vertexSet().size() + GED_Operations_Cost.getEdge_insertion_cost() * g2.edgeSet().size());
        }

     
        // if the graph g1 have vertices and edges; and g2 is empty, then
        // edit distance is = the cost of (deletion of all vertices of g1) + (deletion of all edges of g1)

        if (g2.vertexSet().size() == 0) {
            return (GED_Operations_Cost.getVertex_deletion_cost() * g1.vertexSet().size() + GED_Operations_Cost.getEdge_deletion_cost() * g1.edgeSet().size());
        }


        // local varibal, listV1: set of vertices of g1 ; listV2: set of vertices of g2
        ArrayList<Vertex> listV1 = new ArrayList<>(g1.vertexSet());
        ArrayList<Vertex> listV2 = new ArrayList<>(g2.vertexSet());

        // ---------------------- step 1 : Prepare initial paths (first level of the search tree)

        // Custom comparator to compare IndexValuePair objects based on their values
        Comparator<IndexValuePair> valueComparator = Comparator.comparingDouble(ivp -> ivp.value);

        // Create a PriorityQueue with the custom comparator
        PriorityQueue<IndexValuePair> prioritynext = new PriorityQueue<>(valueComparator);

           // substitution
        for (Vertex w : listV2) {
            Edit_Operation vertex_substitution_operation = new Edit_Operation(listV1.get(0), w);

            Path path = new Path(g1, g2);
            path.add(vertex_substitution_operation);
            // Insert substitution (u1 --> w) into OPEN

            if (path.getG_cost_PLUS_h_cost() <= (((upper_bound + 1000)))) {
                pq.add(path);
                nb_all_path_added_to_open++;
            }
        }

        // deletion
        Edit_Operation vertex_deletion_operation = new Edit_Operation(listV1.get(0), null);
        Path path0 = new Path(g1, g2);
        path0.add(vertex_deletion_operation);
        // Insert deletion (u1 --> null) into OPEN

       //  if (g1_nb_op>g2_nb_op )
        {
            pq.add(path0);
            nb_all_path_added_to_open++;
        }

        Path[] pp;
        Path pMin;
        //while(true)
        int k = Main.k_best;//
        int bar = 1000;
        if (g1.vertexSet().size() < 22) bar = 40;//path_Stack.size();
        int it = 0;
        int nb1 = 0;
        Stack p_S = new Stack<Path>();
       // Path[] pp1 = new Path[1000000];
        while (!pq.isEmpty()&&nb1<Main.k_best) {
            nb1++;
           //    System.out.println(pq.peek().getG_cost_PLUS_h_cost());
               p_S.push(pq.poll());
            //path_Stack.push();
        }
        nb1=0;
        while (!p_S.isEmpty()&&nb1<Main.k_best) {
            nb1++;
            path_Stack.push((Path)p_S.pop());
        }
       // System.out.println("\n new GED g1:"+g1_nb_op+ "g2:"+g2_nb_op+"\n" );

            int [] remain_g2_size =new int[Main.k_best+1]; 
            int [] remain_g2 =new int[g2_nb_op*Main.k_best+1]; 
            int[]  old_opf =new int[g1_nb_op*Main.k_best+1];
            int [] old_opt =new int[g1_nb_op*Main.k_best+1];
             float [] gpu_result=null;
           float [] initial_cost = new float[Main.k_best];
         boolean fin=false;
         long startTime = System.currentTimeMillis();
        while (fin==false) // a loop to process all the vertices in g1, wa treat all the sub-tree.
        {gpu_result=null;
            it++;
            prioritynext.clear();
            double max = 0;
            int size = path_Stack.size();
            int ssi = 0;
            List<Path> tempPaths = new ArrayList<Path>() ;
                
          
         int index_processed_vertices_g1 = -1; 
         int size_old=-1;
    
         if(it==1) {
              int ind_remaining=0; 
            int ind_old=0; 
          
           //if(it<3) 
           for (int i = 0; i < size && i<Main.k_best; i++) {
                ind_remaining= i*g2_nb_op;
              //  System.out.println("index_remainig:"+ind_remaining);
                ind_old=i*g1_nb_op;
                pMin = argMin();
                tempPaths.add(pMin);
                initial_cost[i]=(float)pMin.getG_cost();
                

               // if(it0<1)
                {
                if (pMin.isCompleteEditPath()==false) {
                    List<Vertex> remainsV2 = pMin.getRemaining_unprocessed_vertex_g2();
                    for (int jj=0; jj<remainsV2.size();jj++){
                     remain_g2[ind_remaining+jj]=remainsV2.get(jj).getVertex_id();                    
                    } 
                     for(int ji=remainsV2.size();ji<g2_nb_op;ji++){remain_g2[ind_remaining+ji]=-1;}
                   
                 //   System.out.println("==========================================");
                    List<Edit_Operation> old_edit_Operations = pMin.get_Operations_List();
                    int ind=0;
                   if(old_edit_Operations.size()>0) 
                   for (Edit_Operation old_Edit_Operation : old_edit_Operations) {
                                /// System.out.println(" old edit op : "+old_Edit_Operation.toString());
                                // Check whether the source edge exists
                                if (old_Edit_Operation.getFromVertex() == null ) {
                                    old_opf[ind_old+ ind]=-1;
                                } else {
                                   old_opf[ind_old+ind]= old_Edit_Operation.getFromVertex().getVertex_id();
                                }

                                // Check whether the target edge exists
                                if (old_Edit_Operation.getToVertex() == null ) {
                                    old_opt[ind_old+ind]=-1;
                                } else {
                                    old_opt[ind_old+ind] = old_Edit_Operation.getToVertex().getVertex_id();
                                }

                             //   System.out.println("ind:"+ind + " "+ old_opf[ind]+ " "+ old_opt[ind]);
                                ind++;

                            }
                            for(int ji=ind;ji<g1_nb_op;ji++){old_opt[ind_old+ji]=-1; old_opf[ind_old+ji]=-1; }
                            
                    
                    } 
              
                }
                 }
            
              
               
           }   
          
            index_processed_vertices_g1=it; size_old=it;
          //  System.out.println("it:"+ it +"ind:"+size_old + " g1 size "+ g1.vertexSet().size()+ "g2 size"+ g2.vertexSet().size() + " process g1: "+ index_processed_vertices_g1);
           if(index_processed_vertices_g1>=listV1.size()){
                    fin =true;}
              if(fin==false)  /*if(remain_g2_size[0] >0&&index_processed_vertices_g1<listV1.size()||it0>2&&index_processed_vertices_g1<listV1.size()&&remain_g2_size[0] >0)*/
                {
   
 
        gpu_result= GpuEval (initial_cost,g1.vertexSet().size(), g2.vertexSet().size(), GED_Operations_Cost.getVertex_substitution_cost(), 
        GED_Operations_Cost.getVertex_deletion_cost(),GED_Operations_Cost.getEdge_substitution_cost(), 
        GED_Operations_Cost.getEdge_deletion_cost(), index_processed_vertices_g1,0 ,size_old, 
        remain_g2,  old_opf, old_opt, Main.g1Gpu.device_adj_mat, 
        Main.g2Gpu.device_adj_mat, Main.g1Gpu.device_weight_vertex, Main.g2Gpu.device_weight_vertex,
        deviceOutput, device_renmain_g2, device_old_opf , device_old_opt, device_initial_cost, 
        device_rank,device_best, device_nb, temp_remain, temp_old_opf, temp_old_opt,device_start_position);
       // path_Stack.addAll(tempPaths);
}
 
 long startTime1 = System.currentTimeMillis();
 if(index_processed_vertices_g1>=listV1.size()){
    int max_v= listV1.size();
    if(max_v<listV2.size())max_v=listV2.size(); 
    int best_position= Gpu_last (initial_cost,g1.vertexSet().size(), g2.vertexSet().size(), GED_Operations_Cost.getVertex_substitution_cost(), 
    GED_Operations_Cost.getVertex_deletion_cost(),GED_Operations_Cost.getEdge_substitution_cost(), 
    GED_Operations_Cost.getEdge_deletion_cost(), index_processed_vertices_g1,0 ,size_old, 
    remain_g2,  old_opf, old_opt, Main.g1Gpu.device_adj_mat, 
    Main.g2Gpu.device_adj_mat, Main.g1Gpu.device_weight_vertex, Main.g2Gpu.device_weight_vertex,
    deviceOutput, device_renmain_g2, device_old_opf , device_old_opt, device_initial_cost, 
    device_rank,device_best, device_nb, temp_remain, temp_old_opf, temp_old_opt,device_start_position,g1,g2);

    //unprocessed_GPU_vertex(best_position,g1,g2, g1_nb_op,g2_nb_op,device_old_opf,device_old_opt, max_v );
    path_Stack.clear();
    fin=true;
            }
long endTime1 = System.currentTimeMillis();

elapsedTime_gpu = elapsedTime_gpu +(endTime1 - startTime1);

           
          //    System.out.println("Elapsed time cpu: " + elapsedTime_cpu + " milliseconds");
            tempPaths.clear();
            //    System.out.println("pq-size:"+pq.size()+"path_Stack size:"+path_Stack.size());
            int nb = 0; //k=k+20+(int)0;new Path[0]
            //if(it>5)k=50;
            double v_last = 0;
            while (!pq.isEmpty() && nb < k) {
                nb++;
                v_last = pq.peek().getG_cost_PLUS_h_cost();
                path_Stack.push(pq.poll());
            }
            //System.out.println("\n");
            if (Main.dinamique == 1 && path_Stack.size() > 0)
                while (!pq.isEmpty() && v_last == pq.peek().getG_cost_PLUS_h_cost() && nb < bar) {
                    nb++;
                    
                    path_Stack.add(0, pq.poll());
                }
            
            pq.clear();
        }
        if (optimal_Path != null) {
            System.out.print(optimal_Path.getG_cost());
        } else {
        
         //   System.out.print(10000);
        }
        long endTime = System.currentTimeMillis();

        elapsedTime_cpu =  endTime - startTime;
        System.out.print(", T: "+ elapsedTime_cpu + " milliseconds");
      //  System.out.println("Elapsed gpu time : " + elapsedTime_gpu + " milliseconds");  

           cuMemFree(device_old_opf);
           cuMemFree( device_initial_cost);
        cuMemFree(device_old_opt);
        cuMemFree(device_renmain_g2);
        cuMemFree(deviceOutput);
        cuMemFree(device_best);
        cuMemFree(device_rank);
        cuMemFree(device_start_position);
        cuMemFree(device_nb);
        cuMemFree(temp_old_opf);
         cuMemFree(temp_old_opt);
          cuMemFree(temp_remain);

         // System.exit(1);
        return 0;//optimal_Path.getG_cost();
    }


    /**
     * Get pMin and delete all argmin_p{g(p)+h(p)} paths
     *
     * @return returns the path p with the minimum g(p)+h(p)
     */
    private Path argMin() {
        //Path p = OPEN.poll();
        Path p = path_Stack.pop();

        //while(p.getG_cost_PLUS_h_cost() == OPEN.peek().getG_cost_PLUS_h_cost()) // Double comparison !!! To be fixed!
        //	OPEN.poll();

        return p;
    }
List list_val =null;
List list_all_val =null;
int it0=0;
  float[]  GpuEval (float [] initial_cost,int g1_nb_operation, int g2_nb_operation, float co1, float co2, float ce1, float ce2, int index_g1,int remain_g2_size ,int old_size, int [] remain_g2, int []  old_opf, int [] old_opt, CUdeviceptr adj_mat_g1, CUdeviceptr adj_mat_g2, CUdeviceptr weight_g1, CUdeviceptr weight_g2,CUdeviceptr deviceOutput,CUdeviceptr device_renmain_g2,CUdeviceptr device_old_opf ,CUdeviceptr device_old_opt, CUdeviceptr device_initail_cost, CUdeviceptr device_rank, CUdeviceptr device_best, CUdeviceptr device_nb , CUdeviceptr temp_remain, CUdeviceptr temp_old_opf, CUdeviceptr temp_old_opt, CUdeviceptr device_start_position)throws IOException 
  {it0++;
 //System.out.println("+++++++++++++++++++++++++start+++++++++++++++++++++++++++++++++++++++++");
        // Enable exceptions and omit all subsequent error checks
        JCudaDriver.setExceptionsEnabled(true);
        // Create the PTX file by calling the NVCC
        String ptxFileName = JGraphTtoGPU.preparePtxFile("gpu_evaluation.cu");
        // Load the ptx file.
        CUmodule module = new CUmodule();
        cuModuleLoad(module, ptxFileName);
      //  double bl = Math.pow(g2_nb_operation, index_g1);

        // Obtain a function pointer to the "eval" function.
        CUfunction function = new CUfunction();
        cuModuleGetFunction(function, module, "eval");
        //
       if(it0<2) {
     //   System.out.println("sending data");
        cuMemcpyHtoD(device_initail_cost, Pointer.to(initial_cost), Main.k_best* Sizeof.FLOAT);
        cuMemcpyHtoD(device_renmain_g2, Pointer.to(remain_g2), Main.k_best* g2_nb_operation* Sizeof.INT);
        cuMemcpyHtoD(device_old_opf, Pointer.to(old_opf), Main.k_best* g1_nb_operation* Sizeof.INT);
        cuMemcpyHtoD(device_old_opt, Pointer.to(old_opt), Main.k_best* g1_nb_operation* Sizeof.INT);}
        int best_1=0, best_2=0,best_3=0;

 

    Pointer kernelParameters = Pointer.to(Pointer.to(device_initail_cost), Pointer.to(new int[]{g1_nb_operation}),Pointer.to(new int[]{g2_nb_operation}),Pointer.to(new float[]{co1}),Pointer.to(new float[]{co2}),Pointer.to(new float[]{ce1}),Pointer.to(new float[]{ce2}),Pointer.to(new int[]{index_g1}),Pointer.to(new int[]{old_size}),Pointer.to(device_renmain_g2),Pointer.to(device_old_opf),Pointer.to(device_old_opt),Pointer.to(adj_mat_g1),Pointer.to(adj_mat_g2),Pointer.to(weight_g1),Pointer.to(weight_g2),Pointer.to(deviceOutput),Pointer.to(device_best),Pointer.to(device_nb));


        // Call the kernel function.
        int blockSizeX = g2_nb_operation;
        int gridSizeX = Main.k_best;
      //  if(gridSizeX>bl)gridSizeX=(int)bl; 
        cuLaunchKernel(function,
                gridSizeX,  1, 1,      // Grid dimension
                blockSizeX, 1, 1,      // Block dimension
                g2_nb_operation*Sizeof.INT,null ,               // Shared memory size and stream
                kernelParameters, null // Kernel- and extra parameters
        );
        cuCtxSynchronize();
       
        // Allocate host output memory and copy the device output
        // to the host.
         float hostOutput[] = null;
        // sorting and getting the best k elements
        sort(deviceOutput,g2_nb_operation, device_best,device_nb, device_rank, index_g1);
        update_data  (index_g1 ,g1_nb_operation,g2_nb_operation, device_rank, device_nb, deviceOutput, device_renmain_g2, device_old_opf, device_old_opt, device_initail_cost,temp_remain, temp_old_opf, temp_old_opt, index_g1,device_best,device_start_position);
        return hostOutput;
    }

     void sort  (CUdeviceptr deviceOutput, int g2_nb_operation, CUdeviceptr device_best ,CUdeviceptr device_nb ,CUdeviceptr device_rank, int index_g1 )throws IOException {

        // Enable exceptions and omit all subsequent error checks
        JCudaDriver.setExceptionsEnabled(true);

        // Create the PTX file by calling the NVCC
        String ptxFileName = JGraphTtoGPU.preparePtxFile("gpu_evaluation.cu");

        // Load the ptx file.
        CUmodule module = new CUmodule();
        cuModuleLoad(module, ptxFileName);

        // Obtain a function pointer to the "eval" function.
        CUfunction function = new CUfunction();
        cuModuleGetFunction(function, module, "sort");

      
        Pointer kernelParameters = Pointer.to(Pointer.to(deviceOutput),Pointer.to(device_best),Pointer.to(device_nb),Pointer.to(device_rank));
        // Call the kernel function.
                int blockSizeX = g2_nb_operation;
                int gridSizeX = Main.k_best;
       
        cuLaunchKernel(function,
                gridSizeX,  1, 1,      // Grid dimension
                blockSizeX, 1, 1,      // Block dimension
                0, null,               // Shared memory size and stream
                kernelParameters, null // Kernel- and extra parameters
        );
        cuCtxSynchronize();

     //   System.out.println("Test sort "+"PASSED");

     
    }

         void update_data  (int index, int g1_nb_operation, int g2_nb_operation,CUdeviceptr device_rank,CUdeviceptr device_nb,  CUdeviceptr deviceOutput, CUdeviceptr remain_g2,  CUdeviceptr device_old_opf,  CUdeviceptr device_old_opt,  CUdeviceptr device_initial_result  , CUdeviceptr temp_remain, CUdeviceptr temp_old_opf, CUdeviceptr temp_old_opt, int index_g1,CUdeviceptr dev_best,CUdeviceptr device_start_position)throws IOException {

        // Enable exceptions and omit all subsequent error checks
        JCudaDriver.setExceptionsEnabled(true);

        // Create the PTX file by calling the NVCC
        String ptxFileName = JGraphTtoGPU.preparePtxFile("gpu_evaluation.cu");

        // Load the ptx file.
        CUmodule module = new CUmodule();
        cuModuleLoad(module, ptxFileName);

        // Obtain a function pointer to the "eval" function.
        CUfunction function = new CUfunction();
        cuModuleGetFunction(function, module, "update_data_1");
//System.out.println("in ");
    CUfunction function1 = new CUfunction();
        cuModuleGetFunction(function1, module, "copyVectors");

           CUfunction function2 = new CUfunction();
        cuModuleGetFunction(function2, module, "update_data_2");

        Pointer kernelParameters = Pointer.to(Pointer.to(new int[] {index}), Pointer.to(new int[] {g1_nb_operation}),Pointer.to(new int[] {g2_nb_operation}),Pointer.to(new int[] {Main.k_best}),Pointer.to(device_rank), Pointer.to(device_nb) , Pointer.to(deviceOutput), Pointer.to(remain_g2), Pointer.to(device_old_opf), Pointer.to(device_old_opt), Pointer.to(temp_remain),Pointer.to(temp_old_opf),Pointer.to(temp_old_opt),Pointer.to(dev_best), Pointer.to(device_start_position) );
        // Call the kernel function.
                int blockSizeX = g2_nb_operation;
                int gridSizeX = Main.k_best;
          

        cuLaunchKernel(function,
                gridSizeX,  1, 1,      // Grid dimension
                blockSizeX, 1, 1,      // Block dimension
                0, null,               // Shared memory size and stream
                kernelParameters, null // Kernel- and extra parameters
        );
        cuCtxSynchronize();
        


Pointer kernelParameters1 = Pointer.to( Pointer.to(new int[] {g1_nb_operation}),Pointer.to(new int[] {g2_nb_operation}), Pointer.to(remain_g2), Pointer.to(device_old_opf), Pointer.to(device_old_opt), Pointer.to(temp_remain),Pointer.to(temp_old_opf),Pointer.to(temp_old_opt), Pointer.to(device_start_position));
         // update 2 kernel execution
        cuLaunchKernel(function1,
                gridSizeX,  1, 1,      // Grid dimension
                blockSizeX, 1, 1,      // Block dimension
                0, null,               // Shared memory size and stream
                kernelParameters1, null // Kernel- and extra parameters
        );
        cuCtxSynchronize();


Pointer kernelParameters2 = Pointer.to(Pointer.to(new int[] {index}), Pointer.to(new int[] {g1_nb_operation}),Pointer.to(new int[] {g2_nb_operation}),Pointer.to(new int[] {Main.k_best}),Pointer.to(device_rank), Pointer.to(device_nb) , Pointer.to(deviceOutput), Pointer.to(remain_g2), Pointer.to(device_old_opf), Pointer.to(device_old_opt), Pointer.to(device_initial_result), Pointer.to(temp_remain),Pointer.to(temp_old_opf),Pointer.to(temp_old_opt));
         // update 2 kernel execution
        cuLaunchKernel(function2,
                gridSizeX,  1, 1,      // Grid dimension
                blockSizeX, 1, 1,      // Block dimension
                0, null,               // Shared memory size and stream
                kernelParameters2, null // Kernel- and extra parameters
        );
        cuCtxSynchronize();
      //  System.out.println("Test update "+"PASSED");

     
    }

    int Gpu_last (float [] initial_cost,int g1_nb_operation, int g2_nb_operation, float co1, float co2, float ce1, float ce2, int index_g1,int remain_g2_size ,int old_size, int [] remain_g2, int []  old_opf, int [] old_opt, CUdeviceptr adj_mat_g1, CUdeviceptr adj_mat_g2, CUdeviceptr weight_g1, CUdeviceptr weight_g2,CUdeviceptr deviceOutput,CUdeviceptr device_renmain_g2,CUdeviceptr device_old_opf ,CUdeviceptr device_old_opt, CUdeviceptr device_initail_cost, CUdeviceptr device_rank, CUdeviceptr device_best, CUdeviceptr device_nb , CUdeviceptr temp_remain, CUdeviceptr temp_old_opf, CUdeviceptr temp_old_opt, CUdeviceptr device_start_position, Graph g1, Graph g2)throws IOException 
  {
 //System.out.println("+++++++++++++++++++++++++start+++++++++++++++++++++++++++++++++++++++++");
        // Enable exceptions and omit all subsequent error checks
        JCudaDriver.setExceptionsEnabled(true);
        // Create the PTX file by calling the NVCC
        String ptxFileName = JGraphTtoGPU.preparePtxFile("gpu_evaluation.cu");
        // Load the ptx file.
        CUmodule module = new CUmodule();
        cuModuleLoad(module, ptxFileName);
      //  double bl = Math.pow(g2_nb_operation, index_g1);

        // Obtain a function pointer to the "eval" function.
        CUfunction function = new CUfunction();
        cuModuleGetFunction(function, module, "gpu_unprocessed");
      

int kbest0=Main.k_best;
 

    Pointer kernelParameters = Pointer.to(Pointer.to(device_initail_cost), Pointer.to(new int[]{g1_nb_operation}),Pointer.to(new int[]{g2_nb_operation}),Pointer.to(new float[]{co1}),Pointer.to(new float[]{co2}),Pointer.to(new float[]{ce1}),Pointer.to(new float[]{ce2}),Pointer.to(new int[]{index_g1}),Pointer.to(new int[]{old_size}),Pointer.to(device_renmain_g2),Pointer.to(device_old_opf),Pointer.to(device_old_opt),Pointer.to(adj_mat_g1),Pointer.to(adj_mat_g2),Pointer.to(weight_g1),Pointer.to(weight_g2),Pointer.to(deviceOutput),Pointer.to(device_best),Pointer.to(device_nb),Pointer.to(new int[]{kbest0}) );

        // Call the kernel function.
        int blockSizeX = Main.k_best;// 1024;
        if(Main.k_best>1024)blockSizeX=1024;
        int gridSizeX = Main.k_best/blockSizeX +1;
      //  if(gridSizeX>bl)gridSizeX=(int)bl; 
        cuLaunchKernel(function,
                gridSizeX,  1, 1,      // Grid dimension
                blockSizeX, 1, 1,      // Block dimension
                0,null ,               // Shared memory size and stream
                kernelParameters, null // Kernel- and extra parameters
        );
        cuCtxSynchronize();
       
        // Allocate host output memory and copy the device output
        // to the host.
         int hostOutput[] = new int[2];
        cuMemcpyDtoH(Pointer.to(hostOutput), device_best,
                2* Sizeof.INT);

     int max_v=g1_nb_operation;
     if(max_v<g2_nb_operation)max_v=g2_nb_operation;
    unprocessed_GPU_vertex(hostOutput[1],g1,g2, g1_nb_operation,g2_nb_operation,device_old_opf,device_old_opt, max_v );

 //System.out.print("GPU: "+(float)hostOutput[0]/1000);//+"position:"+hostOutput[1]);

        return hostOutput[1];
    }


    void unprocessed_GPU_vertex(int best_ind , Graph g1, Graph g2, int g1_nb_operation, int g2_nb_operation, CUdeviceptr device_old_opf,  CUdeviceptr device_old_opt,int size) throws IOException {
 
float best =10000000;
     int old_opt[] = new int[g1_nb_operation*Main.k_best];
        cuMemcpyDtoH(Pointer.to(old_opt), device_old_opt,
                g1_nb_operation*Main.k_best* Sizeof.INT);


    

    ArrayList<Vertex> listV1 = new ArrayList<>(g1.vertexSet());
    ArrayList<Vertex> listV2 = new ArrayList<>(g2.vertexSet());
 

     Path best_p =new Path(g1,g2); 
     int k=1000; 
     if(Main.k_best<1000)k=10;

     int i=best_ind;
     { 
             int opf=0;
     ArrayList<Vertex> V2_remain = new ArrayList<>(g2.vertexSet());
            Path p= new Path(g1,g2);
          
            int ind_remain=0;
            int p_opf=0, p_opt=0;
            for (int j=0;j<size;j++){
        //  int opf=-1; 
        opf++;
          int opt=-1;
          if(j<g1_nb_operation){
           // opf= old_opf[i*g1_nb_operation+j]; 
            opt= old_opt[i*g1_nb_operation+j];
            p_opf=opf;p_opt=opt;

            if(opf==-1&&opt==-1)
            System.out.println("\n error node:"+i+" position "+j+ " size" +size +" opf:"+opf+ "opt:"+opt);
     //   System.out.print("in");
        }

            else{opt=V2_remain.get(ind_remain).getVertex_id();  opf=-1; ind_remain++;}
            if(opt>g2_nb_operation)opt=-1;
           
          if(opf>0 && opt>0){

          Edit_Operation vertex_substitution_operation = new Edit_Operation(listV1.get(opf-1), listV2.get(opt-1));
          p.add(vertex_substitution_operation);
          boolean re=V2_remain.remove(listV2.get(opt-1));
          if(!re)System.out.println("error vertex not found:"+opt+" i:"+i);
          }
          else if(opf>0 && opt<0) {
             Edit_Operation vertex_deletion_operation = new Edit_Operation(listV1.get(opf-1), null);
          p.add(vertex_deletion_operation);
           }
            else if(opf<0 && opt>0){   
                Vertex vv = listV2.get(opt-1);
                Edit_Operation vertex_insertion_operation = new Edit_Operation(null, vv);
          p.add(vertex_insertion_operation);  }
            }
          
     
        if(p.getIndex_processed_vertices_g1()>0) while(!p.isCompleteEditPath()){
            
             Edit_Operation vertex_insertion_operation = new Edit_Operation(null, p.getRemaining_unprocessed_vertex_g2().get(0));
             p.add(vertex_insertion_operation);
    }
       if(p.isCompleteEditPath()==true){ //i=1000000000;
        if( p.getG_cost()<best){ best= (float) p.getG_cost();best_p=p;}}//}
        }

        
        
  
        optimal_Path=best_p;



        


    }

}


