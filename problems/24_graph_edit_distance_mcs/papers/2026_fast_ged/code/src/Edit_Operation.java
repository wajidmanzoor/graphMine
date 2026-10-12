//import graph_element.Vertex;

import java.util.List;

/**
 * @author adel
 */
public class Edit_Operation {

    private Vertex fromVertex; // From Vertex (in the operation)

    private Vertex toVertex; // To Vertex (in the operation)

    private GED_Operations operation_type; // Type of the operation

    private List<EdgeOperation> edge_Implied_Operation;

    /**
     * Default Constructor
     */

    @SuppressWarnings("unused")
    private Edit_Operation() {
        // Ensure non-instantiability (without arguments)
    }

    /**
     * @param fromVertex
     * @param toVertex
     */
    public Edit_Operation(Vertex fromVertex, Vertex toVertex) {

        // assert the tow args not null
        if (fromVertex == null && toVertex == null) {
            throw new IllegalArgumentException("illegal operation from" + fromVertex + "to" + toVertex);
        } else if (fromVertex == null) {
            this.operation_type = GED_Operations.Vertex_INSERTION;
        } else if (toVertex == null) {
            this.operation_type = GED_Operations.Vertex_DELETION;
        } else {
            this.operation_type = GED_Operations.Vertex_SUBSTITUTION;
        }

        // Set the vertices of the operation
        this.fromVertex = fromVertex;
        this.toVertex = toVertex;
        this.edge_Implied_Operation = null;
    }


    /**
     * @return the operation_type
     */
    public GED_Operations getOperation_type() {
        return operation_type;
    }

    /**
     * @return the fromVertex
     */
    public Vertex getFromVertex() {
        return fromVertex;
    }

    /**
     * @return the toVertex
     */
    public Vertex getToVertex() {
        return toVertex;
    }

    /**
     * @return the edge_Implied_Operation
     */
    public List<EdgeOperation> getEdge_Implied_Operation() {
        return edge_Implied_Operation;
    }

    /**
     * @param edge_Implied_Operation the edge_Implied_Operation to set
     */
    public void setEdge_Implied_Operation(List<EdgeOperation> edge_Implied_Operation) {
        this.edge_Implied_Operation = edge_Implied_Operation;
    }

    /* (non-Javadoc)
     * @see java.lang.Object#toString()
     */
    @Override
    public String toString() {

        if (edge_Implied_Operation != null)
            return "(" + fromVertex + "-->" + toVertex + ")" + ", " + edge_Implied_Operation.toString();
        else
            return "(" + fromVertex + "-->" + toVertex + ")";
    }

}


// ibra : choof kifach t'ajouter ce code ici dans Edit_Operation,
// ibra : je pense que edge implied operation marahich makhdoma, donc choof kifache takhdemha...
/*
 public class EdgeOperation {

	Edge fromEdge;

	Edge toEdge;


	public EdgeOperation (Edge fromE, Edge toE) {

		fromEdge = fromE;
		toEdge = toE;
	}


	// (non-Javadoc)
	// @see java.lang.Object#toString().
	//
	 @Override
	public String toString() {
	return "(" + fromEdge + "-->" + toEdge + ")";
}


}
*/