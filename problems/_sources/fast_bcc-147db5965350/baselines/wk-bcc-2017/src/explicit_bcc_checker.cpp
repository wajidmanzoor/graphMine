#include<iostream>
#include<fstream>
#include<vector>
#include<string>
#include<unordered_set>
#include<unordered_map>

using namespace std;

// #define debug 1

int main(int argc, char* argv[]) {

	if(argc < 3) {
		std::cerr << argv[0] <<" <serial_output> <parallel_output>\n";
		exit(0);
	}

	fstream f1(argv[1], fstream::in);
	fstream f2(argv[2], fstream::in);

	if (!(f1.is_open())) {
		cout << argv[1] << " can not be opened\n";
		exit(-1);
	}

	if (!(f2.is_open())) {
		cout << argv[2] << " can not be opened\n";
		exit(-1);
	}

	int no_of_vertices, no_of_edges;
	int no_of_vertices1, no_of_edges1;

	f1 >> no_of_vertices >> no_of_edges;
	f2 >> no_of_vertices1;

#ifdef debug
	cout << "no of vertices are compared\n";
#endif

	if (no_of_vertices1 != no_of_vertices) {
		cout << "vertices are not same\n";
		exit(-1);
	}

	vector<int> cut_vertex_status(no_of_vertices), cut_vertex_status1(no_of_vertices);

	string s;
	getline(f1, s);
	getline(f1, s);
	getline(f2, s);
	getline(f2, s);

#ifdef debug
	cout << "string is read\n";
#endif

	int ind;

	for (int i = 0; i < no_of_vertices; ++i) f1 >> ind >> cut_vertex_status[i];
#ifdef debug
		cout << "cv status is read from " << argv[1] << "\n";
#endif
	for (int i = 0; i < no_of_vertices; ++i) f2 >> ind >> cut_vertex_status1[i];
#ifdef debug
		cout << "cv status is read from " << argv[2] << "\n";
#endif

	for (int i = 0; i < no_of_vertices; ++i) {
		if (cut_vertex_status1[i] != cut_vertex_status[i]) {
			cout << "cut vertex status is different for vertex " << i << "\n";
			exit(-1);
		}
	}

	//cut_vertex_status.clear();
	//cut_vertex_status1.clear();

#ifdef debug
	cout << "vertices status compared\n";
#endif

	getline(f1, s);
	getline(f1, s);
	//getline(f2, s);
	//getline(f2, s);

#ifdef debug
	cout << "string is read\n";
#endif

	no_of_edges /= 2;

	int cut_edge_size;
	f1 >> cut_edge_size;

	//unordered_set<long long int> emap;

	for (int i = 0; i < cut_edge_size; ++i) {
		int u, v;
		f1 >> u >> v;
		//if (status) emap.insert((u << 32) + v);
	}


#ifdef debug
	cout << "edges status compared\n";
#endif

	getline(f1, s);
	getline(f1, s);
	getline(f2, s);
	getline(f2, s);

	// read from the pbcc output

	int ne2;
	f2 >> ne2;

	if(ne2 != no_of_edges){
		cout << "The number of edges are not matching " << no_of_edges << " " << ne2 << "\n";
		exit(-1);
	}

	unordered_map<long long int, int> e_bcc_no_in_parallel;

	for (int i = 0; i < no_of_edges; ++i) {
		long long int u, v;
		int num;
		char c;
		f2 >> u >> c >> v >> c >> c >> num;
		e_bcc_no_in_parallel[(u << 32) + v] = num;
		//cout << u << " " << v << " " << num << "\n";
	}

	int nbcc{};
	f1 >> nbcc;

	vector<int> bcc_no_in_parallel(nbcc + 1, -1);
	unordered_set<int> bcc_comp_seen;

	for (int i = 0; i < nbcc; ++i) {
		int bcc_id, size;
		string int_text;
		f1 >> bcc_id >> int_text >> size;
		//cout << bcc_id << " " << size << "\n";

		long long int u, v;
		f1 >> u >> v;

		int p_bcc_num = e_bcc_no_in_parallel[(u << 32) + v];
		if (bcc_comp_seen.find(p_bcc_num) != bcc_comp_seen.end()) {
			cout << "As per parallel BCC the edge " << u << " " << v << " belongs to wrong component that was found previoiusly\n";
			exit(-1);
		}
		bcc_no_in_parallel[bcc_id] = p_bcc_num;
		bcc_comp_seen.insert(p_bcc_num);

		for (int l = 1; l < size; ++l) {

			f1 >> u >> v;
			//cout << "bcc " << bcc_id << " " << u << " " << v << "\n";

			p_bcc_num = e_bcc_no_in_parallel[(u << 32) + v];
			if (p_bcc_num != bcc_no_in_parallel[bcc_id]) {
				cout << "As per parallel BCC the edge " << u << " " << v << " belongs to different component\n";
				exit(-1);
			}
		}
	}

#ifdef debug
	cout << "bcc info compared\n";
#endif
	int no_cv, no_ce,no_bcc;
	int no_cv1, no_bcc1;

	f1 >> no_cv >> no_ce >> no_bcc;
	f2 >> no_cv1 >> no_bcc1;

	if ((no_cv1 != no_cv) || (no_bcc != no_bcc1)) {
		cout << " The count is different \n";
		exit(-1);
	}
#ifdef debug
	cout << "Verification complete: All comparisons successful and correct.\n";
#endif

	cout << "================================\n\nFor the " << argv[1] << "\n\n\tTotal vertices - " << no_of_vertices << ", Total Edges - " << no_of_edges << "\n";
	cout << "\n\tTotal cut vertices - " << no_cv << ", Total cut edges - " << no_ce << ", Total number of BCC's - " << nbcc << "\n\n===============================\n";

	return 0;
}
