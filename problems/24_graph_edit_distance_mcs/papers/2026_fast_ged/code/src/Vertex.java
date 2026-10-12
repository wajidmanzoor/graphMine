//package graph_element;

/**
 * Created by user on 23/03/2017.
 */
public class Vertex {

    private int vertex_id;
    private int vertex_weight;
    private String vertexLabel; // the label on the vertex  or  the vertex name

    public Vertex() {
    }

    public Vertex(int vertex_id) {
        this.vertex_id = vertex_id;
    }

    public Vertex(int vertex_id, int vertex_weight) {
        this.vertex_id = vertex_id;
        this.vertex_weight = vertex_weight;
    }

    public Vertex(int vertex_id, String vertexLabel) {
        this.vertex_id = vertex_id;
        this.vertexLabel = vertexLabel;
    }

    public Vertex(int vertex_id, int vertex_weight, String vertexLabel) {
        this.vertex_id = vertex_id;
        this.vertex_weight = vertex_weight;
        this.vertexLabel = vertexLabel;
    }

    public Vertex(String vertexLabel) {
        this.vertexLabel = vertexLabel;
    }

    public int getVertex_id() {
        return vertex_id;
    }

    public void setVertex_id(int vertex_id) {
        this.vertex_id = vertex_id;
    }

    public int getVertex_weight() {
        return vertex_weight;
    }

    public void setVertex_weight(int vertex_weight) {
        this.vertex_weight = vertex_weight;
    }

    public String getVertexLabel() {
        return vertexLabel;
    }

    public void setVertexLabel(String vertexLabel) {
        this.vertexLabel = vertexLabel;
    }


    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (o == null || getClass() != o.getClass()) return false;

        Vertex vertex = (Vertex) o;

        if (vertex_id != vertex.vertex_id) return false;
        if (vertex_weight != vertex.vertex_weight) return false;
        return vertexLabel != null ? vertexLabel.equals(vertex.vertexLabel) : vertex.vertexLabel == null;
    }

    @Override
    public int hashCode() {
        int result = vertex_id;
        result = 31 * result + vertex_weight;
        result = 31 * result + (vertexLabel != null ? vertexLabel.hashCode() : 0);
        return result;
    }

    /*
    @Override
    public String toString() {
        if (this.vertexLabel != null)
            return " " + vertexLabel + " ";
        else
            return getClass().getName() + "@" + Integer.toHexString(hashCode());
    }
    */

    @Override
    public String toString() {
        return "V_" + vertex_id +
                "{" + vertex_weight + ", " + vertexLabel + "}" +
                '\'';
    }
}
