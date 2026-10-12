/**
 * Created by user on 26/03/2017.
 * <p>
 * h function heuristic estimate future cost.
 */

//import graph_element.Edge;
//import graph_element.Vertex;
import org.jgrapht.Graph;

import java.util.ArrayList;


public final class h_function {

    private static double[][] cost_matrix;
    private static int n;
    private static int m;

    private static int Value_Min_Max = Integer.MAX_VALUE; // Integer.MAX_VALUE if wa calculate min cost, or Integer.MIN_VALUE if max cost;

    private static ArrayList<Vertex> list_vertices_g1;
    private static ArrayList<Vertex> list_vertices_g2;

    private static ArrayList<Edge> list_edges_g1;
    private static ArrayList<Edge> list_edges_g2;

    private h_function() {
    }


    public final static double compute(Graph g1, Graph g2, String min_OR_max) {
        double h_Vertices_Cost;
        double h_Edges_Cost;


        int n1 = g1.vertexSet().size();// get the nomber of vertices in g1
        int n2 = g2.vertexSet().size();// get the nomber of vertices in g2

        h_function.list_vertices_g1 = new ArrayList<Vertex>(g1.vertexSet());
        h_function.list_vertices_g2 = new ArrayList<Vertex>(g2.vertexSet());

        int m1 = g1.edgeSet().size();
        int m2 = g2.edgeSet().size();

        h_function.list_edges_g1 = new ArrayList<Edge>(g1.edgeSet());
        h_function.list_edges_g2 = new ArrayList<Edge>(g2.edgeSet());

        if (min_OR_max.equals("min")) {
            Value_Min_Max = Integer.MAX_VALUE;
        } else {
            Value_Min_Max = Integer.MIN_VALUE;
        }


        // if the tow sets exist, then we can execute the hangarian algo
        if (n1 > 0 && n2 > 0) {
            h_function.create_cost_matrix_vertices(n1, n2);

//            System.out.println("---------------------------- vertex Matrix :");
//            h_function.print_cost_matrix_at_once();

            int[][] assignment = new int[cost_matrix.length][2];
            assignment = HungarianAlgorithm.hgAlgorithm(h_function.cost_matrix, min_OR_max);    //Call Hungarian algorithm.


            double sum = 0;
            for (int i = 0; i < assignment.length; i++) {
                sum = sum + h_function.cost_matrix[assignment[i][0]][assignment[i][1]];
            }

            h_Vertices_Cost = sum;

        } else {
            // The cost of max{0, n1-n2} node deletions and max{0, n2-n1} node insertions
            h_Vertices_Cost = Math.max(0, n1 - n2) * GED_Operations_Cost.getVertex_deletion_cost() + Math.max(0, n2 - n1) * GED_Operations_Cost.getVertex_insertion_cost();

        }


        // --------------------------------------------------------------------------------
        //  ----------------  do the same thing with edges :)


        // creat the coste matrix for edges:

        if (m1 > 0 && m2 > 0) {
            h_function.create_cost_matrix_edges(m1, m2);

//            System.out.println("---------------------------- edge matice :");
//            h_function.print_cost_matrix_at_once();

            int[][] assignment_edges = new int[cost_matrix.length][2];
            assignment_edges = HungarianAlgorithm.hgAlgorithm(h_function.cost_matrix, min_OR_max);    //Call Hungarian algorithm.


            double sum_edges = 0;
            for (int i = 0; i < assignment_edges.length; i++) {
                sum_edges = sum_edges + h_function.cost_matrix[assignment_edges[i][0]][assignment_edges[i][1]];
            }

            h_Edges_Cost = sum_edges;

        } else {
            // The cost of max{0, m1-m2} edge deletions and max{0, m2-m1} edge insertions
            h_Edges_Cost = Math.max(0, m1 - m2) * GED_Operations_Cost.getEdge_deletion_cost() + Math.max(0, m2 - m1) * GED_Operations_Cost.getEdge_insertion_cost();
        }


        // ------------------------------------------------------------------------------------


        return (h_Vertices_Cost + h_Edges_Cost);
    }


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

    private static void create_cost_matrix_edges(int Nb_element_first_set, int Nb_elements_second_set) {
        n = Nb_element_first_set;
        m = Nb_elements_second_set;

        //System.out.println(" n= "+n);
        //System.out.println(" m= "+m);

        // create the cost matrix:

        cost_matrix = new double[n + m][n + m];

        // Upper left == SUBSTITUTION :  == n x m == i x j
        for (int i = 0; i < n; i++) {
            for (int j = 0; j < m; j++) {
                cost_matrix[i][j] = GED_Operations_Cost.getEdge_substitution_cost(list_edges_g1.get(i), list_edges_g2.get(j));
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

    }


    private static void create_cost_matrix_vertices(int Nb_element_first_set, int Nb_elements_second_set) {

        n = Nb_element_first_set;
        m = Nb_elements_second_set;

        //System.out.println(" n= "+n);
        //System.out.println(" m= "+m);

        // create the cost matrix:

        cost_matrix = new double[n + m][n + m];

        // Upper left == SUBSTITUTION :  == n x m == i x j
        for (int i = 0; i < n; i++) {
            for (int j = 0; j < m; j++) {
                cost_matrix[i][j] = GED_Operations_Cost.getVertex_substitution_cost(list_vertices_g1.get(i), list_vertices_g2.get(j));
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

    }


    private static void print_cost_matrix_at_once() {

        if (h_function.cost_matrix == null) return;

        System.out.println("------------------------ affichage d'un seul cout nx2 x mx2 ");

        /* // ce code marche si la matrice n'est pas transposer, sinon, m doit etre met dans la 1er boucle et n dans la 2eme.
        for (int i = 0; i < this.n + this.m; i++) {
            for (int j = 0; j < this.m + this.n; j++) {
                System.out.print(this.cost_matrix[i][j] + "\t");
            }

            System.out.println();
        }
        */
        for (int i = 0; i < h_function.cost_matrix.length; i++) {
            for (int j = 0; j < h_function.cost_matrix[0].length; j++) {
                System.out.print(h_function.cost_matrix[i][j] + "\t");
            }

            System.out.println();
        }
    }

}
