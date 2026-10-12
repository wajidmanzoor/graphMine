#include <vector>
#include <string>
#include <fstream>
#include <iostream>
#include <filesystem>

#include "utility.hpp"

bool verify(const std::vector<long>& arr_1, const std::vector<long>& arr_2) {
    if(arr_1.size() != arr_2.size()) {
        std::cout <<"arr_1 size = " << arr_1.size() << std::endl;
        std::cout <<"arr_2 size = " << arr_2.size() << std::endl;
        std::cerr <<"Error in size.";
        return false;
    }
    for (size_t i = 0; i < arr_1.size(); ++i) {
        if (arr_1[i] != arr_2[i]) {
            std::cout << "Mismatch at index " << i << ":\n";
            std::cout << "arr_1[" << i << "] = " << arr_1[i] << "\n";
            std::cout << "arr_2[" << i << "] = " << arr_2[i] << "\n";
            return false;
        }
    }

    return true;
}

bool verify(const std::vector<int>& arr_1, const std::vector<int>& arr_2) {
    if(arr_1.size() != arr_2.size()) {
        std::cout <<"arr_1 size = " << arr_1.size() << std::endl;
        std::cout <<"arr_2 size = " << arr_2.size() << std::endl;
        std::cerr <<"Error in size.";
        return false;
    }
    for (size_t i = 0; i < arr_1.size(); ++i) {
        if (arr_1[i] != arr_2[i]) {
            std::cout << "Mismatch at index " << i << ":\n";
            std::cout << "arr_1[" << i << "] = " << arr_1[i] << "\n";
            std::cout << "arr_2[" << i << "] = " << arr_2[i] << "\n";
            return false;
        }
    }

    return true;
}

std::string get_file_extension(std::string filename) {

    std::filesystem::path file_path(filename);

    // Extracting filename with extension
    filename = file_path.filename().string();
    // std::cout << "Filename with extension: " << filename << std::endl;

    // Extracting filename without extension
    std::string filename_without_extension = file_path.stem().string();
    // std::cout << "Filename without extension: " << filename_without_extension << std::endl;

    return filename_without_extension;
}

void write_CSR(const std::vector<long>& vertices, const std::vector<int>& edges, std::string filename) {
    
    filename = get_file_extension(filename);
    std::string output_file = filename + "_csr.log";
        std::ofstream outFile(output_file);

        if(!outFile) {
            std::cerr <<"Unable to create file for writing.\n";
            return;
        }
    int numVertices = vertices.size() - 1;
    for (int i = 0; i < numVertices; ++i) {
        outFile << "Vertex " << i << " is connected to: ";
        for (int j = vertices[i]; j < vertices[i + 1]; ++j) {
            outFile << edges[j] << " ";
        }
        outFile << "\n";
    }
}

void print_CSR(const std::vector<long>& vertices, const std::vector<int>& edges) {
    int numVertices = vertices.size() - 1;
    for (int i = 0; i < numVertices; ++i) {
        std::cout << "Vertex " << i << " is connected to: ";
        for (int j = vertices[i]; j < vertices[i + 1]; ++j) {
            std::cout << edges[j] << " ";
        }
        std::cout << "\n";
    }
}

std::string formatDuration(double timeInMs) {
    std::ostringstream stream;

    if (timeInMs < 1000) {
        // Less than 1 second, show in milliseconds
        stream << timeInMs << " ms";
    } else if (timeInMs < 60000) {
        // Less than 1 minute, show in seconds
        stream << std::fixed << std::setprecision(3) << (timeInMs / 1000.0) << " sec";
    } else {
        // Show in minutes and seconds
        long minutes = static_cast<long>(timeInMs / 60000);
        double seconds = static_cast<long>(timeInMs) % 60000 / 1000.0;
        stream << minutes << " min " << std::fixed << std::setprecision(3) << seconds << " sec";
    }

    return stream.str();
}




