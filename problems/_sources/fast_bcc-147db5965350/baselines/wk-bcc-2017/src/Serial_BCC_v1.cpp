#include<iostream>
#include<fstream>
#include<vector>
#include<chrono>
#include<stack>
#include<algorithm>
#include<climits>
#include<queue>
#include<string>
#include <filesystem>

// #define DEBUG 1

using namespace std;

string filename_without_extension(const std::string& str) {
	std::filesystem::path file_path(str);

     // Extracting filename without extension
    std::string filename = file_path.stem().string();
    std::cout << "Filename without extension: " << filename << std::endl;

    return filename;
}

/* Graph functions */

class unweightedGraph
{
public:
	int totalVertices, totalEdges, *offset, *neighbour, *degree;

public:
	// Graph();
	unweightedGraph(ifstream& edgeList);
	void printCSR();
};

unweightedGraph::unweightedGraph(ifstream& edgeList)
{
	// cout << "reached in unweightedGraph" << endl;
	edgeList >> totalVertices >> totalEdges;
	offset = new int[totalVertices + 1];
	degree = new int[totalVertices]();
	neighbour = new int[totalEdges];

	// storing the directed edges and calculating the degree
	int *U = new int[totalEdges];
	int *V = new int[totalEdges];
	for (int i = 0; i < totalEdges; i++)
	{
		int u, v;
		edgeList >> u >> v;

		degree[u]++;

		U[i] = u;
		V[i] = v;
	}

	// updating the offset array
	vector<int> edgeCounter(totalVertices);
	offset[0] = 0;
	for (int i = 0; i < totalVertices; i++)
	{
		offset[i + 1] = degree[i] + offset[i];
		edgeCounter[i] = offset[i];
	}

	// updating the neighbour array
	for (int i = 0; i < totalEdges; i++)
	{
		int u, v;
		u = U[i];
		v = V[i];

		int currIndex = edgeCounter[u];
		edgeCounter[u]++;
		neighbour[currIndex] = v;
	}

	delete[] U;
	delete[] V;

}

void unweightedGraph::printCSR()
{
	cout << "Total Edges = " << totalEdges << endl;
	cout << "Total Vertices = " << totalVertices << endl;
	for (int i = 0; i < totalVertices; i++)
	{
		int u = i;
		cout << "Vertex " << u << " -> { ";
		for (int j = offset[i]; j < offset[i + 1]; j++)
		{
			int v = neighbour[j];
			cout << "( " << u << "," << v << ")";
			cout << ", ";
		}
		cout << "}" << endl;
	}
}

/* Timer */

class mytimer {
	decltype(chrono::high_resolution_clock::now()) tstart, tend;
public:
	mytimer() {
		tstart = chrono::high_resolution_clock::now();
	}

	void timetaken() {
		tend = chrono::high_resolution_clock::now();
		auto dur = chrono::duration_cast<chrono::nanoseconds>(tend - tstart);
		cout << "\n\tTime taken ------ " <<
			dur.count() / ((long long)1000 * 1000 * 1000 * 60) << " min  " <<
			(dur.count() / ((long long)1000 * 1000 * 1000)) % 60 << " sec  " <<
			(dur.count() / (1000 * 1000)) % 1000 << " ms  " <<
			(dur.count() / 1000) % 1000 << " us  " <<
			dur.count() % 1000 << " ns\n";
	}

	void timetaken(string s) {
		tend = chrono::high_resolution_clock::now();
		auto dur = chrono::duration_cast<chrono::nanoseconds>(tend - tstart);
		cout << "\n\tTime taken for " << s << " is ------ " <<
			dur.count() / ((long long)1000 * 1000 * 1000 * 60) << " min  " <<
			(dur.count() / ((long long)1000 * 1000 * 1000)) % 60 << " sec  " <<
			(dur.count() / (1000 * 1000)) % 1000 << " ms  " <<
			(dur.count() / 1000) % 1000 << " us  " <<
			dur.count() % 1000 << " ns\n";
	}

	void timetaken_ns(string s) {
		tend = chrono::high_resolution_clock::now();
		auto dur = chrono::duration_cast<chrono::nanoseconds>(tend - tstart);
		cout << "\n\tTime taken for " << s <<  " is ------ " << dur.count() << " ns => " <<
			dur.count() / ((long long)1000 * 1000 * 1000 * 60) << " min  " <<
			(dur.count() / ((long long)1000 * 1000 * 1000)) % 60 << " sec  " <<
			(dur.count() / (1000 * 1000)) % 1000 << " ms  " <<
			(dur.count() / 1000) % 1000 << " us  " <<
			dur.count() % 1000 << " ns\n";
	}

	void timetaken_reset(string s) {
		tend = chrono::high_resolution_clock::now();
		auto dur = chrono::duration_cast<chrono::nanoseconds>(tend - tstart);
		cout << "\n\tTime taken for " << s << " is ------ " <<
			dur.count() / ((long long)1000 * 1000 * 1000 * 60) << " min  " <<
			(dur.count() / ((long long)1000 * 1000 * 1000)) % 60 << " sec  " <<
			(dur.count() / (1000 * 1000)) % 1000 << " ms  " <<
			(dur.count() / 1000) % 1000 << " us  " <<
			dur.count() % 1000 << " ns\n";
		tstart = chrono::high_resolution_clock::now();
	}

	void reset() {
		tstart = chrono::high_resolution_clock::now();
	}
};

/* DS for DFS */

struct vertex_in_stack {
	int u, ind, parent;
};

struct edge {
	int u, v;
};

int main(int argc, char* argv[])
{

	mytimer total_exec_timer{};

	//cout << "file name is " << argv[1] << "\n";

	if (argc < 2) {
		cout << "Give the dataset path as an argument\n";
		exit(-1);
	}

	ifstream inputGraph;
	inputGraph.open(argv[1]);

	if (inputGraph.is_open() == false) {
		cout << argv[1] << " file does not exits\n";
		exit(-1);
	}

	cout << "\n=========================================================\n";
	cout << "\nserial bcc for the file " << argv[1] << " started\n";
	
	unweightedGraph G(inputGraph);

	//G.printCSR();

	mytimer algo_timer{};

	// tarjan's algo { iterative approach }

	// DS for iterarions and storing results
	stack<vertex_in_stack> vst;
	int prev_vertex = -1;
	int nchild = 0;
	//vector<bool> visited(G.totalVertices,false);
	vector<int> discovery_time(G.totalVertices, -1);
	vector<int> oldest_vertex(G.totalVertices, INT_MAX);
	int time = 0;
	stack<edge> est;
	int nbcc{}, nce{};
	queue<edge> cut_edges;
	vector<vector<edge>> bcc;

	// DS for cutvertex
	vector<int> cut_vertex(G.totalVertices, false);

	// initialization
	int root = 0;
	vst.push({ 0,0,-1 });

	while (vst.size()) {
		vertex_in_stack& vs = vst.top();

		int u = vs.u;
		int ind = vs.ind;
		int parent = vs.parent;

		// set the dis time
		if (discovery_time[u] == -1) {
			discovery_time[u] = ++time;
			oldest_vertex[u] = time;
		}

		int bccsize{};
		if (prev_vertex != -1) { // we backtracked
			oldest_vertex[u] = min(oldest_vertex[u], oldest_vertex[prev_vertex]);

			// check if prev_vertex makes u a cut vertex
			if (u != root && oldest_vertex[prev_vertex] >= discovery_time[u]) {
				cut_vertex[u] = true;

				// printing the bcc
				//cout << "\nBCC Comp\n";
				edge e;
				vector<edge> bcc_list;
				++nbcc;
				
				if (est.size() == 0) { // error checking
					cout << "est is zero but it shouldn't be\n";
					#ifdef DEBUG
					cout << "u and prev ver is - " << u << "\t" << prev_vertex << "\n";
					cout << "cutvertex status of u and prev_vertex - " << cut_vertex[u] << "\t" << cut_vertex[prev_vertex];
					#endif
					exit(-1);
				}

				do {
					++bccsize;
					e = est.top();
					edge e2 = e;
					if (e2.v < e2.u) {
						int t = e2.u;
						e2.u = e2.v;
						e2.v = t;
					}
					bcc_list.push_back(e2);
					est.pop();
					//cout << e.u << " " << e.v << "\n";
				} while (e.u != u || e.v != prev_vertex);
				
				bcc.push_back(bcc_list);

				if (est.size() == 0) { // error checking
					cout << "est is emptied by " << u << "\n";
					exit(-1);
				}
			}

			// check if the edge u - prev_vertex is cut edge
			if (oldest_vertex[prev_vertex] > discovery_time[u]) { //cout << "\n" << u << " " << prev_vertex << " is a cut edge\n";
				++nce;

				if (u < prev_vertex) cut_edges.push({ u,prev_vertex });
				else cut_edges.push({ prev_vertex,u });
				
				if ( (u != root && bccsize != 1) || (u == root && est.size()!=1) ) {
					cout << "we encountered a trivial bcc yet the stack contains more edges\n";
					exit(-1);
				}
			}

			// clear the backtrac info
			prev_vertex = -1;
		}


		/* now we are moving forward */

		int end_ind = G.offset[u + 1];

		// if we exhausted all neighbouring vertices
		if (ind == end_ind) {
			vst.pop();
			prev_vertex = u;
			if (u == root) { // for root special condition
				//cout << "\nprinting last root bcc\n";
				++nbcc;
				vector<edge> bcc_list;

				while (est.size()) {
					edge e = est.top();
					if (e.v < e.u) {
						int t = e.u;
						e.u = e.v;
						e.v = t;
					}
					bcc_list.push_back(e);
					est.pop();
					//cout << e.u << " " << e.v << "\n";
				}

				bcc.push_back(bcc_list);
			}
			continue;
		}

		int v = G.neighbour[ind];

		if (discovery_time[v] == -1) { // moving forward
			if (u == root) ++nchild;
			vertex_in_stack new_vs;
			new_vs.u = v;
			new_vs.ind = G.offset[v];
			new_vs.parent = u;
			if (u == root && nchild > 1) {
				cut_vertex[root] = true;
				//cout << "\nprinting root bcc\n";
				++nbcc;
				vector<edge> bcc_list;
				while(est.size()) {
					edge e = est.top();
					if (e.v < e.u) {
						int t = e.u;
						e.u = e.v;
						e.v = t;
					}
					bcc_list.push_back(e);
					est.pop();
					//cout << e.u << " " << e.v << "\n";
				}
				bcc.push_back(bcc_list);
			}
			vst.push(new_vs);
			est.push({ u,v }); // pushing onto edge stack
		}
		else if (v != parent && discovery_time[v] < discovery_time[u]) { // or else updating oldest_vertex info if it's a back edge ignoring parent
			oldest_vertex[u] = min(oldest_vertex[u], discovery_time[v]); // updating the old value
			est.push({ u,v });
		}
		vs.ind++;
	}

	algo_timer.timetaken_ns("the completion of the serial algo");

	string file_name = filename_without_extension(argv[1]);
	file_name += "_serial_result.txt";
	file_name = "output/" + file_name;
	cout << file_name << "\n";

	ofstream outfile(file_name, ios::out);

	if (outfile.is_open() == false) {
		cout << file_name << " can not be opened to write the results\n";
		exit(-1);
	}

	outfile << G.totalVertices << "\t" << G.totalEdges << "\n";
	
	// printing cut vertices
	outfile << "cut vertex status\n";
	int ncv{};
	for (int i = 0; i < G.totalVertices; ++i) {
		outfile << i << " " << cut_vertex[i] << "\n";
		if (cut_vertex[i]) ++ncv;
	}

	// printing cut edges

	outfile << "cut edge status\n";
	outfile << cut_edges.size() << "\n";
	while (cut_edges.size()) {
		outfile << cut_edges.front().u << " " << cut_edges.front().v << "\n";
		cut_edges.pop();
	}

	outfile << "Explicit BCC's\n";
	outfile << bcc.size() << "\n";
	for (int i = 0; i < bcc.size(); ++i) {
		outfile << i + 1 << " <-bcc_num|bcc_size-> " << bcc[i].size() << "\n";
		for (int l = 0; l < bcc[i].size(); ++l) {
			outfile << bcc[i][l].u << " " << bcc[i][l].v << "\n";
		}
		outfile << "\n";
	}

	outfile << ncv << "\t" << nce << "\t" << nbcc;

	cout << "\nno of cut vertices - " << ncv << "\n";
	cout << "\nno of cut edges - " << nce << "\n";
	cout << "\nno of bcc - " << nbcc << "\n";

	total_exec_timer.timetaken("entire program");

	cout << "\nserial bcc for the file " << argv[1] << " is completed\n";
	cout << "\n=========================================================\n";

	return 0;
}