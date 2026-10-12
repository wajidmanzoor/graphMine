//import Edge.Edge;
//import Vertex.Vertex;
import net.sourceforge.gxl.*;
import org.jgrapht.UndirectedGraph;
import org.jgrapht.graph.SimpleGraph;
import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.Node;
import org.w3c.dom.NodeList;
import org.xml.sax.SAXException;
import javax.xml.parsers.DocumentBuilder;
import javax.xml.parsers.DocumentBuilderFactory;
import javax.xml.parsers.ParserConfigurationException;
import java.io.*;

public class Import_JGraphT_From_GXL {

    GXLDocument gxlDoc = new GXLDocument(new File("path/to/your/gxl/file.gxl"));

    public Import_JGraphT_From_GXL() throws IOException, SAXException {
    }

    // acyclic, alkane, mao and pah Benchmark :  Vertex Weight (int),  Edge Weight (int).
    //                                           Id begin from _1 , with the char "_" before the ID.
    public static UndirectedGraph<Vertex, Edge> import_simple_graph(String gxl_path_file) {
        UndirectedGraph<Vertex, Edge> graph_JGJ = new SimpleGraph(Edge.class);

        int node_id=1;
        int diff=-10;
        try {
            File gxlFile = new File(gxl_path_file);
          //  Importer<Integer, DefaultEdge> importer = new GraphMLImporter<>();
            GXLDocument gxlDocument = new GXLDocument(gxlFile);


            GXLGraph graph_GXL = gxlDocument.getDocumentElement().getGraphAt(0);

            GXLNode gxlNode;
            GXLEdge gxlEdge;
            GXLAttr gxlAttr;
            GXLInt gxlInt;

            int nodeId;
            int nodeValue;

            int edgeValue;

            int nb_element = graph_GXL.getGraphElementCount();

            //int nbNode=(int) Math.ceil((0.75)*(nb_element)); // on supose que le nombre de nodes est de 3/4 de toutes les elemeents
            //ArrayList<Vertex> arrayList = new ArrayList<Vertex>(nbNode);

            int nbNode = nb_element; // we supose that all element are node, because here we can't risk, unless we find a fast methode to know the number of nodes

            Vertex[] arry_ref_vertex = new Vertex[nbNode + 1]; // +1 , beacause Node ID begin from 1. so to not each time do (nodeID-1)


            for (int i = 0; i < nb_element; i++) {
                GXLElement graphElement = graph_GXL.getGraphElementAt(i);

                if (graphElement instanceof GXLNode) {
                    gxlNode = ((GXLNode) graphElement);
                    nodeId = node_id;
                    int true_id=Integer.parseInt(gxlNode.getID());
                    if(diff==-10)diff=node_id-true_id;
                    node_id++;
                    gxlAttr = gxlNode.getAttrAt(0);

                    gxlInt = (GXLInt) gxlAttr.getChildAt(0);

                    nodeValue = gxlInt.getIntValue();

                    Vertex v = new Vertex(nodeId, nodeValue);

                    graph_JGJ.addVertex(v);

                    arry_ref_vertex[v.getVertex_id()] = v;
                } else if (graphElement instanceof GXLEdge) {
                    gxlEdge = (GXLEdge) graphElement;

                /*System.out.println(" Edge : "+((GXLEdge) graphElement).getID()+
                        "| form: "+((GXLEdge) graphElement).getSourceID()+
                        "--> to : "+((GXLEdge) graphElement).getTargetID());*/

                    int nodeID_from = Integer.parseInt(((GXLEdge) graphElement).getSourceID().substring(1))+diff;
                    int nodeID_to = Integer.parseInt(((GXLEdge) graphElement).getTargetID().substring(1))+diff;

                    edgeValue = ((GXLInt) (gxlEdge.getAttrAt(0).getChildAt(0))).getIntValue();

                    if (arry_ref_vertex[nodeID_from] != null && arry_ref_vertex[nodeID_to] != null) {
                        Edge myEdge = graph_JGJ.addEdge(arry_ref_vertex[nodeID_from], arry_ref_vertex[nodeID_to]);

                        myEdge.setWeight(edgeValue);
                    }
                }
            }

        } catch (FileNotFoundException e) {
            e.printStackTrace();
        } catch (IOException e) {
            e.printStackTrace();
        } catch (SAXException e) {
            e.printStackTrace();
        }

        return graph_JGJ;
    }
    public static UndirectedGraph<Vertex, Edge> GxlReader(String file) {
      /*  File tempFile = null;
        try {
            tempFile = File.createTempFile("tempfile", ".txt");
        } catch (IOException e) {
            throw new RuntimeException(e);
        }*/
        File tempFile = null;//new File("temp.txt");
        try {
            tempFile = File.createTempFile("tempfile", ".txt");
        } catch (IOException e) {
            throw new RuntimeException(e);
        }

        UndirectedGraph<Vertex, Edge> graph_JGJ = new SimpleGraph(Edge.class);
        Vertex[] arry_ref_vertex = new Vertex[5000];
        try (BufferedReader reader = new BufferedReader(new FileReader(file))) {

            String line=reader.readLine();

            while ((line = reader.readLine()) != null) {
                DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
                DocumentBuilder builder = factory.newDocumentBuilder();
                // Check if the line contains a node definition
                if (line.contains("<node")) {
                    //
                    // Write the string content to the file
                    byte[] arr=line.getBytes();
                    FileWriter writer = new FileWriter(tempFile,false);
                    writer.write(line);
                    writer.close();

                    Document doc = builder.parse(tempFile );
                    NodeList nodes = doc.getElementsByTagName("node");
                    NodeList attrs = doc.getElementsByTagName("attr");
                    int nodeId=0;
                    String nodeValue="";
                    String nodeLabel="";
                    for (int i = 0; i < nodes.getLength(); i++) {
                        Node node = nodes.item(i);
                        if (node.getNodeType() == Node.ELEMENT_NODE) {
                            Element element = (Element) node;
                            String id = element.getAttribute("id");
                            nodeId=Integer.parseInt(id);
                           // System.out.println("Node ID: " + id);
                        }
                    }

                  //  String nodeId = line.substring(line.indexOf("\"") + 1, line.lastIndexOf("\""));

                    for (int i = 0; i < attrs.getLength(); i++) {
                        Node attr = attrs.item(i);
                        if (attr.getNodeType() == Node.ELEMENT_NODE) {
                            Element element = (Element) attr;
                            String attrName = element.getAttribute("name");
                            String attrValue = element.getElementsByTagName("int").item(0).getTextContent();
                           // System.out.println(attrName + ": " + attrValue);

                            if(attrName.equals("sequence")){nodeLabel=attrValue;}
                            else if(attrName.equals("type")){nodeValue=nodeValue + attrValue;}
                    /*String type = element.getAttribute("type");
                    String length = element.getAttribute("aalength");
                    String sequence = element.getAttribute("sequence");
                    System.out.println("attr type: " + type + ", Length: " + length + " seq"+sequence);*/
                        }
                    }

                    int nodeValueHash = HashFunction.getHash(nodeValue);

                    Vertex v = new Vertex(nodeId, nodeValueHash, nodeLabel);
                   // v.setVertexLabel(nodeLabel);
                   // System.out.println(nodeId+"/"+nodeValueHash+"/"+nodeLabel);
                    arry_ref_vertex[nodeId]=v;
                    graph_JGJ.addVertex(v);
                }


                if (line.contains("<edge")) {

                    // Write the string content to the file
                    FileWriter writer = new FileWriter(tempFile,false);
                    writer.write(line);
                    writer.close();
                    int nodeID_to=-1;
                    int nodeID_from=-1;
                    Document doc = builder.parse(tempFile );
                    NodeList edges = doc.getElementsByTagName("edge");
                    NodeList attrs = doc.getElementsByTagName("attr");
                    for (int i = 0; i < edges.getLength(); i++) {
                        Node edge = edges.item(i);
                        if (edge.getNodeType() == Node.ELEMENT_NODE) {
                            Element element = (Element) edge;
                            String from = element.getAttribute("from");
                            String to = element.getAttribute("to");
                            nodeID_from=Integer.parseInt(from);
                            nodeID_to=Integer.parseInt(to);

                        }
                    }

                    //  String nodeId = line.substring(line.indexOf("\"") + 1, line.lastIndexOf("\""));
                    String edgeLabel="";
                    int frequency=1;
                    String [] type = new String[5];
                    int [] distance =new int[5];
                    int ind=0;
                    for (int i = 0; i < attrs.getLength(); i++) {
                        Node attr = attrs.item(i);
                        if (attr.getNodeType() == Node.ELEMENT_NODE) {
                            Element element = (Element) attr;
                            String attrName = element.getAttribute("name");
                            NodeList vint = element.getElementsByTagName("int");
                            NodeList vdouble = element.getElementsByTagName("double");
                            String attrValue="";
                            if(vint.getLength()>0){attrValue=element.getElementsByTagName("int").item(0).getTextContent();}
                            else if (vdouble.getLength()>0){attrValue=element.getElementsByTagName("double").item(0).getTextContent();}
                            if(attrName.equals("frequency")) {
                                frequency=Integer.parseInt(attrValue);
                            }else if (attrName.equals("type0")) {
                                type[0]=attrValue;
                            } else if (attrName.equals("type1")) {
                                type[1]=attrValue;
                            }
                            else if (attrName.equals("distance0")) {
                                distance[0]=(int)Float.parseFloat(attrValue);
                            } else if (attrName.equals("distance1")) {
                                distance[1]=  (int)Float.parseFloat(attrValue);

                            }

                          //  System.out.println(attrName + ": " + attrValue);
                    /*String type = element.getAttribute("type");
                    String length = element.getAttribute("aalength");
                    String sequence = element.getAttribute("sequence");
                    System.out.println("attr type: " + type + ", Length: " + length + " seq"+sequence);*/
                        }
                    }
                   // System.out.println(frequency+"  "+type[frequency-1]);
                   // Edge myEdge = graph_JGJ.addEdge(arry_ref_vertex[nodeID_from], arry_ref_vertex[nodeID_to]);
                    for (int i0=0 ;i0< frequency;i0++){
                        Edge myEdge=null;
                    if(i0==0) {   myEdge = graph_JGJ.addEdge(arry_ref_vertex[nodeID_from], arry_ref_vertex[nodeID_to]);}
                    else{myEdge = graph_JGJ.addEdge(arry_ref_vertex[nodeID_to], arry_ref_vertex[nodeID_from]);}
                       // System.out.println(frequency+"  "+type[frequency-1]+"  "+distance[frequency-1]);
                    if(myEdge!=null) {
                        String temp = myEdge.getEdgeLabale();
                        if (temp == null) temp = "";

                        myEdge.setEdgeLabale(/*temp+","+*/type[i0]);

                        myEdge.setWeight(/*i0*1000*myEdge.getWeight()+*/(int) (distance[i0] * 100));
                        // System.out.println(i0+" edge from: " + nodeID_from + " to " + nodeID_to);
                        //System.out.println(myEdge.getEdgeLabale() + ": " + myEdge.getWeight());
                    }
                    }

                }

                // Check if the line contains an edge definition
              /*  else if (line.contains("<edge from=")) {
                    String sourceNodeId = line.substring(line.indexOf("\"") + 1, line.indexOf("\" to="));
                    String targetNodeId = line.substring(line.lastIndexOf("\"") + 1, line.lastIndexOf("\">"));
                    System.out.println("Edge: From " + sourceNodeId + " to " + targetNodeId);
                }*/
            }
            tempFile.delete();
        } catch (IOException e) {
            e.printStackTrace();
        } catch (ParserConfigurationException e) {
            throw new RuntimeException(e);
        } catch (SAXException e) {
            throw new RuntimeException(e);
        }

     return graph_JGJ;
    }
    // MUTA-GED Benchmark :  Vertex Label (string),  Edge Weight (int).
    //                       Id begin from 1 without any char before the ID.
    public static UndirectedGraph<Vertex, Edge> import_simple_graph_from_MUTA_GED(String gxl_path_file) {
        UndirectedGraph<Vertex, Edge> graph_JGJ = new SimpleGraph(Edge.class);
 int node_id=1;
 int diff=-10;
        try {
            File gxlFile = new File(gxl_path_file);
            GXLDocument gxlDocument = new GXLDocument(gxlFile);


            GXLGraph graph_GXL = gxlDocument.getDocumentElement().getGraphAt(0);

            GXLNode gxlNode;
            GXLEdge gxlEdge;
            GXLAttr gxlAttr;
            GXLInt gxlInt;
            GXLString gxlString;

            int nodeId;
            String nodeValue;
            int nodeValueHash;

            int edgeValue;

            int nb_element = graph_GXL.getGraphElementCount();

            //int nbNode=(int) Math.ceil((0.75)*(nb_element)); // on supose que le nombre de nodes est de 3/4 de toutes les elemeents
            //ArrayList<Vertex> arrayList = new ArrayList<Vertex>(nbNode);

            int nbNode = nb_element; // we supose that all element are node, because here we can't risk, unless we find a fast methode to know the number of nodes

            Vertex[] arry_ref_vertex = new Vertex[nbNode + 1]; // +1 , beacause Node ID begin from 1. so to not each time do (nodeID-1)


            for (int i = 0; i < nb_element; i++) {
                GXLElement graphElement = graph_GXL.getGraphElementAt(i);

                if (graphElement instanceof GXLNode) {
                    gxlNode = ((GXLNode) graphElement);
                    nodeId = node_id;
                    int true_id=Integer.parseInt(gxlNode.getID());
                    if(diff==-10)diff=node_id-true_id;
                    node_id++;
                    gxlAttr = gxlNode.getAttrAt(0);

                    gxlString = (GXLString) gxlAttr.getChildAt(0);

                    nodeValue = gxlString.getValue();

                    nodeValueHash = HashFunction.getHash(nodeValue);

                    Vertex v = new Vertex(nodeId, nodeValueHash, nodeValue);

                    graph_JGJ.addVertex(v);

                    arry_ref_vertex[v.getVertex_id()] = v;
                } else if (graphElement instanceof GXLEdge) {
                    gxlEdge = (GXLEdge) graphElement;

                /*System.out.println(" Edge : "+((GXLEdge) graphElement).getID()+
                        "| form: "+((GXLEdge) graphElement).getSourceID()+
                        "--> to : "+((GXLEdge) graphElement).getTargetID());*/

                    int nodeID_from = Integer.parseInt(((GXLEdge) graphElement).getSourceID())+diff;
                    int nodeID_to = Integer.parseInt(((GXLEdge) graphElement).getTargetID())+diff;

                    edgeValue = ((GXLInt) (gxlEdge.getAttrAt(0).getChildAt(0))).getIntValue();

                    if (arry_ref_vertex[nodeID_from] != null && arry_ref_vertex[nodeID_to] != null) {
                        Edge myEdge = graph_JGJ.addEdge(arry_ref_vertex[nodeID_from], arry_ref_vertex[nodeID_to]);

                        myEdge.setWeight(edgeValue);
                    }
                }
            }

        } catch (FileNotFoundException e) {
            e.printStackTrace();
        } catch (IOException e) {
            e.printStackTrace();
        } catch (SAXException e) {
            e.printStackTrace();
        }

        return graph_JGJ;
    }

    // CMU-GED Benchmark :  Vertex : 2 Label (double, double),  Edge Weight (double).
    //                       Id begin from 1 without any char before the ID.
    public static UndirectedGraph<Vertex, Edge> import_simple_graph_from_CMU_GED(String gxl_path_file) {
        UndirectedGraph<Vertex, Edge> graph_JGJ = new SimpleGraph(Edge.class);
        int node_id=1;
        int diff=-10;
        try {
            File gxlFile = new File(gxl_path_file);
            GXLDocument gxlDocument = new GXLDocument(gxlFile);


            GXLGraph graph_GXL = gxlDocument.getDocumentElement().getGraphAt(0);

            GXLNode gxlNode;
            GXLEdge gxlEdge;
            GXLAttr gxlAttr;
            GXLInt gxlInt;
            GXLString gxlString;
            GXLFloat gxlFloat;

            int nodeId;
            Float nodeValue_1;
            Float nodeValue_2;
            String nodeValue_1_2;
            int nodeValueHash;

            Float edgeValue;
            int edgeValueHash;

            int nb_element = graph_GXL.getGraphElementCount();

            //int nbNode=(int) Math.ceil((0.75)*(nb_element)); // on supose que le nombre de nodes est de 3/4 de toutes les elemeents
            //ArrayList<Vertex> arrayList = new ArrayList<Vertex>(nbNode);

            int nbNode = nb_element; // we supose that all element are node, because here we can't risk, unless we find a fast methode to know the number of nodes

            Vertex[] arry_ref_vertex = new Vertex[nbNode + 1]; // +1 , beacause Node ID begin from 1. so to not each time do (nodeID-1)


            for (int i = 0; i < nb_element; i++) {
                GXLElement graphElement = graph_GXL.getGraphElementAt(i);

                if (graphElement instanceof GXLNode) {
                    gxlNode = ((GXLNode) graphElement);
                    nodeId = node_id;
                    int true_id=Integer.parseInt(gxlNode.getID());
                    if(diff==-10)diff=node_id-true_id;
                    node_id++;

                    gxlAttr = gxlNode.getAttrAt(0);
                    gxlFloat = (GXLFloat) gxlAttr.getChildAt(0);
                    nodeValue_1 = gxlFloat.getFloatValue();

                    gxlAttr = gxlNode.getAttrAt(1);
                    gxlFloat = (GXLFloat) gxlAttr.getChildAt(0);
                    nodeValue_2 = gxlFloat.getFloatValue();

                    nodeValue_1_2 = nodeValue_1 + "_" + nodeValue_2;

                    nodeValueHash = HashFunction.getHash(nodeValue_1_2);

                    Vertex v = new Vertex(nodeId, nodeValueHash);

                    graph_JGJ.addVertex(v);

                    arry_ref_vertex[v.getVertex_id()] = v;
                } else if (graphElement instanceof GXLEdge) {
                    gxlEdge = (GXLEdge) graphElement;

                /*System.out.println(" Edge : "+((GXLEdge) graphElement).getID()+
                        "| form: "+((GXLEdge) graphElement).getSourceID()+
                        "--> to : "+((GXLEdge) graphElement).getTargetID());*/

                    int nodeID_from = Integer.parseInt(((GXLEdge) graphElement).getSourceID())+diff;
                    int nodeID_to = Integer.parseInt(((GXLEdge) graphElement).getTargetID())+diff;

                    //edgeValue = ((GXLInt) (gxlEdge.getAttrAt(0).getChildAt(0))).getIntValue();
                   // edgeValue = ((GXLFloat) (gxlEdge.getAttrAt(0).getChildAt(0))).getFloatValue();
                   edgeValue = ((GXLFloat) (gxlEdge.getAttrAt(0).getChildAt(0))).getFloatValue();

                   edgeValueHash = Double.hashCode(edgeValue);

                    if (arry_ref_vertex[nodeID_from] != null && arry_ref_vertex[nodeID_to] != null) {
                        Edge myEdge = graph_JGJ.addEdge(arry_ref_vertex[nodeID_from], arry_ref_vertex[nodeID_to]);

                        myEdge.setWeight(edgeValueHash);
                    }
                }
            }
            
        } catch (FileNotFoundException e) {
            e.printStackTrace();
        } catch (IOException e) {
            e.printStackTrace();
        } catch (SAXException e) {
            e.printStackTrace();
        }

        return graph_JGJ;
    }

    public static UndirectedGraph<Vertex, Edge> import_simple_graph_GED(String gxl_path_file) {
        UndirectedGraph<Vertex, Edge> graph_JGJ = new SimpleGraph(Edge.class);
        int node_id=1;
        int diff=-1;
        try {
            File gxlFile = new File(gxl_path_file);
            GXLDocument gxlDocument = new GXLDocument(gxlFile);


            GXLGraph graph_GXL = gxlDocument.getDocumentElement().getGraphAt(0);

            GXLNode gxlNode;
            GXLEdge gxlEdge;
            GXLAttr gxlAttr;
            GXLInt gxlInt;
            GXLString gxlString;
            GXLFloat gxlFloat;

            int nodeId;
            Float nodeValue_1;
            Float nodeValue_2;
            String nodeValue_1_2;
            int nodeValueHash;

            Float edgeValue;
            int edgeValueHash;

            int nb_element = graph_GXL.getGraphElementCount();

            //int nbNode=(int) Math.ceil((0.75)*(nb_element)); // on supose que le nombre de nodes est de 3/4 de toutes les elemeents
            //ArrayList<Vertex> arrayList = new ArrayList<Vertex>(nbNode);

            int nbNode = nb_element; // we supose that all element are node, because here we can't risk, unless we find a fast methode to know the number of nodes

            Vertex[] arry_ref_vertex = new Vertex[nbNode + 1]; // +1 , beacause Node ID begin from 1. so to not each time do (nodeID-1)


            for (int i = 0; i < nb_element; i++) {
                GXLElement graphElement = graph_GXL.getGraphElementAt(i);

                if (graphElement instanceof GXLNode) {
                    gxlNode = ((GXLNode) graphElement);
                    nodeId = node_id;
                    int true_id=Integer.parseInt(gxlNode.getID());
                    if(diff==-10)diff=node_id-true_id;
                    node_id++;

                    gxlAttr = gxlNode.getAttrAt(0);
                    gxlFloat = (GXLFloat) gxlAttr.getChildAt(0);
                    nodeValue_1 = gxlFloat.getFloatValue();

                    gxlAttr = gxlNode.getAttrAt(1);
                    gxlFloat = (GXLFloat) gxlAttr.getChildAt(0);
                    nodeValue_2 = gxlFloat.getFloatValue();

                    nodeValue_1_2 = nodeValue_1 + "_" + nodeValue_2;

                    nodeValueHash = HashFunction.getHash(nodeValue_1_2);

                    Vertex v = new Vertex(nodeId, nodeValueHash);

                    graph_JGJ.addVertex(v);

                    arry_ref_vertex[v.getVertex_id()] = v;
                } else if (graphElement instanceof GXLEdge) {
                    gxlEdge = (GXLEdge) graphElement;

                /*System.out.println(" Edge : "+((GXLEdge) graphElement).getID()+
                        "| form: "+((GXLEdge) graphElement).getSourceID()+
                        "--> to : "+((GXLEdge) graphElement).getTargetID());*/

                    int nodeID_from = Integer.parseInt(((GXLEdge) graphElement).getSourceID())+diff;
                    int nodeID_to = Integer.parseInt(((GXLEdge) graphElement).getTargetID())+diff;

                    //edgeValue = ((GXLInt) (gxlEdge.getAttrAt(0).getChildAt(0))).getIntValue();
                    edgeValue = ((GXLFloat) (gxlEdge.getAttrAt(0).getChildAt(0))).getFloatValue();

                    // edgeValueHash = Double.hashCode(edgeValue);

                    if (arry_ref_vertex[nodeID_from] != null && arry_ref_vertex[nodeID_to] != null) {
                        Edge myEdge = graph_JGJ.addEdge(arry_ref_vertex[nodeID_from], arry_ref_vertex[nodeID_to]);

                        //  myEdge.setWeight(edgeValueHash);
                    }
                }
            }

        } catch (FileNotFoundException e) {
            e.printStackTrace();
        } catch (IOException e) {
            e.printStackTrace();
        } catch (SAXException e) {
            e.printStackTrace();
        }

        return graph_JGJ;
    }

    // GREC-GED Benchmark :  Vertex : 3 Label (Integer, Integer, String),  Edge 3 labels (Integer, String, String).
    //                       Id begin from 1 without any char before the ID.
    public static UndirectedGraph<Vertex, Edge> import_simple_graph_from_GREC_GED(String gxl_path_file) {
       // System.err.println(gxl_path_file);
        UndirectedGraph<Vertex, Edge> graph_JGJ = new SimpleGraph(Edge.class);
        int node_id=1;
        int diff=-10;
        try {
          //  System.err.println(gxl_path_file);
            File gxlFile = new File(gxl_path_file);

            GXLDocument gxlDocument = new GXLDocument(gxlFile);


            GXLGraph graph_GXL = gxlDocument.getDocumentElement().getGraphAt(0);
            GXLNode gxlNode;
            GXLEdge gxlEdge;
            GXLAttr gxlAttr;
            GXLInt gxlInt;
            GXLString gxlString;
            GXLFloat gxlFloat;

            int nodeId;
            int nodeValue_1;
            int nodeValue_2;
            String nodeValue_3;
            String nodeValue_1_2_3;
            int nodeValueHash;

            int edgeValue_1;
            String edgeValue_2;
            String edgeValue_3;
            String edgeValue_1_2_3;
            int edgeValueHash;

            int nb_element = graph_GXL.getGraphElementCount();

            //int nbNode=(int) Math.ceil((0.75)*(nb_element)); // on supose que le nombre de nodes est de 3/4 de toutes les elemeents
            //ArrayList<Vertex> arrayList = new ArrayList<Vertex>(nbNode);

            int nbNode = nb_element; // we supose that all element are node, because here we can't risk, unless we find a fast methode to know the number of nodes

            Vertex[] arry_ref_vertex = new Vertex[nbNode + 1]; // +1 , beacause Node ID begin from 1. so to not each time do (nodeID-1)


            for (int i = 0; i < nb_element; i++) {
                GXLElement graphElement = graph_GXL.getGraphElementAt(i);

                if (graphElement instanceof GXLNode) {
                    gxlNode = ((GXLNode) graphElement);
                    nodeId = node_id;
                    int true_id=Integer.parseInt(gxlNode.getID());
                    if(diff==-10)diff=node_id-true_id;
                    node_id++;
                    gxlAttr = gxlNode.getAttrAt(0);
                    gxlInt = (GXLInt) gxlAttr.getChildAt(0);
                    nodeValue_1 = gxlInt.getIntValue();

                    gxlAttr = gxlNode.getAttrAt(1);
                    gxlInt = (GXLInt) gxlAttr.getChildAt(0);
                    nodeValue_2 = gxlInt.getIntValue();

                    gxlAttr = gxlNode.getAttrAt(2);
                    gxlString = (GXLString) gxlAttr.getChildAt(0);
                    nodeValue_3 = gxlString.getValue();

                    nodeValue_1_2_3 = nodeValue_1 + "_" + nodeValue_2 + "_" + nodeValue_3;

                    nodeValueHash = HashFunction.getHash(nodeValue_1_2_3);

                    Vertex v = new Vertex(nodeId, nodeValueHash);

                    graph_JGJ.addVertex(v);

                    arry_ref_vertex[v.getVertex_id()] = v;
                } else if (graphElement instanceof GXLEdge) {
                    gxlEdge = (GXLEdge) graphElement;

                /*System.out.println(" Edge : "+((GXLEdge) graphElement).getID()+
                        "| form: "+((GXLEdge) graphElement).getSourceID()+
                        "--> to : "+((GXLEdge) graphElement).getTargetID());*/

                    int nodeID_from = Integer.parseInt(((GXLEdge) graphElement).getSourceID())+diff;
                    int nodeID_to = Integer.parseInt(((GXLEdge) graphElement).getTargetID())+diff;

                    edgeValue_1 = ((GXLInt) (gxlEdge.getAttrAt(0).getChildAt(0))).getIntValue();
                    edgeValue_2 = ((GXLString) (gxlEdge.getAttrAt(1).getChildAt(0))).getValue();
                    edgeValue_3 = ((GXLString) (gxlEdge.getAttrAt(2).getChildAt(0))).getValue();

                    edgeValue_1_2_3 = edgeValue_1 + "_" + edgeValue_2 + "_" + edgeValue_3;

                    edgeValueHash = HashFunction.getHash(edgeValue_1_2_3);

                    if (arry_ref_vertex[nodeID_from] != null && arry_ref_vertex[nodeID_to] != null) {
                        Edge myEdge = graph_JGJ.addEdge(arry_ref_vertex[nodeID_from], arry_ref_vertex[nodeID_to]);
                        myEdge.setWeight(edgeValueHash);
                    }
                }
            }

        } catch (FileNotFoundException e) {
            e.printStackTrace();
        } catch (IOException e) {
            e.printStackTrace();
        } catch (SAXException e) {
            e.printStackTrace();
        }

        return graph_JGJ;
    }

}
