//! .gr to harish's format
#include <algorithm>
#include <iostream>
#include <map>
#include <stack>
#include <sstream>
#include <climits>
#include <vector>
#include <set>
#include <signal.h>
#include <unistd.h>
#include <cstring>
#include <cmath>

volatile sig_atomic_t tle = 0;

#define LEVEL 0 // 1 - print all 0 -- submission level
#define DEBUG if(LEVEL)
#define LOCAL 0
#define TEST if(LOCAL)

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

void checkMST(vector<vector<Edge>> g, map<pair<int,int>,int> W, vector<vector<Edge>> mst);
vector<vector<Edge>> inducedSubgraph(vector<vector<Edge>> &graph, set<int> & steinerTreeV);
vector<vector<Edge>> PrimsAlgo(vector<vector<Edge>> & graph, map<pair<int,int> , int>& W, int src);
//~ void printEdgeList(const vector< vector<Edge> > &graph, bool withWeight=false, bool isViz= false);

int minCost = INT_MAX;
set<int> steinerTreeV;
vector< vector<Edge> > graph;
map<pair<int,int> , int> W;
map<pair<int,int> , set<pair<int,int>> > dSet;


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
void printTerminals(vector <int> & terminals){
	for(auto v : terminals){
		cout << v << "[shape=\"doublecircle\"]" << endl;
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



int main(int argc, char* argv[]){

    ios_base::sync_with_stdio(false);

	vector<vector<int>> tdEdge;
	vector<vector<int>> tdBag;
	vector <int> terminals;
	set <int> terminalSet;
	string code, type, dummy;
	int N;
	int M;
	while( cin>> code >> type ){
		transform(code.begin(), code.end(), code.begin(), ::toupper);
		if(code == "SECTION" && type =="Graph"){
			long m, n;
			long u, v, w;
			cin >> dummy >> n;
			cin >> dummy >> m;
			N = n+1;
			M = m;
			graph.resize(N); // coz graph has from index 0. where as challege its 1
			for(long i=0; i < m; i++){
				cin>> dummy >> u >> v >> w;
				graph[u].push_back(Edge(v,w));
				graph[v].push_back(Edge(u,w));
				W[make_pair(u,v)]=w;
				W[make_pair(v,u)]=w;
			}
			cin >> dummy >> ws;
		}
		else if(code == "SECTION" && type =="Terminals"){
			long t, u;
			cin >> dummy >> t;
			for(long i=0; i < t; i++){
				cin>> dummy >> u;
				terminals.push_back(u);
				terminalSet.insert(terminalSet.end(), u);
			}
			cin >> dummy >> ws;
		}
		else if(code == "SECTION" && type =="Tree"){

			cin >> dummy >> ws; // DECOMP
			cin >> dummy >> dummy; // s ,td
			long bags, bid, val ;
			cin >> bags; // total bags
			tdEdge.resize(bags+1);
			tdBag.resize(bags+1);
			cin >> dummy >> dummy >> ws; // tw, n

			for(long i=0; i < bags; i++){
				string line;
				getline(cin, line); stringstream sstream(line);
				if(sstream >> dummy, dummy=="b"){
					sstream >> bid; // bag id
					//~ cout << bid << ": ";
					while(sstream >> val){
						//~ cout << val << " " ;
						tdBag[bid].push_back(val);
					}
					//~ cout << endl;
				}
			}
			long tu, tv;
			for(long i=1; i < bags; i++){ // b-1 edges is Td
				cin >>  tu >> tv;
				//~ cout<<  tu << " " << tv << endl;
				tdEdge[tu].push_back(tv);
				tdEdge[tv].push_back(tu);
			}
			cin >> dummy >> ws; // END
			cin >> dummy >> ws; // eof

		}
		else{
			cout << "Err in Input/Parsing! " << code << endl;
			exit(1);
		}

	}
	cout << N-1 << endl;
	int count =0;
	for(int i=1, endI = graph.size(); i < endI; i++){
		int size = graph[i].size();
		cout << count<< " "<<  size <<endl;
		count+=size;
	}
	cout << "\n0\n";
	cout << M*2 << endl;
	for(int i=1, endI = graph.size(); i < endI; i++){
		for(int j=0, endJ = graph[i].size(); j < endJ; j++){
			cout << graph[i][j].to-1 << " " << graph[i][j].length <<" "; // note the -1 to ensure {0,...,n-1}
		}
	}
	cout << endl;

	cout << terminalSet.size() << endl;
	for (auto i : terminalSet){
		cout << i-1 << " ";
	}
	cout << endl;
	return 0;
}

