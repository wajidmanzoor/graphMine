// Working faster KMB CPU
/*
 * // For IJPP'22 paper at https://doi.org/10.1007/s10766-021-00723-0.
 *
 * // For compiling
 * g++ -Wall -o "2approxCpu2.out" "2approxCpu2.cpp" -O3
 *
 * // Authors
 * Rajesh Pandian M | https://mrprajesh.co.in
 * Rupesh Nasre     | www.cse.iitm.ac.in/~rupesh
 * N.S.Narayanaswamy| www.cse.iitm.ac.in/~swamy
 *
 * MIT LICENSE
 *
 */
#include <algorithm>
#include <iostream>
#include <map>
#include <stack>
#include <sstream>
#include <climits>
#include <vector>
#include <unordered_map>
#include <set>
#include <signal.h>

#include <chrono>


volatile sig_atomic_t gSignalStatus = 0;

#define LEVEL  0 //	 1 -- print all
				//	 0 -- submission level
#define DEBUG if(LEVEL)
#define INIT -1
#define SHIFT 1

using namespace std;
class Edge {

public:
	int to;
	int length;

	Edge(){}
	~Edge(){}
	Edge(int t, int l){
		to = t; length = l;
	}
	bool operator < (const Edge& e){
		return length < e.length;
	}
};
class Arg{
public:
	bool isEdgesToPrint;

	Arg(){
		isEdgesToPrint= false;
	}

	Arg(int options){
		switch(options){
			case 1:
				isEdgesToPrint = true;
		}
	}

	~Arg(){}

};

Arg arg;
void printAdjList(const vector< vector<Edge> > &graph){
	int i = 0;
	for (auto vec : graph){

		cout << i << ": ";
		for(auto e : vec){
			cout<< e.to << " ";
		}
		i++;
		cout << endl;
	}
}

void printEdgeList(const vector< vector<Edge> > &graph, bool withWeight=false, bool isViz= false){
	for(int i=0, endI = graph.size(); i < endI; i++){
		for(int j=0, endJ = graph[i].size(); j < endJ; j++){
			if(i < graph[i][j].to){
			//~ cout << i << " -- "<< e.to << ": " << e.length << endl;
				if(withWeight){
					cout << i << " "<< graph[i][j].to << " : " << graph[i][j].length <<  endl;
				}else if(isViz){
					cout << i << " -- "<< graph[i][j].to << "[label=" << graph[i][j].length << ",weight="<<  graph[i][j].length << ",color=red, penwidth=2]" <<  endl;
				}else {
					cout << i << " "<< graph[i][j].to <<  endl;
				}
			}
		}
	}

}

int getGraphWeight(const vector< vector<Edge> > &graph){
	int mstVal =0;

	for(int i=0, endI = graph.size(); i < endI; i++){
		for(int j=0, endJ = graph[i].size(); j < endJ; j++){
			if(i < graph[i][j].to)
				mstVal += graph[i][j].length;
		}
	}

	return mstVal;
}


// It returns dist of src to target wt and its path vertices as vector!
pair<int, vector<int>>  dijkstra_misof_path(
	const vector< vector<Edge> > &graph,
	int source,
	int target,
//	vector<int>& min_distance,
	vector <int> terminals,
	set<int> &nextVertSet,
	set<pair<int,int> > &nextEdgeSet //isit used?
	) {


	vector <int>pathVertices;
	int gSize = graph.size();
	vector<int> parent(gSize , INIT);

    vector<int> min_distance(gSize, INT_MAX );
    min_distance[ source ] = 0;
    set< pair<int,int> > active_vertices;
    active_vertices.insert( {0,source} );

    while (!active_vertices.empty()) {
        int where = active_vertices.begin()->second;
        if (where == target) {
			DEBUG cout << source <<"--"<< target << "["<< min_distance[where]
				 <<"]: " <<where << "~";
				pathVertices.push_back(where);
				int tarVertex = where; // temp of target Vertex to traverse
				while(tarVertex!=source) { // parent[tarVertex] != -1
					nextVertSet.insert(parent[tarVertex]);

					if(tarVertex<parent[tarVertex]) // OPT for storing one time.
						nextEdgeSet.insert(make_pair(tarVertex,parent[tarVertex]));
					else
						nextEdgeSet.insert(make_pair(parent[tarVertex],tarVertex));
					DEBUG cout << parent[tarVertex] << "~" ;
					pathVertices.push_back(parent[tarVertex]);
					tarVertex=parent[tarVertex];
					//~ cout << parent[tarVertex] << "~~|";

				}
				DEBUG cout << endl;
				return make_pair(min_distance[where], pathVertices);
			//~ return make_pair(min_distance[where], parent);
		}
        active_vertices.erase( active_vertices.begin() );
        for (auto ed : graph[where])
            if (min_distance[ed.to] > min_distance[where] + ed.length) {
                active_vertices.erase( { min_distance[ed.to], ed.to } );
                min_distance[ed.to] = min_distance[where] + ed.length;
                parent[ed.to] = where;
                active_vertices.insert( { min_distance[ed.to], ed.to } );
            }
    }
    //~ return INT_MAX;
    //~ return make_pair(INT_MAX,parent);
    return make_pair(INT_MAX,pathVertices);
}
// takes is only graph and spits out the edges as pair
// simple and fast comparaed to compstructing graph
// CONS: Need to compute weight
vector < pair<int,int>>
PrimsAlgoEdge(vector<vector<Edge>> & graph, int src){
	int N = graph.size(); // it is one more than actual nodes in G in case if V={1,..N}
	vector<vector<Edge>> nG(N);
	vector <int> key(N, INT_MAX);
	vector <int> toEdges(N, INIT );
	vector <bool> visited(N, false);

	DEBUG cout << "In Prims "<< endl;

	set< pair<int, int> > active; // holds value and vertex
	set< pair <int, int> > treeEdges;

	//~ key[0] = INT_MAX;
	//~ visited[0] = true;

	key[src] = 0;
	active.insert( { 0, src});

	while(active.size()>0 ){
		auto where = active.begin()->second;

		DEBUG cout << "picked " << where <<"\tsize"<< active.size()<< endl;
		active.erase(active.begin());
		if(visited[where]) {
			continue;
		}
		visited[where] = true;
		for(Edge E : graph[where]){
			if(!visited[E.to] && E.length < key[E.to]){ //W[{where,E.to}]
				key[E.to] = E.length; //W[{where,E.to}]
				active.insert( { key[E.to], E.to});
				DEBUG cout << key[E.to] <<" ~ " <<  E.to << endl;
				toEdges[E.to]=where;
			}
		}
	}

	vector < pair<int,int>> edges;
	int u=0;
	for(auto v : toEdges){ // nice parallel code or made to parallel
		if(v != INIT ){
			//~ int w = W[{u,v}];
			//~ nG[u].push_back(Edge(v,w));
			//~ nG[v].push_back(Edge(u,w));
			edges.push_back(make_pair(u,v));
			edges.push_back(make_pair(v,u));
		}
		u++;
	}
	//~ return nG;
	return edges;
}

vector<vector<Edge>>
//~ vector < pair<int,int>>

PrimsAlgo(vector<vector<Edge>> & graph, map<pair<int,int> , int> W, int src){
	int N = graph.size(); // it is one more than actual nodes in G in case if V={1,..N}
	vector<vector<Edge>> nG(N);
	vector <int> key(N, INT_MAX);
	vector <int> toEdges(N, INIT );
	vector <bool> visited(N, false);

	set< pair<int, int> > active; // holds value and vertex
	set< pair <int, int> > treeEdges;

	key[0] = INT_MAX;
	visited[0] = true;

	key[src] = 0;
	active.insert( { 0, src});

	while(active.size()>0 ){
		auto where = active.begin()->second;

		DEBUG cout << "picked " << where <<"\tsize"<< active.size()<< endl;
		active.erase(active.begin());
		if(visited[where]) {
			continue;
		}
		visited[where] = true;
		for(Edge E : graph[where]){
			if(!visited[E.to] && E.length < key[E.to]){ //W[{where,E.to}]
				key[E.to] = E.length; //W[{where,E.to}]
				active.insert( { key[E.to], E.to});
				DEBUG cout << key[E.to] <<" ~ " <<  E.to << endl;
				toEdges[E.to]=where;
			}
		}
	}

	vector < pair<int,int>> edges;
	int u=0;
	for(auto v : toEdges){ // nice parallel code or made to parallel
		if(v != INIT ){
			int w = W[{u,v}];
			nG[u].push_back(Edge(v,w));
			nG[v].push_back(Edge(u,w));
			edges.push_back(make_pair(u,v));
		}
		u++;
	}
	return nG;
}



vector< vector<Edge> >minG;
int minMSTVal = INT_MAX;
void handleSignal(int signalNum) {
	gSignalStatus = signalNum;
    if (signalNum == SIGINT || signalNum == SIGTERM) {
        DEBUG cout << "Received SIGTERM!\n";
		cout <<"VALUE " << minMSTVal << endl;
		printEdgeList(minG , false,false);
        exit(1);
    }

}


void  ConstructGraphs(

	const vector<vector<Edge>> &T, // This is the MST
	const map<pair<int,int>, int> &W, // This is W of G
	const map<pair<int,int>, vector<int>> &WPath ,
	const unordered_map<int,int> &reMapT,
	const  vector <int> &terminals,
	vector<vector<Edge>> &nG,
	map<pair<int,int>, int>   &nW
	){

	DEBUG cout << "in Construct Graph" << endl;

	//G is MST of G' here.
	//Remap using remapT the vertex ids of G
	//collect the vertex id of the path
	DEBUG cout << "printing reMap"<<endl;
	DEBUG
	for(auto &a : reMapT)
		cout << a.first << "--" << a.second << endl;
	//~ cout <<"*"<< reMapT.at(40) <<endl; // This works! yay :)

	// Declaration G"
	// new V set and new V vector
	set<int> nVS;
	set<pair<int,int>> nE;

	for(int i=0, endI = T.size(); i < endI; i++){
		for(int j=0, endJ = T[i].size(); j < endJ; j++){
			int v = T[i][j].to;
			int x = -1;
			int y = -1;
			if(i < v) {
				x = terminals[i-1];
				y = terminals[v-1];

				DEBUG cout << x << "===" <<  y << ": \n" ;
				const vector<int> &aVec = WPath.at({x,y});
				int count=0, oldV=-1;
				//~ for(auto &a: aVec )
					//~ cout << olda << ", ";
				/// Constructing the edge list using vertices
				for(auto a: aVec ){
					++count;
					if(count == 1){ // first vertex in vector
						oldV = a;
						continue;
					}
					if(oldV < a)
						nE.insert(make_pair(oldV,a));
					else
						nE.insert(make_pair(a,oldV));
					DEBUG cout << "\t"<< oldV << " -- " << a << endl;
					oldV = a;

				}
				DEBUG cout << endl;

				nVS.insert(aVec.begin(), aVec.end());
				/// appending the vertices to the list
			}
		}
	}

	vector<int> nVV(nVS.begin(), nVS.end());
	//~ int NN = (int)nVS.size();
	//~ int MM = (int)nE.size();
	//~ printf(" %s\n", (NN-1==MM?"TRUE":"FALSE"));
	//~ printf("|nVS|:%d |nE|=%d %s\n", NN, MM, (NN-1==MM?"TRUE":"FALSE"));
	//~ exit(0);

	map<int,int> nGMap;
	DEBUG cout << "Vertices!"<< endl;
	int count =0;
	for (auto &a : nVS){
		DEBUG printf("VS[%d]=%d\n",count, a);
		nGMap.insert(make_pair(a,count));
		count++;
	}

	DEBUG cout << "Edges!"<< endl;

	nG.resize(nVS.size() );

	DEBUG cout <<"Done resize!" << endl;

	for (auto &a : nE){
		//~ cout << a.first << "--" << a.second<< endl;
		int w = W.at(make_pair(a.first,a.second));
		int p = nGMap[a.first] ;
		int q = nGMap[a.second];


		DEBUG cout << a.first << "--" << a.second<< endl;
		//~ cout << "\t"<< p<< "--" << q<< endl;
		nG[p ].push_back(Edge(q, w));
		nG[q ].push_back(Edge(p, w));
	}
	DEBUG
	for(auto a: nGMap){
		printf("reMap[%d]=%d\n" , a.first, a.second);
	}
	//~ printAdjList(nG);

	//! if((int)nVS.size() == (int)nE.size()-1)
    //! printf("Tree Already\n");
  //! return;
	auto es = PrimsAlgoEdge(nG ,1); // 1 is source // IAM NOT A BLE TO DEBUG FOR 0
	int mstVal = 0;
  for(auto &e: es){
      int s = e.first;
      int t = e.second;

      if(s>=t) continue;
      int u = nVV[s];
      int v = nVV[t];
      int w = W.at(make_pair(u,v));
      //~ printf("%d, %d ==", s, t);
      //~ printf("%d == %d :%d  \n", u, v, w);

      //~ Commenting for output
      //~ printf("%d %d %d \n", u, v,w);
      mstVal += w;
    }


	//~ cout <<mstVal ;
	cout << "VALUE "<<mstVal << endl;

	//DEBUG
  if(arg.isEdgesToPrint){
    for(auto &e: es){
      int s = e.first;
      int t = e.second;

      if(s>=t) continue;
      int u = nVV[s];
      int v = nVV[t];

      //~ printf("%d, %d ==", s, t);
      printf("%d %d \n", u ,v );

    }
  }
	//~ for (auto a : W)
		//~ printf("%d -- %d : %d\n", a.first.first, a.first.second, a.second);


}

void TwoApproxAlgo(const vector< vector<Edge> > &graph,
					const map<pair<int,int> , int> &W,
					const  vector <int> &terminals){

	set<int> nextVertSet(terminals.begin(), terminals.end());
	set<pair<int,int>> nextEdgeSet;
	map<pair<int,int> , int> WD;
	map<pair<int,int> , vector<int>> WPath;
	// computation of all pairs	 of terminals
	int len =0;
	for(auto u : terminals){
		for(auto v : terminals){
			if(u >= v) // cutting short the repeated computations
				continue;
			auto pair = dijkstra_misof_path(graph, u, v, terminals, nextVertSet, nextEdgeSet) ;

			int w = pair.first;

			WD[make_pair(u,v)]=w;
			WD[make_pair(v,u)]=w;

			WPath[make_pair(v,u)] = pair.second;
			WPath[make_pair(u,v)] = pair.second;
			int val = pair.second.size();
			//~ cout << u << " "<< v << ":" << val <<endl;
			len +=val;
		}
	}
	//~ cout <<len << endl;
	unordered_map<int,int> reMapT;

	for(int i=0, end =terminals.size(); i< end;i++){
		reMapT[terminals[i]]=i;
		DEBUG printf("T[%d]=%d \n", i, terminals[i]);
	}

	DEBUG
	for(auto a : reMapT){
		printf("MapT[%d]=%d \n", a.first, a.second);
	}

	DEBUG
	for (auto& x: WD) {
		int u = x.first.first;
		int v = x.first.second;
		int w = x.second;

		if(u < v)
			printf("Map[%d-%d]=%d\n",u,v,w);
			//cout << u << "-"<<v << ":"<< w << endl;
	}

	vector< vector<Edge> > nG(terminals.size() + 1);

	for (int i=1, end = terminals.size(); i <= end; i++ ){ // 1 to t
		for(int j=1 ; j <= end; j++){
			if(j==i)
				continue;

			int w = WD[{terminals[i-1],terminals[j-1]}];
			nG[i].push_back(Edge(j,w));
		}
	}
	DEBUG
	cout << "Testing WD MAP"<<endl;
	DEBUG
	for(auto &a : WD){
		printf("%d--%d: %d\n", a.first.first, a.first.second, a.second );
	}
	DEBUG printAdjList(nG);
	DEBUG printEdgeList(nG,true);
	auto Td=PrimsAlgo(nG,WD,1);

	//~ cout<< "TEST G'" << getGraphWeight(Td)<< endl;

	vector< vector<Edge> > Gdd;
	map<pair<int,int> , int> Wdd;
	// Get the vertices in the path
	//Reconstruct the graph with [0-n) vertices
	ConstructGraphs(Td, W, WPath, reMapT, terminals,Gdd, Wdd);
	//~ cout <<"Len :" << WD.at({1,47})<< endl;

	// Final MST on  the G"
	//~ auto Tdd = PrimsAlgo(Gdd,WD,1);

}

pair< vector<int>, vector<int>>
dijkstra(const vector< vector<Edge> > &graph, int source,
	vector<int>& parent,
	vector<int>& min_distance,
	vector <int> terminals) {

	min_distance[ source ] = 0;
	set< pair<int,int> > active_vertices;
	active_vertices.insert( {0,source} );
	set <int> terminalsSet(terminals.begin(), terminals.end());
	while (!active_vertices.empty() && terminalsSet.size()>0) {
		int where = active_vertices.begin()->second;

		terminalsSet.erase(where);

		active_vertices.erase( active_vertices.begin() );

		for (auto ed : graph[where]) {
			auto newdist = min_distance[where] + ed.length;
			if (newdist < min_distance[ed.to]) {
				active_vertices.erase( { min_distance[ed.to], ed.to } );
				min_distance[ed.to] = newdist;
				parent[ed.to] = where;
				active_vertices.insert( { newdist, ed.to } );
			}
		}
	}

	return {parent,min_distance};
}


void TwoApproxAlgoFast(const vector< vector<Edge> > &graph,
					const map<pair<int,int> , int> &W,
					const  vector <int> &terminals){

	set<int> nextVertSet(terminals.begin(), terminals.end());
	set<pair<int,int>> nextEdgeSet;
	map<pair<int,int> , int> WD;
	map<pair<int,int> , vector<int>> WPath;
	// computation of SSSP from all of terminals


	for(auto u : terminals){
		int gSize = graph.size();
		vector<int> min_distance(gSize, INT_MAX);
		vector<int> parent(gSize, INIT);

		auto pair = dijkstra(graph, u,parent,min_distance, terminals) ;
		DEBUG cout << "SSSP on" << u <<endl;
		for(auto v : terminals) {
			if(u >= v) continue; // shortcuts the unneccassary computation as G is undirected!
			DEBUG cout << "\tto " << v << endl;

			int p =v;
			vector<int> path;
			path.push_back(v);
			while(parent[p] != INIT){
				path.push_back(parent[p]);
				p = parent[p];
			}

			int w = min_distance[v];

			WD[make_pair(u,v)]=w;
			WD[make_pair(v,u)]=w;

			WPath[make_pair(v,u)] = path;
			WPath[make_pair(u,v)] = path;
			DEBUG {
				cout << "WPATH(" <<u <<","<< v<<"): " ;
				for(auto a: path)
					cout << a << " ";
				cout << endl;
			}
		}

	}
	//~ cout << "SSSP DONE"<<endl;

	// Upto this point
	// Both the WD and WPath must be populated!
	unordered_map<int,int> reMapT;

	DEBUG cout << "SSSP DONE"<<endl;

	for(int i=0, end =terminals.size(); i< end;i++){
		reMapT[terminals[i]]=i;
		DEBUG printf("T[%d]=%d \n", i, terminals[i]);
	}

	DEBUG
	for(auto a : reMapT){
		printf("MapT[%d]=%d \n", a.first, a.second);
	}

	DEBUG
	for (auto& x: WD) {
		int u = x.first.first;
		int v = x.first.second;
		int w = x.second;

		if(u < v)
			printf("Map[%d-%d]=%d\n",u,v,w);
			//cout << u << "-"<<v << ":"<< w << endl;
	}

	vector< vector<Edge> > nG(terminals.size() + 1);

	for (int i=1, end = terminals.size(); i <= end; i++ ){ // 1 to t
		for(int j=1 ; j <= end; j++){
			if(j==i)
				continue;

			int w = WD[{terminals[i-1],terminals[j-1]}];
			nG[i].push_back(Edge(j,w));
		}
	}
	DEBUG
	cout << "Testing WD MAP"<<endl;
	DEBUG
	for(auto &a : WD){
		printf("%d--%d: %d\n", a.first.first, a.first.second, a.second );
	}
	DEBUG printAdjList(nG);
	DEBUG printEdgeList(nG,true);
	auto Td=PrimsAlgo(nG,WD,1);

	//~ cout<< "TEST G'" << getGraphWeight(Td)<< endl;

	vector< vector<Edge> > Gdd;
	map<pair<int,int> , int> Wdd;
	// Get the vertices in the path
	//Reconstruct the graph with [0-n) vertices
	ConstructGraphs(Td, W, WPath, reMapT, terminals,Gdd, Wdd);
	//~ cout <<"Len :" << WD.at({1,47})<< endl;

	// Final MST on  the G"
	//~ auto Tdd = PrimsAlgo(Gdd,WD,1);

}
int main(int argc, char **argv){
  if(argc > 1){
		arg.isEdgesToPrint = true;
    DEBUG cout << "ARG SET" << endl;
	}

	vector< vector<Edge> > graph;
	map<pair<int,int> , int> W;
	vector <int> terminals;
	string code, type, dummy;

	while( cin>> code >> type ){
		transform(code.begin(), code.end(), code.begin(), ::toupper);

		if(code == "SECTION" && type =="Graph"){
			long m, n;
			long u, v, w;
			cin >> dummy >> n;
			cin >> dummy >> m;

			//~ cout <<"n="<< n <<";"<< "m="<<m << endl;
			//graph= new Graph(n,true);
			graph.resize(n+1); // coz graph has from index 0. where as challege its 1
			for(long i=0; i < m; i++){
				cin>> dummy >> u >> v >> w;
				graph[u].push_back(Edge(v,w));
				graph[v].push_back(Edge(u,w));
				W[make_pair(u,v)]=w;
				W[make_pair(v,u)]=w;
				//~ cout << u<< " -- "<< v << " :"<< w << endl;
			}
			cin >> dummy;
		}
		else if(code == "SECTION" && type =="Terminals"){
			long t, u;
			cin >> dummy >> t;
			for(long i=0; i < t; i++){
				cin>> dummy >> u;
				//cout << "T " << u << endl;
				terminals.push_back(u);
			}
			cin >> dummy;
		}
		else if(code == "SECTION" && type =="Tree"){
			// This for TRACK B - it is incomplete!
			cin >> dummy >> dummy >> dummy;
			long b, val ; cin >> b;

			cin >> dummy >> dummy >> ws;

			for(long i=0; i < b; i++){
				string line;
				getline(cin, line); stringstream sstream(line);
				if(sstream >> dummy, dummy=="b"){
					while(sstream >> val){
						//cout << val << " " ;
					}
					//cout << endl;
				}
			}
			long tu, tv;
			for(long i=0; i < b-1; i++){ // b-1 edges is Td
				cin >>  tu >> tv;
				//cout<<  tu << " " << tv << endl;
			}
			cin >> dummy; // end
		}
		else{
			cout << "INVALID FORMAT\nErr in INPUT: "<< code << endl;


			exit(1);
		}

	}
	using namespace std::chrono;
	time_point<system_clock> start, end;
	start = system_clock::now();

	//~ TwoApproxAlgo(graph,W,terminals);
	DEBUG cout << "READ!"<<endl;
	TwoApproxAlgoFast(graph,W,terminals);

	//~ auto mst = PrimsAlgo(graph, W, 1);
	//~ cout << getGraphWeight(mst) ;
	end = system_clock::now();

	duration<double> timespent = end - start;
	cout  << "TIME "<<timespent.count()*1000 << endl; // retuns in us ; converted to ms
	//	cout << getGraphWeight(graph) ;
	//~ printAdjList(graph);
	//! printEdgeList(minG , false,false);
	return 0;
}

