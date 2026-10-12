#include <iostream>
#include <fstream>
#include <string>
#include <vector>
#include <set>
#include <algorithm> // for std::remove_if
#include <utility> //Add this include for std::pair
#include <sstream> // Add this include for std::istringstream

template <typename T> 
void print(const std::vector<T> arr) {
    for(auto i : arr)
        std::cout << i <<" ";
    std::cout << std::endl;
}

template<typename T>
int verify(const std::vector<T>& vec1, const std::vector<T>& vec2) {
    if (vec1.size() != vec2.size()) {
        return -1; // Vectors have different sizes
    }

    for (std::size_t i = 0; i < vec1.size(); i++) {
        if (vec1[i] != vec2[i]) {
            return static_cast<int>(i); // Return the index of the first differing element
        }
    }

    return -1; // Vectors are the same
}

void bcc_verify(const std::vector<std::vector<int>>& bcc_serial, const std::vector<int> bcc_parallel)
{
    std::vector<bool> visited(bcc_parallel.size(), false);
    std::vector<int> parent_component(bcc_parallel.size(), -1);

    std::set<int> unique_num;
    for(int i = 0; i < bcc_serial.size(); ++i)
    {
        int vertex = bcc_serial[i][0];
        int num = bcc_parallel[vertex];

        //check if this number is unique and all the vertices in the component are having the same number of not
        //step 1 : Check if this number is unique
        if (unique_num.find(num) != unique_num.end()) {
            // Element found in set
            std::cerr << "\nThe component number for vertex " << vertex <<" is not unique .";
            return;
        } 
        else {
            // Element not found in set
            //step 2 : Check if all the vertices in the same component have same number
            for(int j = 0; j < bcc_serial[i].size(); ++j)
            {
                if(bcc_parallel[bcc_serial[i][j]] != num or visited[bcc_serial[i][j]]) {
                    if(visited[bcc_serial[i][j]])
                        std::cout << "\nVertex " << bcc_serial[i][j] << " is already visited by " << parent_component[bcc_serial[i][j]];
                    std::cerr <<"\nDifferent bcc_num for vertex " << bcc_serial[i][j] << " belonging to component " << num;
                    return;
                }

                visited[bcc_serial[i][j]] = true;
                parent_component[bcc_serial[i][j]] = i;
            }
        }
    }
    std::cout <<"\nHurrray! Verification Successful.\n";
}

std::pair<std::vector<int>, std::vector<int>> processDataForParallelOutput(const std::string& filename) {
    std::ifstream inputFile(filename);
    if (!inputFile) {
        std::cerr << "Error opening the file." << std::endl;
        return {}; // Return an empty pair as a placeholder for the error case
    }
    // Ignore the first line
    std::string line;

    int n; // number of vertices
    long e;
    inputFile >> n >> e;
    // Consume the left over line
    std::getline(inputFile, line);     
    std::vector<int> cut_vertices_parallel_output(n);
    std::vector<int> bcc_num_parallel_output(n);

    std::getline(inputFile, line);
    if(line != "cut vertex status") {
        std::cerr <<"Expected cut vertices status, but got " << line << std::endl;
        exit(-1);
    }

    int vertex, value;
    for (int i = 0; i < n; i++) {
        inputFile >> vertex >> value;
        cut_vertices_parallel_output[vertex] = value;
    }

    std::getline(inputFile, line); // Consume the leftover newline character
    std::getline(inputFile, line);
    if(line != "vertex BCC number") {
        std::cerr <<"Expected vertex BCC number, but got " << line << std::endl;
        exit(-1);
    }

    for(int i = 0; i < n; ++i) {
        inputFile >> vertex >> value;
        bcc_num_parallel_output[vertex] = value;
    }
    
    return {cut_vertices_parallel_output, bcc_num_parallel_output}; // Return both vectors as a pair
}

std::pair<std::vector<int>, std::vector<std::set<int>>> processDataForSerialOutput(const std::string& filename) {
    std::ifstream inputFile(filename);
    if (!inputFile) {
        std::cerr << "Error opening the file." << std::endl;
        return {}; // Return an empty vector as a placeholder for the error case
    }

    std::string line;
    std::getline(inputFile, line); // Read the first line as a whole

    int n, num_values;
    std::istringstream iss(line); // Create a string stream to parse the line
    iss >> n >> num_values;

    std::vector<int> cut_vertices_serial_output(n);

    // Ignore the second line
    std::getline(inputFile, line);

    int vertex, value;
    for (int i = 0; i < n; i++) {
        inputFile >> vertex >> value;
        cut_vertices_serial_output[vertex] = value;
    }

    while(std::getline(inputFile, line)) {
        if(line == "Explicit BCC's")
            break;
    }
    inputFile >> n;
    std::getline(inputFile, line); //To ingore the new line a.k.a "\n";

    /*
    e.g. 7
         1 <-bcc_num|bcc_size-> 3
         here it means
         7\n (becoz I hit enter)
         then 3 characters 1, <-bcc_num|bcc_size->, 3
    */
    
    std::vector<std::set<int>> bcc(n);
    
    while(std::getline(inputFile, line))
    {
        int bcc_num, bcc_size;
        std::string temp;
        std::istringstream iss(line);
        iss >> bcc_num >> temp >> bcc_size;
        int u, v;
        for(int i = 0; i < bcc_size; ++i)
        {
            inputFile >> u >> v;
            if(!cut_vertices_serial_output[u])
                bcc[bcc_num - 1].insert(u);
            if(!cut_vertices_serial_output[v])
                bcc[bcc_num - 1].insert(v);
        }

        std::getline(inputFile, line); //for /n
        std::getline(inputFile, line); //for empty line
    }

    inputFile.close();
    return {cut_vertices_serial_output, bcc};
}

int main(int argc, char* argv[]) {
    if (argc != 3) {
        std::cerr << "Usage: " << argv[0] << " <parallel_output_file>" << " <serial_output_file>" << std::endl;
        return 1;
    }

    std::string filename_1 = argv[1];
    std::string filename_2 = argv[2];

    auto arr_parallel = processDataForParallelOutput(filename_1);
    std::vector<int> cut_vertices_parallel_output = arr_parallel.first;
    std::vector<int> bcc_num_parallel_output = arr_parallel.second;

    auto arr_serial = processDataForSerialOutput(filename_2);
    std::vector<int> cut_vertices_serial_output = arr_serial.first;
    std::vector<std::set<int>> bcc_serial = arr_serial.second;

    bcc_serial.erase(std::remove_if(bcc_serial.begin(), bcc_serial.end(), [](const std::set<int>& s) 
    {
    return s.empty();
    }), bcc_serial.end());

    #ifdef DEBUG
        std::cout <<"Printing parallel cut vertices : \n"; print(cut_vertices_parallel_output);
        std::cout <<"Printing parallel bcc numbers : \n"; print(bcc_num_parallel_output);

        std::cout <<"Printing serial cut vertices : \n"; print(cut_vertices_serial_output);
        std::cout <<"Printing serial bcc numbers : \n"; 
        for (const std::set<int>& s : bcc_serial) {
            for (int num : s) 
            {
                std::cout << num << " ";
            }
            std::cout << std::endl;
        }
    #endif

    std::vector<std::vector<int>> bcc_serial_vect;

    for (const auto& set : bcc_serial) {
        std::vector<int> vec(set.begin(), set.end()); // Convert set to vector
        bcc_serial_vect.push_back(vec);
    }

    #ifdef DEBUG
        for(int i = 0; i < bcc_serial_vect.size(); ++i)
        {
            for(int j = 0; j < bcc_serial_vect[i].size(); ++j)
            {
                std::cout << bcc_serial_vect[i][j] << " ";
            }
            std::cout << std::endl;
        }
    #endif

    int errorIndex;

    errorIndex = verify(cut_vertices_parallel_output, cut_vertices_serial_output);
    if (errorIndex == -1) {
        std::cout << "vec1 and vec2 are the same. Cut vertices verification over. " << std::endl;
    } else {
        std::cout <<"Cut vertices verification failed. ";
        std::cout << "vec1 and vec2 are different. Error at index: " << errorIndex << std::endl;
    }

    bcc_verify(bcc_serial_vect, bcc_num_parallel_output);



    return 0;
}