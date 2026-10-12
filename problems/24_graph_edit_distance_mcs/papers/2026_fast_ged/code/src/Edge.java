//package graph_element;

import org.jgrapht.graph.DefaultEdge;

/**
 * Created by user on 26/04/2017.
 */
public class Edge extends DefaultEdge {

    String edgeLabale;

    //double weight;
    int weight;

    public Edge() {
    }

    public Edge(String edgeLabale) {

        this.edgeLabale = edgeLabale;
    }

    public Edge(int weight) {

        this.weight = weight;
    }

    public Edge(String edgeLabale, int weight) {
        this.edgeLabale = edgeLabale;
        this.weight = weight;
    }

    public String getEdgeLabale() {
        return edgeLabale;
    }

    public int getWeight() {
        return weight;
    }

    public void setEdgeLabale(String edgeLabale) {
        this.edgeLabale = edgeLabale;
    }

    public void setWeight(int weight) {
        this.weight = weight;
    }

    public Object getSource() {
        return super.getSource();
    }

    public Object getTarget() {
        return super.getTarget();
    }

    @Override
    public String toString() {
        if (this.edgeLabale != null)
            return "( " + ((Vertex) super.getSource()) + "--" + this.edgeLabale + "-- " + ((Vertex) super.getTarget()) + ")";


        return "( " + ((Vertex) super.getSource()) + "--(" + this.weight + ")-- " + ((Vertex) super.getTarget()) + ")";
    }
}
