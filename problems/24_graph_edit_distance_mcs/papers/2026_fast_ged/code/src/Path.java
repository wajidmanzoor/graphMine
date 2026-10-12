//import graph_element.Edge;
//import graph_element.Vertex;
import org.jgrapht.Graph;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

public class Path {

    //private int n; // number of row elements or number of element of the first set
    //private int m; // number of column elements or number of element of the seconds set

    //double[][] cost_matrix; // a matrix that contain a cost of edit graph operations, we use it to estimate the heuristic 'h'

    private List<Edit_Operation> path; // List of edit operations

    Path parent; // Parent path


    @SuppressWarnings("rawtypes")
    private static Graph g1, g2; // References to processed graphs g1 and g2

    // in reality we don't need to store these tow references in the path object.
    // but, because we use tow (02) methods (containsEdge(), getEdge() ) that depend on g1 and g2, so we need to use these references
    // the problem here is with each node we lose the space of 2*size(reference variable).


    private static int nb_vertices_g1_from; // The order of the first graph (from)

    private static int nb_vertices_g2_to; // The order of the second graph (to)

    // we don't need these tow variables at each node, because we know the size of vertices.
    // here we use theme in order to replace the call of "fromGraph.vertexSet().size()" each time.


    private static List<Vertex> list_vertices_g1; // list of all vertices of graph 1

    // also this list is used to access to vertices as local variable (also for readability),
    // we don't need to use put it at each node.

    // all tha variables : g1, g2, nb_vertices_g1_from, nb_vertices_g2_to, list_vertices_g1
    // are not related to change at each intermediate node, so we make theme static,
    // like this they will not be in the object node.


    private int index_processed_vertices_g1; // The last index of the processed vertices in the first graph g1
    // this variable is related to the node at the level "i"
    // when we chose a node to process, we can get "index_processed_vertices_g1"
    // chose node at level 5, and after we can chose another node at the level 2 because it have a better g+h value.

    private List<Vertex> remaining_unprocessed_vertex_g2; // The remaining set of unprocessed vertex in g2

    // in the process of resolving the Graph Edit Distance, in the search tree, at each level,
    // we take one vertex from g1, and we do all combination of vertices of g1 (and also one deletion)
    // so we will hav different path children outgoing from one node (in the search tree),
    // each path has an operation v from g1 and w_i from g2 (i: each time different vertex of g2).
    // so: when we deal with the set of g1, at each level of the search tree we choose one vertex, level i, we choose vertex i.
    //     It is therefore sufficient to use a single list and counter for all the process of search tree.
    // but in the second graph g2, at each time we choose a different vertex (each outgoing path has a different vertex from g2)
    // so we need to at each node to know which vertices that are not yet processed (The remaining set of unprocessed of vertices of g2 )


    private List<Edge> unprocessed_edges_g1; // The set of unprocessed edges in g1
    private List<Edge> unprocessed_edges_g2; // The set of unprocessed edges in g2

    // we need these tow variables, in orders to compute the h value at each intermediate node,
    // because each node in the tree have a different set of an unprocessed edges.
    // which is related to the processed or unprocessed vertices.
    // we can not store these variables, and instead, each time we compute the implied edges and then the unprocessed edges
    // but i think that will take a lot of amount of computing time because we have huge number of node to explore...
    // by the same thinking we can say that will take a lot of space memory...
    // here a chose to use these variable instead to do calculate theme.


    private double g_cost; // Effective path cost g(p)

    private double g_cost_PLUS_h_cost; // Estimated path cost: g(p) + h(p);

    private static final int Value_Min_Max = Integer.MAX_VALUE; // in this class (pass) we compute only cost min.


    /**
     * Default Constructor
     */
    @SuppressWarnings("unused")
    private Path() {
        // Ensure non-instantiability (without arguments)
    }

    /**
     * Constructor to create a new Path Object
     *
     * @param fromGraph
     * @param toGraph
     */
    @SuppressWarnings("rawtypes")
    public Path(Graph fromGraph, Graph toGraph) {
        this.parent = null;

        Path.g1 = fromGraph;
        Path.g2 = toGraph;

        this.path = new ArrayList<Edit_Operation>();

        Path.nb_vertices_g1_from = fromGraph.vertexSet().size();
        Path.nb_vertices_g2_to = toGraph.vertexSet().size();

        this.index_processed_vertices_g1 = 0;
        Path.list_vertices_g1 = new ArrayList<Vertex>(fromGraph.vertexSet());

        this.remaining_unprocessed_vertex_g2 = new ArrayList<Vertex>(toGraph.vertexSet());

        this.unprocessed_edges_g1 = new ArrayList<Edge>(fromGraph.edgeSet());
        this.unprocessed_edges_g2 = new ArrayList<Edge>(toGraph.edgeSet());


        this.g_cost = 0;
        List<Vertex> remainsV2 = this.getRemaining_unprocessed_vertex_g2();
        this.g_cost_PLUS_h_cost = g_cost;//+abs(((g1.vertexSet().size()-this.index_processed_vertices_g1)-this.getRemaining_unprocessed_vertex_g2().size()))*GED_Operations_Cost.getVertex_deletion_cost();// h();
    }

    /**
     * Constructor to clone a path to a new one
     *
     * @param path
     */
    public Path(Path path) {
        this.parent = path;

        this.path = new ArrayList<Edit_Operation>();
        //this.path.addAll(p.getPath());

        this.index_processed_vertices_g1 = path.getIndex_processed_vertices_g1();

        this.remaining_unprocessed_vertex_g2 = new ArrayList<Vertex>(path.remaining_unprocessed_vertex_g2);

        this.unprocessed_edges_g1 = new ArrayList<Edge>(path.unprocessed_edges_g1);
        this.unprocessed_edges_g2 = new ArrayList<Edge>(path.unprocessed_edges_g2);

        this.g_cost = path.getG_cost();

        this.g_cost_PLUS_h_cost = path.getG_cost_PLUS_h_cost();
    }


    /**
     * Heuristic h(p): aims at the estimation of the lower bound of the future costs
     *
     * @return return an estimation of the remaining optimal edit path cost
     */


    //  cost_matrix :
    //
    //  g1 : n
    //  g2 : m
    //            m          n
    //      +-----------+-----------+
    //      |           |           |
    //  n   |    Sub    |   Del     |
    //      |           |           |
    //      +-----------+-----------+
    //      |           |           |
    //  m   |   Insr    | Del-Del   |
    //      |           |           |
    //      +-----------+-----------+
    //
    // all operation are made from g1 to g2, (substitute,delete, insert): element of g1 (with,from,in) g2
    //
    // Upper left == SUBSTITUTION : (elements of g1:n) X (elements of g2:m)
    //
    // Upper right == DELETION : (all elements of g1:n), delete each elements of g1,  (its like a substitution of n element g1 with n epsilon)
    // we put the cost of each element on the diagonal (for the sake of mankers algorithm),
    // because if we put them on the same column, when mankers algo choose one element, all the elements on the same column will be exclude.
    // so, tu insure that each element can be chosen, we put in separate column
    // only diagonal are filled by cost, others case of the matrix (upper right) ar filed by Value_Min_Max
    //
    // Bottom left == insertion: (insert element of g2:m), its mean from g1 we insert all element of g2.
    // also, each element is inserted in the diagonal.
    // only diagonal are filled by cost, others case of the matrix (Bottom left) ar filed by Value_Min_Max
    //
    // Bottom right == Delete --> Delete  (substitution of empty (deleted) elements of g1 with empty (deleted) elements of g2)
    // The matrix (Bottom right) ar filed by 0, since the substitution of the form (empty-->empty) should not cause any cost.
    //
    // Value_Min_Max = +Infinity   if we compute the MIN assignment, (the assignment with the minimum cost)
    //                              like this, those region will not influence for the chose of assignment
    //                              because the value is +Infinity, so Mankers algo will not choose the element.
    //
    // Value_Min_Max = -Infinity    if we compute the Max assignment
    //                               same explanation (but in reverse :)
    //
    // ps : the matrix is always square (n+m)x2 , so when we apply mankers algo we don't need to check if (rows>column) to transpose the matrix.
    private double[][] create_cost_matrix_edges(int Nb_element_first_set, int Nb_elements_second_set) {

        int n = Nb_element_first_set;
        int m = Nb_elements_second_set;

        //System.out.println(" n= "+n);
        //System.out.println(" m= "+m);

        // create the cost matrix:

        double[][] cost_matrix = new double[n + m][n + m];

        // Upper left == SUBSTITUTION :  == n x m == i Upperx j
        for (int i = 0; i < n; i++) {
            for (int j = 0; j < m; j++) {
                cost_matrix[i][j] = GED_Operations_Cost.getEdge_substitution_cost(this.unprocessed_edges_g1.get(i), this.unprocessed_edges_g2.get(j));
            }
        }


        // Upper right == DELETION :  == (n X n) : n x (m + n) = i x m+j
        for (int i = 0; i < n; i++) {
            for (int j = 0 + m; j < m + n; j++) {
                if (j == i + m) // check the diagonal element
                {
                    cost_matrix[i][j] = cost_matrix[i][j] = GED_Operations_Cost.getEdge_deletion_cost();
                } else {
                    cost_matrix[i][j] = Value_Min_Max;
                }
            }
        }

        // Bottom left == insertion :  == (m X m): (n + m) x + m = i+n x j
        for (int i = 0 + n; i < n + m; i++) {
            for (int j = 0; j < m; j++) {
                if (i == j + n) // check the diagonal element
                {
                    cost_matrix[i][j] = GED_Operations_Cost.getEdge_insertion_cost();
                } else {
                    cost_matrix[i][j] = Value_Min_Max;
                }
            }
        }

        // Bottom right == delete-->delete :  ==   (m X n): n+m x m+n = n+i x m+j
        for (int i = 0 + n; i < n + m; i++) {
            for (int j = 0 + m; j < m + n; j++) {
                cost_matrix[i][j] = 0;
            }
        }

        return cost_matrix;
    }


    private double[][] create_cost_matrix_vertices(int Nb_element_first_set, int Nb_elements_second_set) {
        int n = Nb_element_first_set;
        int m = Nb_elements_second_set;

        // create the cost matrix:

        double[][] cost_matrix = new double[n + m][n + m];


        // Upper left == SUBSTITUTION :  == n x m == i x j
        for (int i = 0; i < n; i++) {
            for (int j = 0; j < m; j++) {
                cost_matrix[i][j] = GED_Operations_Cost.getVertex_substitution_cost(list_vertices_g1.get(this.index_processed_vertices_g1 + i), remaining_unprocessed_vertex_g2.get(j));
            }
        }

        // Upper right == DELETION :  == (n X n) : n x (m + n) = i x m+j
        for (int i = 0; i < n; i++) {
            for (int j = 0 + m; j < m + n; j++) {
                if (j == i + m) // check the diagonal element
                {
                    cost_matrix[i][j] = GED_Operations_Cost.getVertex_deletion_cost();
                } else {
                    cost_matrix[i][j] = Value_Min_Max;
                }
            }
        }

        // Bottom left == insertion :  == (m X m): (n + m) x + m = i+n x j
        for (int i = 0 + n; i < n + m; i++) {
            for (int j = 0; j < m; j++) {
                if (i == j + n) // check the diagonal element
                {
                    cost_matrix[i][j] = GED_Operations_Cost.getVertex_insertion_cost();
                } else {
                    cost_matrix[i][j] = Value_Min_Max;
                }
            }
        }

        // Bottom right == delete-->delete :  ==   (m X n): n+m x m+n = n+i x m+j
        for (int i = 0 + n; i < n + m; i++) {
            for (int j = 0 + m; j < m + n; j++) {
                cost_matrix[i][j] = 0;
            }
        }

        return cost_matrix;
    }

    private void print_cost_matrix_at_once(double[][] cost_matrix) {

        if (cost_matrix == null) return;

        System.out.println("------------------------ Displaying the cost matrix at once: nx2 x mx2 ");

        /* // This code works if the matrix is not transposed, otherwise, m must be put in the 1st loop and n in the 2nd.
        for (int i = 0; i < this.n + this.m; i++) {
            for (int j = 0; j < this.m + this.n; j++) {
                System.out.print(this.cost_matrix[i][j] + "\t");
            }

            System.out.println();
        }
        */
        for (int i = 0; i < cost_matrix.length; i++) {
            for (int j = 0; j < cost_matrix[0].length; j++) {
                System.out.print(cost_matrix[i][j] + "\t");
            }

            System.out.println();
        }
    }


    private double h() {
        double h_Vertices_Cost;
        double h_Edges_Cost;


        int n1 = Path.nb_vertices_g1_from - this.index_processed_vertices_g1; // get the number of remaining vertices in g1
        int n2 = remaining_unprocessed_vertex_g2.size(); // get the number of remaining vertices in g2

        int nb_unprocessed_edges_g1 = unprocessed_edges_g1.size();
        int nb_unprocessed_edges_g2 = unprocessed_edges_g2.size();

        double[][] cost_matrix;


        // create the cost matrix for vertices:

        // if the tow sets exist, then we can execute the hangarian algo
        if (n1 > 0 && n2 > 0) {
            cost_matrix = this.create_cost_matrix_vertices(n1, n2);

            /// print_cost_matrix_at_once();

            int[][] assignment = new int[cost_matrix.length][2];
            assignment = HungarianAlgorithm.hgAlgorithm(cost_matrix, "min");    //Call Hungarian algorithm.


            double sum = 0;
            for (int i = 0; i < assignment.length; i++) {
                sum = sum + cost_matrix[assignment[i][0]][assignment[i][1]];
            }

            h_Vertices_Cost = sum;

        } else {
            // The cost of max{0, n1-n2} node deletions and max{0, n2-n1} node insertions
            h_Vertices_Cost = Math.max(0, n1 - n2) * GED_Operations_Cost.getVertex_deletion_cost() + Math.max(0, n2 - n1) * GED_Operations_Cost.getVertex_insertion_cost();

        }


        // --------------------------------------------------------------------------------
        //  ----------------  do the same thing with edges :)


        // create the cost matrix for edges:

        if (nb_unprocessed_edges_g1 > 0 && nb_unprocessed_edges_g2 > 0) {
            cost_matrix = this.create_cost_matrix_edges(nb_unprocessed_edges_g1, nb_unprocessed_edges_g2);

            //print_cost_matrix_at_once();

            int[][] assignment_edges = new int[cost_matrix.length][2];
            assignment_edges = HungarianAlgorithm.hgAlgorithm(cost_matrix, "min");    //Call Hungarian algorithm.


            double sum_edges = 0;
            for (int i = 0; i < assignment_edges.length; i++) {
                sum_edges = sum_edges + cost_matrix[assignment_edges[i][0]][assignment_edges[i][1]];
            }

            h_Edges_Cost = sum_edges;

        } else {
            // The cost of max{0, nb_unprocessed_edges_g1-nb_unprocessed_edges_g2} edge deletions and max{0, nb_unprocessed_edges_g2-nb_unprocessed_edges_g1} edge insertions
            h_Edges_Cost = Math.max(0, nb_unprocessed_edges_g1 - nb_unprocessed_edges_g2) * GED_Operations_Cost.getEdge_deletion_cost() + Math.max(0, nb_unprocessed_edges_g2 - nb_unprocessed_edges_g1) * GED_Operations_Cost.getEdge_insertion_cost();
        }


        // ------------------------------------------------------------------------------------


        return (h_Vertices_Cost + h_Edges_Cost);
    }


    /**
     * Add an operation to the path
     *
     * @param edit_operation the Edit_Operation Object to add
     * @return
     */
    @SuppressWarnings("unchecked")

    public boolean add(Edit_Operation edit_operation) {
        boolean source_Edge_Exists;
        boolean target_Edge_Exists;

        double vertex_Cost = 0;
        double edges_Implied_Cost = 0;
        // All edit operations (vertices) performed
        List<Edit_Operation> old_Edit_Operation_List = get_Operations_List();

        if (this.path.add(edit_operation)) {
            if (edit_operation.getOperation_type() == GED_Operations.Vertex_SUBSTITUTION) {
                index_processed_vertices_g1++;

                remaining_unprocessed_vertex_g2.remove(edit_operation.getToVertex());

                vertex_Cost = GED_Operations_Cost.getVertex_substitution_cost(edit_operation.getFromVertex(), edit_operation.getToVertex());

            } else if (edit_operation.getOperation_type() == GED_Operations.Vertex_DELETION) {
                index_processed_vertices_g1++; // Vertex_DELETION v --> null

                vertex_Cost = GED_Operations_Cost.getVertex_deletion_cost();

            } else {
                remaining_unprocessed_vertex_g2.remove(edit_operation.getToVertex());

                vertex_Cost = GED_Operations_Cost.getVertex_insertion_cost();
            }

            /// System.out.println("----------------------------------------------- nb ops : "+old_Edit_Operation_List.size());
            Vertex edf = edit_operation.getFromVertex();
            Vertex edt = edit_operation.getToVertex();
            for (Edit_Operation old_Edit_Operation : old_Edit_Operation_List) {

                //System.out.println(" old edit op from : "+old_Edit_Operation.getFromVertex()+"  to "+old_Edit_Operation.getToVertex());

                // Check whether the source edge exists
                if (old_Edit_Operation.getFromVertex() == null || edf == null) {
                    source_Edge_Exists = false;
                } else {
                    source_Edge_Exists = g1.containsEdge(old_Edit_Operation.getFromVertex(), edf);
                }

                // Check whether the target edge exists
                if (old_Edit_Operation.getToVertex() == null || edt == null) {
                    target_Edge_Exists = false;
                } else {
                    target_Edge_Exists = g2.containsEdge(old_Edit_Operation.getToVertex(), edt);
                }


                if (source_Edge_Exists && !target_Edge_Exists) // Delete edge (e1 --> epsilon)
                {
                    if (edit_operation.getEdge_Implied_Operation() == null) {
                        edit_operation.setEdge_Implied_Operation(new ArrayList<EdgeOperation>());
                    }

                    //Edge e1 = new Edge(old_Edit_Operation.getFromVertex(), edit_operation.getFromVertex());
                    Edge e1 = (Edge) g1.getEdge(old_Edit_Operation.getFromVertex(), edf);

                    edit_operation.getEdge_Implied_Operation().add(new EdgeOperation(e1, null));
                    int factor = 1;
                    //if(edit_operation.getFromVertex()!=null) if(edit_operation.getFromVertex().getVertexLabel()=="N")factor=factor*10;
                    edges_Implied_Cost += factor * GED_Operations_Cost.getEdge_deletion_cost();

                    this.unprocessed_edges_g1.remove(e1);

                } else if (!source_Edge_Exists && target_Edge_Exists) // Add edge (epsilon --> e2)
                {

                    if (edit_operation.getEdge_Implied_Operation() == null) {
                        edit_operation.setEdge_Implied_Operation(new ArrayList<EdgeOperation>());
                    }

                    // Edge e2 = new Edge(old_Edit_Operation.getToVertex(), edit_operation.getToVertex());
                    Edge e2 = (Edge) g2.getEdge(old_Edit_Operation.getToVertex(), edt);
                    edit_operation.getEdge_Implied_Operation().add(new EdgeOperation(null, e2));
                    int factor = 1;
                    //if(edit_operation.getFromVertex()!=null) if(edit_operation.getFromVertex().getVertexLabel()=="N")factor=factor*10;
                    edges_Implied_Cost += factor * GED_Operations_Cost.getEdge_insertion_cost();

                    this.unprocessed_edges_g2.remove(e2);

                } else if (source_Edge_Exists && target_Edge_Exists) // substitution e1-->e2
                {
                    if (edit_operation.getEdge_Implied_Operation() == null) {
                        edit_operation.setEdge_Implied_Operation(new ArrayList<EdgeOperation>());
                    }

                    //Edge e1 = new Edge(old_Edit_Operation.getFromVertex(), edit_operation.getFromVertex());
                    Edge e1 = (Edge) g1.getEdge(old_Edit_Operation.getFromVertex(), edf);

                    // Edge e2 = new Edge(old_Edit_Operation.getToVertex(), edit_operation.getToVertex());
                    Edge e2 = (Edge) g2.getEdge(old_Edit_Operation.getToVertex(), edt);

                    edit_operation.getEdge_Implied_Operation().add(new EdgeOperation(e1, e2));

                    edges_Implied_Cost += GED_Operations_Cost.getEdge_substitution_cost(e1, e2);

                    this.unprocessed_edges_g1.remove(e1);
                    this.unprocessed_edges_g2.remove(e2);
                }
            }
//System.out.println("\n end add");
            // Update costs
            /// g_cost += op.cost();
            /// g_cost += GED_Operations_Cost.getOperationCost(edit_operation.getOperation_type());

            g_cost += vertex_Cost;
            g_cost += edges_Implied_Cost;

            g_cost_PLUS_h_cost = g_cost;// +abs(((g1.vertexSet().size()-this.index_processed_vertices_g1)-this.getRemaining_unprocessed_vertex_g2().size()))*GED_Operations_Cost.getVertex_deletion_cost()  ;//+ h();

            return true;

        } else
            return false;
    }

    /* (non-Javadoc)
     * @see java.lang.Object#toString()
     */
    @Override
    public String toString() {
        return "NB ops : " + get_Operations_List().size() + " | Path [p=" + get_Operations_List().toString() + ", g(p)+h(p)=" + g_cost_PLUS_h_cost + "]";
    }

    public double add_cost(Edit_Operation edit_operation) {
        boolean source_Edge_Exists;
        boolean target_Edge_Exists;

        double vertex_Cost = 0;
        double edges_Implied_Cost = 0;
        // All edit operations (vertices) performed
        List<Edit_Operation> old_Edit_Operation_List = get_Operations_List();

        if (this.path.add(edit_operation)) {
            if (edit_operation.getOperation_type() == GED_Operations.Vertex_SUBSTITUTION) {
                vertex_Cost = GED_Operations_Cost.getVertex_substitution_cost(edit_operation.getFromVertex(), edit_operation.getToVertex());

            } else if (edit_operation.getOperation_type() == GED_Operations.Vertex_DELETION) {
                vertex_Cost = GED_Operations_Cost.getVertex_deletion_cost();

            } else {
                vertex_Cost = GED_Operations_Cost.getVertex_insertion_cost();
            }

            /// System.out.println("----------------------------------------------- nb ops : "+old_Edit_Operation_List.size());
            for (Edit_Operation old_Edit_Operation : old_Edit_Operation_List) {
                /// System.out.println(" old edit op : "+old_Edit_Operation.toString());
                // Check whether the source edge exists
                if (old_Edit_Operation.getFromVertex() == null || edit_operation.getFromVertex() == null) {
                    source_Edge_Exists = false;
                } else {
                    source_Edge_Exists = g1.containsEdge(old_Edit_Operation.getFromVertex(), edit_operation.getFromVertex());
                }

                // Check whether the target edge exists
                if (old_Edit_Operation.getToVertex() == null || edit_operation.getToVertex() == null) {
                    target_Edge_Exists = false;
                } else {
                    target_Edge_Exists = g2.containsEdge(old_Edit_Operation.getToVertex(), edit_operation.getToVertex());
                }


                if (source_Edge_Exists && !target_Edge_Exists) // Delete edge (e1 --> epsilon)
                {
                    if (edit_operation.getEdge_Implied_Operation() == null) {
                        // edit_operation.setEdge_Implied_Operation(new ArrayList<EdgeOperation>());
                    }

                    //Edge e1 = new Edge(old_Edit_Operation.getFromVertex(), edit_operation.getFromVertex());
                    //Edge e1 = (Edge) g1.getEdge(old_Edit_Operation.getFromVertex(), edit_operation.getFromVertex());
                    //edit_operation.getEdge_Implied_Operation().add(new EdgeOperation(e1, null));

                    edges_Implied_Cost += GED_Operations_Cost.getEdge_deletion_cost();

                    //  this.unprocessed_edges_g1.remove(e1);

                } else if (!source_Edge_Exists && target_Edge_Exists) // Add edge (epsilon --> e2)
                {

                    if (edit_operation.getEdge_Implied_Operation() == null) {
                        //   edit_operation.setEdge_Implied_Operation(new ArrayList<EdgeOperation>());
                    }

                    // Edge e2 = new Edge(old_Edit_Operation.getToVertex(), edit_operation.getToVertex());
                    //  Edge e2 = (Edge) g2.getEdge(old_Edit_Operation.getToVertex(), edit_operation.getToVertex());
                    //  edit_operation.getEdge_Implied_Operation().add(new EdgeOperation(null, e2));

                    edges_Implied_Cost += GED_Operations_Cost.getEdge_insertion_cost();

                    //  this.unprocessed_edges_g2.remove(e2);

                } else if (source_Edge_Exists && target_Edge_Exists) // substitution e1-->e2
                {
                    if (edit_operation.getEdge_Implied_Operation() == null) {
                        //     edit_operation.setEdge_Implied_Operation(new ArrayList<EdgeOperation>());
                    }

                    //Edge e1 = new Edge(old_Edit_Operation.getFromVertex(), edit_operation.getFromVertex());
                    Edge e1 = (Edge) g1.getEdge(old_Edit_Operation.getFromVertex(), edit_operation.getFromVertex());

                    // Edge e2 = new Edge(old_Edit_Operation.getToVertex(), edit_operation.getToVertex());
                    Edge e2 = (Edge) g2.getEdge(old_Edit_Operation.getToVertex(), edit_operation.getToVertex());

                    // edit_operation.getEdge_Implied_Operation().add(new EdgeOperation(e1, e2));

                    edges_Implied_Cost += GED_Operations_Cost.getEdge_substitution_cost(e1, e2);

                    //  this.unprocessed_edges_g1.remove(e1);
                    // this.unprocessed_edges_g2.remove(e2);
                }
            }

            // Update costs
            /// g_cost += op.cost();
            /// g_cost += GED_Operations_Cost.getOperationCost(edit_operation.getOperation_type());

            double gg_cost = g_cost + vertex_Cost + edges_Implied_Cost;


            // g_cost_PLUS_h_cost = g_cost ;//+ h();

            return gg_cost;

        } else
            return 0;
    }


    public List<Edit_Operation> get_Operations_List() {
        List<Edit_Operation> operationsList = new ArrayList<Edit_Operation>();
        if (parent != null) {
            operationsList.addAll(parent.get_Operations_List());
        }

        operationsList.addAll(path);

        return operationsList;
    }

    /*
     **********************************************
     * Getters									  *
     **********************************************
     */

    /**
     * @return the index_processed_vertices_g1
     */
    public int getIndex_processed_vertices_g1() {
        return index_processed_vertices_g1;
    }


    /**
     * @return the path
     */
    public List<Edit_Operation> getPath() {
        return path;
    }

    /**
     * @return the nb_vertices_g1_from
     */
    public int getNb_vertices_g1_from() {
        return nb_vertices_g1_from;
    }

    /**
     * @return the nb_vertices_g2_to
     */
    public int getNb_vertices_g2_to() {
        return nb_vertices_g2_to;
    }

    /**
     * @return the g_cost
     */
    public double getG_cost() {
        return g_cost;
    }

    /**
     * @return the g_cost_PLUS_h_cost
     */
    public double getG_cost_PLUS_h_cost() {
        return g_cost_PLUS_h_cost;
    }

    /**
     * Check if the path is complete
     *
     * @return
     */
    public boolean isCompleteEditPath() {
        return (index_processed_vertices_g1 >= nb_vertices_g1_from && remaining_unprocessed_vertex_g2.size() <= 0);
    }


    public List<Vertex> getRemaining_unprocessed_vertex_g2() {
        return remaining_unprocessed_vertex_g2;
    }

}

class PathComparator implements Comparator<Path> {

    // Overriding compare()method of Comparator
    // for descending order of cgpa
    public int compare(Path s1, Path s2) {
        //  if (s1.getG_cost_PLUS_h_cost() < s2.getG_cost_PLUS_h_cost())
        if (s1.getG_cost() + s1.getG_cost_PLUS_h_cost() < s2.getG_cost() + s2.getG_cost_PLUS_h_cost())
            return -1;
        else if (s1.getG_cost() + s1.getG_cost_PLUS_h_cost() > s2.getG_cost() + s2.getG_cost_PLUS_h_cost())// if (s1.getG_cost_PLUS_h_cost() > s2.getG_cost_PLUS_h_cost())
            return +1;
        return 0;
    }
}
