#pragma once

class idle_queue {
public:
    int *data;          // Array to store queue elements
    int *head;          // Pointer to the front of the queue
    int *rear;          // Pointer to the back of the queue
    int *size;          // Current number of elements in the queue
    int *limit_size;    // Maximum capacity of the queue

    idle_queue() : data(nullptr), head(nullptr), rear(nullptr),
        size(nullptr), limit_size(nullptr) {}

    // Initialize the queue on the device
    __host__ void
    init(int lim = 2048) {
        // Allocate and initialize device memory
        cudaCheck(cudaMalloc(&limit_size, sizeof(int)));
        cudaCheck(cudaMemcpy(limit_size, &lim, sizeof(int), cudaMemcpyHostToDevice));

        cudaCheck(cudaMalloc(&data, sizeof(int) * lim));
        cudaCheck(cudaMemset(data, -1, sizeof(int) * lim));  // Initialize all elements to -1 (0xFF per byte)

        cudaCheck(cudaMalloc(&head, sizeof(int)));
        cudaCheck(cudaMemset(head, 0, sizeof(int)));

        cudaCheck(cudaMalloc(&rear, sizeof(int)));
        cudaCheck(cudaMemset(rear, 0, sizeof(int)));

        cudaCheck(cudaMalloc(&size, sizeof(int)));
        cudaCheck(cudaMemset(size, 0, sizeof(int)));
    }

    // Release device memory resources
    __host__ void
    deallocate() {
        if (data) {
            cudaFree(data);
        }
        if (head) {
            cudaFree(head);
        }
        if (rear) {
            cudaFree(rear);
        }
        if (size) {
            cudaFree(size);
        }
        if (limit_size) {
            cudaFree(limit_size);
        }
        data = head = rear = size = limit_size = nullptr;
    }

    ~idle_queue() {
        deallocate();
    }

    __device__ int
    length() {
        return *size;
    }

    // Add an element to the queue (device function)
    __device__ bool
    enqueue(int elem) {
        __threadfence();

        int oldSize = atomicAdd(size, 1);
        if (oldSize >= *limit_size) {
            atomicSub(size, 1);
            return false;
        }

        int pos = atomicAdd(rear, 1) % *limit_size;

        // Wait until we can atomically insert the element
        while (atomicCAS(&data[pos], -1, elem) != -1) {
            __nanosleep(100);
        }

        __threadfence();
        return true;
    }

    // Remove and return an element from the queue (device function)
    __device__ bool
    dequeue(int *elem) {
        __threadfence();
        int oldSize = atomicSub(size, 1);
        if (oldSize <= 0) {
            atomicAdd(size, 1);
            return false;
        }

        int pos = atomicAdd(head, 1) % *limit_size;

        // Wait until we can atomically retrieve an element
        int old_val;
        while ((old_val = atomicExch(&data[pos], -1)) == -1) {
            __nanosleep(100);
        }
        *elem = old_val;

        __threadfence();
        return true;
    }
};