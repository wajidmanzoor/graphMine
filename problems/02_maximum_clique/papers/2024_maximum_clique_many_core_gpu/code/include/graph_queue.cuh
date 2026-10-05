#pragma once

#include "cgarray.cuh"
#include "defs.h"

namespace graph
{
	template <typename T, typename MarkType = bool>
	struct GraphQueue_d
	{
		T *count;
		T *queue;
		MarkType *mark;
	};

	template <typename T, typename MarkType = bool>
	class GraphQueue
	{

	public:
		GPUArray<T> count;
		GPUArray<T> queue;
		GPUArray<MarkType> mark; // mark if a node or edge is present in the graph
		GPUArray<GraphQueue_d<T, MarkType>> *device_queue = nullptr;
		int capacity;

		void Create(AllocationTypeEnum at, uint cap, int devId)
		{
			capacity = cap;
			count.initialize("Queue Count", at, 1, devId);
			queue.initialize("Queue data", at, capacity, devId);
			mark.initialize("Queue Mark", at, capacity, devId);

			device_queue = new GPUArray<GraphQueue_d<T, MarkType>>();
			device_queue->initialize("Device Queue", unified, 1, devId);

			// GPU allocations already have device storage. Copying their unused
			// host mirrors here would overwrite initialized flags with garbage.
			if (at == cpuonly)
			{
				count.switch_to_gpu(devId);
				queue.switch_to_gpu(devId);
				mark.switch_to_gpu(devId);
			}
			count.setSingle(0, 0, true);
			mark.setAll(false, true);

			device_queue->gdata()[0].count = count.gdata();
			device_queue->gdata()[0].queue = queue.gdata();
			device_queue->gdata()[0].mark = mark.gdata();

			device_queue->switch_to_gpu();
		}

		void CreateQueueStruct(GraphQueue_d<T, MarkType> *&d)
		{
			d = device_queue->gdata();
		}

		void free()
		{
			if (device_queue != nullptr)
			{
				device_queue->freeGPU();
				delete device_queue;
				device_queue = nullptr;
			}
			count.freeGPU();
			queue.freeGPU();
			mark.freeGPU();
		}
	};
} // namespace graph
