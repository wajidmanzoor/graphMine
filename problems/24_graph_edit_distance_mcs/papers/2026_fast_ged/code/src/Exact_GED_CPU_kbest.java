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
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

//import sun.security.provider.certpath.Vertex;

import java.io.IOException;
import java.util.*;
// Exact Graph Edit Distance (GED) with Branch and Bound (BB) Depth First stratigy (DF)



class WorkerThread implements Runnable {
   public Stack p =new Stack<Path>();
   Path pMin=null;
    Vertex v; 
    int index;

    public WorkerThread(Path task, Vertex v1, int i) {
        this.pMin = task;
        this.v=v1;
        this.index=i;
    }

    @Override
    public void run() {
      //  System.out.println(Thread.currentThread().getName() + " Start. Task = " + p.size());
        List<Vertex> remainsV2 = pMin.getRemaining_unprocessed_vertex_g2();
        int index_v2 = 0;
        for (Vertex w1 : remainsV2) {
                          
             Path newP1 = new Path(pMin);
             Edit_Operation newOp1 = new Edit_Operation(this.v, w1);
             newP1.add(newOp1);
             this.p.add(newP1);
             
            }                           
        Path newP2 = new Path(pMin);
        Edit_Operation newOp2 = new Edit_Operation(this.v, null);
                       //  System.out.println("---node  : g+h = "+newP2.getG_cost()+" original node cost"+pMin.getG_cost());
         newP2.add(newOp2);
         this.p.add(newP2);

                        


       // System.out.println(Thread.currentThread().getName() + " index"+this.index+ " End." + p.size()); 
        Main.stackTable[this.index].clear();
        Main.stackTable[this.index].addAll(this.p);
       // System.out.println(Thread.currentThread().getName() + " End.2 " + Main.stackTable[this.index].size()); 
    }


 
}


public class Exact_GED_CPU_kbest {
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
    public Exact_GED_CPU_kbest() {
        path_Stack = new Stack<Path>();
    }

    public Exact_GED_CPU_kbest(long amount_RunTime) {

        path_Stack = new Stack<Path>();
        this.amount_RunTime = amount_RunTime;
    }

    /**
     * Compute the exact edit distance between two graphs.
     * The method implements A* algorithm
     *
     * @param g1 from graph
     * @param g2 to graph
     * @return returns the exact edit distance between the to graphs
     */
    @SuppressWarnings({"rawtypes", "unchecked"})
    public double computeGED(Graph g1, Graph g2) throws IOException  {
        PriorityQueue<Path> pq = new PriorityQueue<Path>(1, new PathComparator());
        
        it0=0;
        int g2_nb_op = g2.vertexSet().size(); 
        int g1_nb_op = g1.vertexSet().size();
        long elapsedTime_cpu =0;
         long elapsedTime_gpu =0;
        //upper_bound=100000000;
        //	PriorityQueue<Path> pq_best = new PriorityQueue<Path>(1, new PathComparator());
        // if both graph are empty, then the edit distance is "0"
        optimal_Path = null;
        if (g1.vertexSet().size() == 0 && g2.vertexSet().size() == 0) {
            return 0;
        }
        // if the graph g1 is empty (g2 is not), then
        // edit distance is = the cost of (insertion of all vertices of g2) + (insertion of all edges of g2)

        if (g1.vertexSet().size() == 0) {
            return (GED_Operations_Cost.getVertex_insertion_cost() * g2.vertexSet().size() + GED_Operations_Cost.getEdge_insertion_cost() * g2.edgeSet().size());
        }

     /*   if (g1.vertexSet().size() > g2.vertexSet().size()) {
            Graph g3 = g1;
            g1 = g2;
            g2 = g3;
        }
       */ 

        // if the graph g1 have vertices and edges; and g2 is empty, then
        // edit distance is = the cost of (deletion of all vertices of g1) + (deletion of all edges of g1)

        if (g2.vertexSet().size() == 0) {
            return (GED_Operations_Cost.getVertex_deletion_cost() * g1.vertexSet().size() + GED_Operations_Cost.getEdge_deletion_cost() * g1.edgeSet().size());
        }


        // local varibal, listV1: set of vertices of g1 ; listV2: set of vertices of g2
        ArrayList<Vertex> listV1 = new ArrayList<>(g1.vertexSet());
        ArrayList<Vertex> listV2 = new ArrayList<>(g2.vertexSet());

        //  upper_bound =1000;// h_function.compute(g1,g2,"max");
        //upper_bound=111;//60;//4300;
        // ---------------------- step 1 : Prepare initial paths (first level of the search tree)

        // Custom comparator to compare IndexValuePair objects based on their values
        Comparator<IndexValuePair> valueComparator = Comparator.comparingDouble(ivp -> ivp.value);

        // Create a PriorityQueue with the custom comparator
        PriorityQueue<IndexValuePair> prioritynext = new PriorityQueue<>(valueComparator);

        // Add elements to the PriorityQueue
        prioritynext.add(new IndexValuePair(0, 1, 5));
        prioritynext.add(new IndexValuePair(1, 1, 3));
        prioritynext.add(new IndexValuePair(2, 2, 7));

        // Poll elements from the PriorityQueue based on their values
        while (!prioritynext.isEmpty()) {
            IndexValuePair ivp = prioritynext.poll();
            //System.out.println("Index: " + ivp.index1 + ", Value: " + ivp.value);
        }
        // substitution
        for (Vertex w : listV2) {
            Edit_Operation vertex_substitution_operation = new Edit_Operation(listV1.get(0), w);

            Path path = new Path(g1, g2);
            path.add(vertex_substitution_operation);
            // Insert substitution (u1 --> w) into OPEN

            if (path.getG_cost_PLUS_h_cost() <= (((upper_bound + 1000)))) {
                //	path_Stack.push(path);
                pq.add(path);
                //OPEN.add(path);
                nb_all_path_added_to_open++;
            }
        }

        // deletion
        Edit_Operation vertex_deletion_operation = new Edit_Operation(listV1.get(0), null);
        Path path0 = new Path(g1, g2);
        path0.add(vertex_deletion_operation);
        // Insert deletion (u1 --> null) into OPEN

        if (path0.getG_cost_PLUS_h_cost() <= (((upper_bound + 1000)))) {
            //  path_Stack.push(path0);
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
        //Path[] pp1 = new Path[1000000];
        while (!pq.isEmpty()/*&&nb1<k*/) {
            nb1++;
            //   System.out.println(pq.peek().getG_cost_PLUS_h_cost());
            path_Stack.push(pq.poll());
        }
       // System.out.println("\n new GED g1:"+g1_nb_op+ "g2:"+g2_nb_op+"\n" );
            int availableCores = 1;//Runtime.getRuntime().availableProcessors();
         
         boolean fin=false;
        while (!path_Stack.empty()) // a loop to process all the vertices in g1, wa treat all the sub-tree.
        {
            it++;
            prioritynext.clear();
            double max = 0;
            // Return pMin and delete all argmin_p{g(p)+h(p)} paths
            // get the node pMin from OPEN, this depend on the strategy implemented.
            int size = path_Stack.size();
            int ssi = 0;
            List<Path> tempPaths = new ArrayList<Path>() ;
                
            int index_processed_vertices_g1 = -1; 
         
         

            //for (int i = 0; i < 10; i++) {
             //  
            //}
    
       
    
long startTime = System.currentTimeMillis();
ExecutorService executor = Executors.newFixedThreadPool(availableCores);            for (int i = 0; i < size; i++) { 
               
             //   executor.execute(worker);
                boolean doo =true;
              {
                pMin = argMin();
                List<Vertex> remainsV2 = pMin.getRemaining_unprocessed_vertex_g2();
                index_processed_vertices_g1 = pMin.getIndex_processed_vertices_g1();

                if (pMin.isCompleteEditPath()) {
                    //System.out.println("complete path");
                    if (optimal_Path == null) {
                        optimal_Path = new Path(pMin); // Make a copy for debugging purpose

                        upper_bound = pMin.getG_cost();
                        //  System.out.println("G_cost = "+optimal_Path.getG_cost()+" | g+h = "+optimal_Path.getG_cost_PLUS_h_cost()+" | upper_bound = "+upper_bound);
                    } else {
                        if (pMin.getG_cost() <= ((upper_bound ))/*optimal_Path.getG_cost()*/) {
                            optimal_Path = new Path(pMin); // Make a copy for debugging purpose
                            upper_bound = pMin.getG_cost();
                            // System.out.println(optimal_Path.toString());
                            // System.out.println("G_cost = "+optimal_Path.getG_cost()+" | g+h = "+optimal_Path.getG_cost_PLUS_h_cost()+" | upper_bound = "+upper_bound);
                        }
                    }
                } else { 
                    
                    

                              

                         if (index_processed_vertices_g1 < listV1.size()) {
                          
                    Runnable worker = new WorkerThread(pMin,listV1.get(index_processed_vertices_g1),i);
                    executor.execute(worker);
                 
                  
                  //pq.addAll(stackTable[i]);
                   // float [] result_cpu =new float [remainsV2.size()];
                        // substitution
                        double dp_min = pMin.getG_cost_PLUS_h_cost();
                        int index_v2 = 0;
                       /*  for (Vertex w1 : remainsV2) {
                             doo=true;
                              if(list_val==null||list_val.size()==0){doo=true;}
                              //   else{ if(list_val.contains((i*g2_nb_op+index_v2))==false)doo=false;}

                              //if(doo==true)
                              {
                             Path newP1 = new Path(pMin);

                             Edit_Operation newOp1 = new Edit_Operation(listV1.get(index_processed_vertices_g1), w1);

                             //	double cost=newP1.add_cost(newOp1);

                             newP1.add(newOp1);
                             // System.out.println("adj mat"+Main.g1Gpu.edge_weight_matrix[(index_processed_vertices_g1)*g1.vertexSet().size()+old_opf[0]-1]);
                             // Add substitution to pMin, then add the new path to OPEN

                        //       result_cpu[index_v2]=(float)newP1.getG_cost();
                           //  if (newP1.getG_cost_PLUS_h_cost() <= (((upper_bound + 1000)))) 
                             {
                                //     path_Stack.push(newP1);
                                //if(pq.size()>k)
                                {
                                    // System.out.println(index_v2+"---node  : g+h = "+newP1.getG_cost()+" original node cost"+pMin.getG_cost());
                                    //  Iterator pq_iterator = pq.iterator();
                                    //if(pq_iterator.)
                                    if (pq.size() > k && i > 0) {// if(pp1[ssi-1].getG_cost_PLUS_h_cost()>newP1.getG_cost_PLUS_h_cost())
                                        {
                                            pq.add(newP1);
                                        }
                                    } else {
                                        pq.add(newP1);
                                    }
                                    //System.out.println("|"+pq.size());


                                }
                                nb_all_path_added_to_open++;
                            }
                            //vertex_Cost = GED_Operations_Cost.getVertex_substitution_cost(newOp1.getFromVertex(),newOp1.getToVertex());
                            //	prioritynext.add(new IndexValuePair(i,index_v2, dp_min));
                            index_v2++;
                        }}
                 ///    if(list_val!=null)   list_val.clear();
                        
                  //   if(it>2 && gpu_result!=null) 
                     //  for (int i2=0;i2<remainsV2.size();i2++) if( Math.abs(result_cpu[i2] - (gpu_result[i*g2_nb_op+i2])) > 1e-1) System.out.println("node "+i+"error i:"+i2+"cpu eval:"+result_cpu[i2]+"gpu eval:"+(gpu_result[i*g2_nb_op+i2]+"pmin_cost"+pMin.getG_cost()));
                        // deletion
                        Path newP2 = new Path(pMin);
                        Edit_Operation newOp2 = new Edit_Operation(listV1.get(index_processed_vertices_g1), null);
                       //  System.out.println("---node  : g+h = "+newP2.getG_cost()+" original node cost"+pMin.getG_cost());
                        newP2.add(newOp2);
                        // Add deletion to pMin, then add the new path to OPEN
                    //   if(it>2)  if(gpu_result!=null) if( Math.abs(newP2.getG_cost() - (gpu_result[i*g2_nb_op+g2_nb_op-1])) > 1e-2)  System.out.println("node deletion error "+i+" cpu eval:"+newP2.getG_cost()+"gpu eval:"+gpu_result[i*g2_nb_op+g2_nb_op-1]+"pmin_cost"+pMin.getG_cost()); 
                        /// System.out.println("---------- Midele node : g+h = "+newP2.getG_cost_PLUS_h_cost());

                        if (newP2.getG_cost_PLUS_h_cost() <= (((upper_bound + 1000)))) {
                            //  path_Stack.push(newP2);
                            if (pq.size() > k && i > 0) { //if(pp1[ssi-1].getG_cost_PLUS_h_cost()>newP2.getG_cost_PLUS_h_cost())
                                {
                                    pq.add(newP2);

                                }
                            } else {
                                pq.add(newP2);
                            }
                            nb_all_path_added_to_open++;
                        }
                        */

                    } else {
                        Path newP3 = new Path(pMin);
                        for (Vertex w2 : remainsV2) {
                            Edit_Operation newOp3 = new Edit_Operation(null, w2);
                            newP3.add(newOp3);
                        }
                        // Add insertion to pMin, then add the new path to OPEN

                       //  System.out.println("---------- Midele node : g+h = "+newP3.getG_cost_PLUS_h_cost());

                        if (newP3.getG_cost_PLUS_h_cost() <= (((upper_bound + 1000)))) {
                            //    path_Stack.push(newP3);
                            pq.add(newP3);
                            nb_all_path_added_to_open++;
                        }
                    }

                }


              /*   if (i == 0) {
                    pq.toArray(pp1);
                    ssi = pq.size();
                    //System.out.println(pp1[ssi-1]);
                }*/

                //	if(pq.size()>10000)	System.out.println(pq.size()+"|"+pp1[00].getG_cost_PLUS_h_cost()+"|"+pp1[100].getG_cost_PLUS_h_cost());
                }
            }
            executor.shutdown();
            while (!executor.isTerminated()) {
            }

          for (int i=0;i<size;i++) { pq.addAll(Main.stackTable[i]) ; //System.out.println("stack"+Main.stackTable[i].size());
          Main.stackTable[i].clear();}
            long endTime = System.currentTimeMillis();

               elapsedTime_cpu = elapsedTime_cpu +( endTime - startTime);

           
            tempPaths.clear();
            //    System.out.println("pq-size:"+pq.size()+"path_Stack size:"+path_Stack.size());
            int nb = 0; //k=k+20+(int)0;new Path[0]
            //if(it>5)k=50;
            double v_last = 0;
            while (!pq.isEmpty() && nb < k) {
                nb++;
                v_last = pq.peek().getG_cost_PLUS_h_cost();
           // if (index_processed_vertices_g1 < listV1.size())     if(it>2 && gpu_result!=null)  
         //  	System.out.println ("k:"+nb+"|"+pq.peek().getG_cost_PLUS_h_cost());
                path_Stack.push(pq.poll());
           // if (index_processed_vertices_g1 < listV1.size())   if(it>2 && gpu_result!=null) {
            //    if(list_val.contains((int)(v_last*100))==false){ System.out.print(" error value not found in the sort \\");   if(list_all_val.contains((int)(v_last*100))==false) System.out.print(" error value not found in the second all result "); }  }
            }
            //System.out.println("\n");
            if (Main.dinamique == 1 && path_Stack.size() > 0)
                while (!pq.isEmpty() && v_last == pq.peek().getG_cost_PLUS_h_cost() && nb < bar) {
                    nb++;
                    //System.out.println(it+"::"+nb+"::"+v_last+"::"+pq.peek().getG_cost_PLUS_h_cost());
                    path_Stack.add(0, pq.poll());
                }
            
            pq.clear();
        }
       
        if (optimal_Path != null) {
            System.out.print("\nCPU: "+optimal_Path.getG_cost());
        } else {
            System.out.print(10000);
        }
        System.out.println(", T: " + elapsedTime_cpu + " milliseconds");
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
//System.out.println(p.toString());
        return p;
    }
List list_val =null;
List list_all_val =null;
int it0=0;
  float[]  GpuEval (float [] initial_cost,int g1_nb_operation, int g2_nb_operation, float co1, float co2, float ce1, float ce2, int index_g1,int remain_g2_size ,int old_size, int [] remain_g2, int []  old_opf, int [] old_opt, CUdeviceptr adj_mat_g1, CUdeviceptr adj_mat_g2, CUdeviceptr weight_g1, CUdeviceptr weight_g2,CUdeviceptr deviceOutput,CUdeviceptr device_renmain_g2,CUdeviceptr device_old_opf ,CUdeviceptr device_old_opt, CUdeviceptr device_initail_cost, CUdeviceptr device_rank, CUdeviceptr device_best, CUdeviceptr device_nb , CUdeviceptr temp_remain, CUdeviceptr temp_old_opf, CUdeviceptr temp_old_opt)throws IOException 
  {it0++;
 //System.out.println("+++++++++++++++++++++++++start+++++++++++++++++++++++++++++++++++++++++");
        // Enable exceptions and omit all subsequent error checks
        JCudaDriver.setExceptionsEnabled(true);

        // Create the PTX file by calling the NVCC
        String ptxFileName = JGraphTtoGPU.preparePtxFile("gpu_evaluation.cu");

        // Load the ptx file.
        CUmodule module = new CUmodule();
        cuModuleLoad(module, ptxFileName);

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
        cuLaunchKernel(function,
                gridSizeX,  1, 1,      // Grid dimension
                blockSizeX, 1, 1,      // Block dimension
                0, null,               // Shared memory size and stream
                kernelParameters, null // Kernel- and extra parameters
        );
        cuCtxSynchronize();

        // Allocate host output memory and copy the device output
        // to the host.
         float hostOutput[] = new float[g2_nb_operation*Main.k_best];
        //cuMemcpyDtoH(Pointer.to(hostOutput), deviceOutput,
         //       g2_nb_operation*Main.k_best* Sizeof.FLOAT);


        // sorting and getting the best k elements
                sort(deviceOutput,g2_nb_operation, device_best,device_nb, device_rank);
              update_data  (index_g1 ,g1_nb_operation,g2_nb_operation, device_rank, device_nb, deviceOutput, device_renmain_g2, device_old_opf, device_old_opt, device_initail_cost,temp_remain, temp_old_opf, temp_old_opt);
       
          /*    int hostSort[] = new int[g2_nb_operation*Main.k_best];
                cuMemcpyDtoH(Pointer.to(hostSort), device_rank,
                g2_nb_operation*Main.k_best* Sizeof.INT);
  list_val = new ArrayList<Integer>();
          //   list_all_val = new ArrayList<Integer>();
           for(int i=0;i<g2_nb_operation*Main.k_best;i++){
            int j= (int) i%g2_nb_operation;
          //  if(hostOutput[i]==0)System.out.println("\n zero found"+i+ "rank:"+hostSort[i]+ "result:"+hostOutput[i]);
            if(hostSort[i]<Main.k_best && hostSort[i]>=0)
            {list_val.add((int)(i));
        // if(hostSort[i]==0)  System.out.println("\n best:"+i+ "rank:"+hostSort[i]+ "result:"+hostOutput[i]);// "value:"+ (hostOutput[i])); 
        }
         //  else {list_all_val.add((int)( (hostOutput[i])*100));}
         
          }
              */
         
        // Clean up
       

 //System.out.println("old:"+old_size);

        return hostOutput;
    }

     void sort  (CUdeviceptr deviceOutput, int g2_nb_operation, CUdeviceptr device_best ,CUdeviceptr device_nb ,CUdeviceptr device_rank )throws IOException {

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

         void update_data  (int index, int g1_nb_operation, int g2_nb_operation,CUdeviceptr device_rank,CUdeviceptr device_nb,  CUdeviceptr deviceOutput, CUdeviceptr remain_g2,  CUdeviceptr device_old_opf,  CUdeviceptr device_old_opt,  CUdeviceptr device_initial_result  , CUdeviceptr temp_remain, CUdeviceptr temp_old_opf, CUdeviceptr temp_old_opt)throws IOException {

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

           CUfunction function2 = new CUfunction();
        cuModuleGetFunction(function2, module, "update_data_2");

        Pointer kernelParameters = Pointer.to(Pointer.to(new int[] {index}), Pointer.to(new int[] {g1_nb_operation}),Pointer.to(new int[] {g2_nb_operation}),Pointer.to(new int[] {Main.k_best}),Pointer.to(device_rank), Pointer.to(device_nb) , Pointer.to(deviceOutput), Pointer.to(remain_g2), Pointer.to(device_old_opf), Pointer.to(device_old_opt), Pointer.to(temp_remain),Pointer.to(temp_old_opf),Pointer.to(temp_old_opt));
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
Pointer kernelParameters2 = Pointer.to(Pointer.to(new int[] {index}), Pointer.to(new int[] {g1_nb_operation}),Pointer.to(new int[] {g2_nb_operation}),Pointer.to(new int[] {Main.k_best}),Pointer.to(device_rank), Pointer.to(device_nb) , Pointer.to(deviceOutput), Pointer.to(remain_g2), Pointer.to(device_old_opf), Pointer.to(device_old_opt), Pointer.to(device_initial_result), Pointer.to(temp_remain),Pointer.to(temp_old_opf),Pointer.to(temp_old_opt));
         // update 2 kernel execution
        cuLaunchKernel(function2,
                gridSizeX,  1, 1,      // Grid dimension
                blockSizeX, 1, 1,      // Block dimension
                0, null,               // Shared memory size and stream
                kernelParameters2, null // Kernel- and extra parameters
        );
      //  System.out.println("Test update "+"PASSED");

     
    }


    void unprocessed_GPU_vertex( Graph g1, Graph g2, int g1_nb_operation, int g2_nb_operation, CUdeviceptr device_old_opf,  CUdeviceptr device_old_opt,int size) throws IOException {
   int old_opf[] = new int[g1_nb_operation*Main.k_best];
        cuMemcpyDtoH(Pointer.to(old_opf), device_old_opf,
                g1_nb_operation*Main.k_best* Sizeof.INT);

     int old_opt[] = new int[g1_nb_operation*Main.k_best];
        cuMemcpyDtoH(Pointer.to(old_opt), device_old_opt,
                g1_nb_operation*Main.k_best* Sizeof.INT);

    ArrayList<Vertex> listV1 = new ArrayList<>(g1.vertexSet());
    ArrayList<Vertex> listV2 = new ArrayList<>(g2.vertexSet());

   // for (int i=0;i<listV2.size();i++)System.out.println("v2:"+listV2.get(i).getVertex_id()+listV2.get(i).getVertex_weight());
    //for (int i=0;i<listV1.size();i++)System.out.println("v1:"+listV1.get(i).getVertex_id()+listV1.get(i).getVertex_weight());
   //  int size=g1_nb_operation;
     //if(size<g2_nb_operation)size=g2_nb_operation;
   
        for (int i=0;i<Main.k_best;i++){
            Path p= new Path(g1,g2);
            int p_opf=0, p_opt=0;
            for (int j=0;j<size;j++){
          int opf=-1;
          int opt=-1;
          if(j<g1_nb_operation&&j<g2_nb_operation){
            opf= old_opf[i*g1_nb_operation+j]; 
            opt= old_opt[i*g1_nb_operation+j];
            p_opf=opf;p_opt=opt;
      //  System.out.print("in");
        }
            else if(j<g1_nb_operation&&j>=g2_nb_operation){opt=-1; opf=p_opf+1; p_opf++;}
            else{opt=p_opt+1; opf=-1; p_opt++;}
  //System.out.println(" opf:"+opf+ "opt:"+opt);
          if(opf>0 && opt>0){
          Edit_Operation vertex_substitution_operation = new Edit_Operation(listV1.get(opf-1), listV2.get(opt-1));
          p.add(vertex_substitution_operation);
          }
          else if(opf>0 && opt<0) {
             Edit_Operation vertex_deletion_operation = new Edit_Operation(listV1.get(opf-1), null);
          p.add(vertex_deletion_operation);
           }
            else if(opf<0 && opt>0){     Edit_Operation vertex_insertion_operation = new Edit_Operation(null, listV2.get(opt-1));
          p.add(vertex_insertion_operation);  }
            }
            System.out.println("path i:"+i+ "eval cpu:"+p.getG_cost());
        }






    }

}


