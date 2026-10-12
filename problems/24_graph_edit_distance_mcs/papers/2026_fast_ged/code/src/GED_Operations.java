
/**
 * Different types of the Graph Edit Distance (GED) Operations on the Graph vertices and edges
 */

public enum GED_Operations {
    Vertex_SUBSTITUTION, // vertex: u      -->v ;
    Vertex_INSERTION,    // vertex: epsilon-->v ;
    Vertex_DELETION,     // vertex: u      -->epsilon ;

    Edge_SUBSTITUTION, // edge: e1     -->e2
    Edge_INSERTION,    // edge: epsilon-->e2
    Edge_DELETION;     // edge: e1     -->epsilon
}
