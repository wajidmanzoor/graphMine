#ifndef __COMMON_H__
#define __COMMON_H__
#include <iostream>
#include <string>
#include "IndexType.h"
#include "common.h"
using std::endl;
using std::cout;

template<typename T>
void PrintArrayln(T *x, uint32_t num, std::string name) {
    cout << "name: " << name << endl;
    cout << "ite: " << num << endl;
    for (uint32_t i = 0; i < num; ++i) {
        cout << x[i] << endl;
    }
    cout << endl;
}

template<typename T> 
void PrintValueln(T x, std::string str) {
    cout << str << ": " << x << endl;
}

template<typename T> 
void PrintValuesp (T x, std::string str){
        cout << str << ": " << x << " ";
}

template<typename T>
void PrintEdgeln(T *x, uint32_t num, std::string name) {
  cout << "name: " << name << endl;
  cout << "ite: " << num << endl;
  for(uint32_t i = 0; i < num; ++i) {
    cout << x[i].source << " " << x[i].destination << endl;
  }
  cout << endl;
}


#define CPUAlloc(__E, __n) (__E *)malloc((__n) * sizeof(__E))
#endif