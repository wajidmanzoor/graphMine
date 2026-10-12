/**
 *
 */

//import graph_element.Edge;

public class EdgeOperation {

    Edge fromEdge;

    Edge toEdge;

    private EdgeOperation() {
        // Ensure non-instantiability (without arguments)
    }

    public EdgeOperation(Edge fromE, Edge toE) {

        fromEdge = fromE;
        toEdge = toE;
    }


    /* (non-Javadoc)
     * @see java.lang.Object#toString()
     */
    @Override
    public String toString() {
        if (fromEdge != null && toEdge != null)
            return "(" + fromEdge.toString() + "-->" + toEdge.toString() + ")";

        if (fromEdge == null && toEdge != null)
            return "( null -->" + toEdge.toString() + ")";

        if (fromEdge != null && toEdge == null)
            return "(" + fromEdge.toString() + "--> null )";

        return "( null --> null )";
    }
}
