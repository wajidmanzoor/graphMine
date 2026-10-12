#include "fileIO.h"
#include "topo.cuh"
#include "topo_batch.cuh"

int main(int argc, char* argv[]) {

	bool computePH		= true;
	bool write2HDD		= false;
	bool output_peakRAM	= false;

    //PH2D_multiThread<ushort_> ph(computePH, write2HDD);
    //TopoGPU2D<ushort_> topo2D(uint2{ 1690, 2004 }, 1500, uint2{ 0, 0 }, -1, false, false);

    //for (const auto& entry : fs::directory_iterator("E:/WorkBench/TopoGPU_baselines_py/CuMPerLay/data/Glaucoma")) {
    //    if (entry.is_regular_file() && entry.path().extension() == ".jpg") {
    //        topo2D.configure(uint2{ 1690, 2004 });
    //        topo2D.run_frmFile(entry.path().string(), "uchar", ph);
    //        ph.bndmat_reduction();
    //        ph.print_results(false);
    //        ph.reset();
    //    }
    //}

	//{
	//	std::string filename2d1 = "E:/Data/topoGPU/GaussianRandomField/2D/2D_32_1.dat";
	//	std::string filename2d2 = "E:/Data/topoGPU/GaussianRandomField/2D/2D_64_1.dat";
	//	uint2 imgSize2d1 = make_uint2(32, 32);
	//	uint2 imgSize2d2 = make_uint2(64, 64);
	//	PH2D_multiThread<float> ph(computePH, write2HDD);
	//	TopoGPU2D<float> topo2D(uint2{ 128, 128 }, 500, uint2{ 0, 0 }, -1, false, false);

	//	// Read from file
	//	topo2D.configure(imgSize2d1);
	//	topo2D.run_frmFile(filename2d1, "float", ph);
	//	ph.bndmat_reduction();
	//	ph.print_results(false);
	//	ph.reset();

	//	topo2D.configure(imgSize2d2);
	//	topo2D.run_frmFile(filename2d2, "float", ph);
	//	ph.bndmat_reduction();
	//	ph.print_results(false);
	//	ph.reset();

	//	//// Read whole file
	//	//float* data2d1 = readArrayFromBin2D_multiThread<float, float>(filename2d1, imgSize2d1);
	//	//float* data2d2 = readArrayFromBin2D_multiThread<float, float>(filename2d2, imgSize2d2);

	//	//topo2D.configure(imgSize2d1);
	//	//topo2D.run_frmArr(data2d1, ph);
	//	//ph.bndmat_reduction();
	//	//ph.print_results(false);
	//	//ph.reset();

	//	//topo2D.configure(imgSize2d2);
	//	//topo2D.run_frmArr(data2d2, ph);
	//	//ph.bndmat_reduction();
	//	//ph.print_results(false);
	//	//ph.reset();
	//}
	
	//{
	//	std::string filename3d1 = "E:/Data/topoGPU/gMSC/csafe_heptane_302x302x302_uint8.raw";
	//	std::string filename3d2 = "E:/Data/topoGPU/gMSC/silicium_98x34x34_uint8.raw";
	//	uint3 imgSize3d1 = make_uint3(302, 302, 302);
	//	uint3 imgSize3d2 = make_uint3(34, 98, 34);
	//	PH3D_multiThread<float> ph(computePH, write2HDD);
	//	TopoGPU3D<float> topo3D(uint3{512, 512, 512}, 2000, uint3{ 0, 0, 0 }, -1, false, false);

	//	// Read from file
	//	topo3D.configure(imgSize3d1);
	//	topo3D.run_frmFile(filename3d1, "uchar", ph);
	//	ph.bndmat_reduction();
	//	ph.print_results(false);
	//	ph.reset();

	//	topo3D.configure(imgSize3d2);
	//	topo3D.run_frmFile(filename3d2, "uchar", ph);
	//	ph.bndmat_reduction();
	//	ph.print_results(false);
	//	ph.reset();

	//	//// Read whole file
	//	//float* data3d1 = readArrayFromBin_multiThread<uchar_, float>(filename3d1, imgSize3d1);
	//	//float* data3d2 = readArrayFromBin_multiThread<uchar_, float>(filename3d2, imgSize3d2);

	//	//topo3D.configure(imgSize3d1);
	//	//topo3D.run_frmArr(data3d1, ph);
	//	//ph.bndmat_reduction();
	//	//ph.print_results(false);
	//	//ph.reset();

	//	//topo3D.configure(imgSize3d2);
	//	//topo3D.run_frmArr(data3d2, ph);
	//	//ph.bndmat_reduction();
	//	//ph.print_results(false);
	//	//ph.reset();
	//}

    // =======================================================
    // Arguments passed in from commandline

    CmdArgs cfg;
    bool ok = parse_commandlneArges(argc, argv, cfg);
    if (!ok) return 1;

    const bool is3D         = (cfg.depth != 0);
    uint_        bufferSize = (cfg.bufSize > 0) ? cfg.bufSize : 2000;
    std::string  filename   = cfg.filename;
    std::string  dtype      = cfg.datatype;

    if (is3D) {
        // ================================
        // 3D case: use TopoGPU3D / PH3D
        // ================================
        uint3 imgSize = make_uint3(cfg.height, cfg.width, cfg.depth);
        uint3 blockSize = make_uint3(cfg.bx, cfg.by, cfg.bz);

        if (dtype == "uchar") {
            PH3D_multiThread<ushort_> ph(computePH, write2HDD);
            auto start = std::chrono::high_resolution_clock::now();
            TopoGPU3D<ushort_> topo3D(imgSize, bufferSize, blockSize, -1, false, false);
            topo3D.configure(imgSize);
            topo3D.run_frmFile(filename, dtype, ph);
            double bnd_time = ph.bndmat_reduction();
            auto stop = std::chrono::high_resolution_clock::now();
            std::cout << "Total time (chunky, 3D): "
                << std::chrono::duration_cast<std::chrono::microseconds>(stop - start).count() / 1000000.0
                << std::endl;
#ifdef ENABLE_TIMING
            topo3D.printDetailedTiming();
            std::cout << "boundary matrix reduction: " << bnd_time << " secs" << std::endl;
#endif
            ph.print_results(false);
            if (!cfg.out.empty()) ph.write_results(cfg.out);
            ph.reset();
        }
        else if (dtype == "ushort") {
            PH3D_multiThread<int> ph(computePH, write2HDD);
            auto start = std::chrono::high_resolution_clock::now();
            TopoGPU3D<int> topo3D(imgSize, bufferSize, blockSize, -1, false, false);
            topo3D.configure(imgSize);
            topo3D.run_frmFile(filename, dtype, ph);
            double bnd_time = ph.bndmat_reduction();
            auto stop = std::chrono::high_resolution_clock::now();
            std::cout << "Total time (chunky, 3D): "
                << std::chrono::duration_cast<std::chrono::microseconds>(stop - start).count() / 1000000.0
                << std::endl;
#ifdef ENABLE_TIMING
            topo3D.printDetailedTiming();
            std::cout << "boundary matrix reduction: " << bnd_time << " secs" << std::endl;
#endif
            ph.print_results(false);
            if (!cfg.out.empty()) ph.write_results(cfg.out);
            ph.reset();
        }
        else if (dtype == "int") {
            PH3D_multiThread<int> ph(computePH, write2HDD);
            auto start = std::chrono::high_resolution_clock::now();
            TopoGPU3D<int> topo3D(imgSize, bufferSize, blockSize, -1, false, false);
            topo3D.configure(imgSize);
            topo3D.run_frmFile(filename, dtype, ph);
            double bnd_time = ph.bndmat_reduction();
            auto stop = std::chrono::high_resolution_clock::now();
            std::cout << "Total time (chunky, 3D): "
                << std::chrono::duration_cast<std::chrono::microseconds>(stop - start).count() / 1000000.0
                << std::endl;
#ifdef ENABLE_TIMING
            topo3D.printDetailedTiming();
            std::cout << "boundary matrix reduction: " << bnd_time << " secs" << std::endl;
#endif
            ph.print_results(false);
            if (!cfg.out.empty()) ph.write_results(cfg.out);
            ph.reset();
        }
        else if (dtype == "float") {
            PH3D_multiThread<float> ph(computePH, write2HDD);
            auto start = std::chrono::high_resolution_clock::now();
            TopoGPU3D<float> topo3D(imgSize, bufferSize, blockSize, -1, false, false);
            topo3D.configure(imgSize);
            topo3D.run_frmFile(filename, dtype, ph);
            double bnd_time = ph.bndmat_reduction();
            auto stop = std::chrono::high_resolution_clock::now();
            std::cout << "Total time (chunky, 3D): "
                << std::chrono::duration_cast<std::chrono::microseconds>(stop - start).count() / 1000000.0
                << std::endl;
#ifdef ENABLE_TIMING
            topo3D.printDetailedTiming();
            std::cout << "boundary matrix reduction: " << bnd_time << " secs" << std::endl;
#endif
            ph.print_results(false);
            if (!cfg.out.empty()) ph.write_results(cfg.out);
            ph.reset();
        }
        else {
            std::fprintf(stderr, "Error: unknown datatype '%s'\n", dtype.c_str());
            return 1;
        }
    }
    else {
        // ================================
        // 2D case: use TopoGPU2D / PH2D
        // ================================
        uint2 imgSize = make_uint2(cfg.height, cfg.width);
        uint2 blockSize = make_uint2(cfg.bx, cfg.by);

        if (dtype == "uchar") {
            PH2D_multiThread<ushort_> ph(computePH, write2HDD);
            auto start = std::chrono::high_resolution_clock::now();
            TopoGPU2D<ushort_> topo2D(imgSize, bufferSize, blockSize, -1, false, false);
            topo2D.configure(imgSize);
            topo2D.run_frmFile(filename, dtype, ph);
            double bnd_time = ph.bndmat_reduction();
            auto stop = std::chrono::high_resolution_clock::now();
            std::cout << "Total time (chunky, 2D): "
                << std::chrono::duration_cast<std::chrono::microseconds>(stop - start).count() / 1000000.0
                << std::endl;
#ifdef ENABLE_TIMING
            topo2D.printDetailedTiming();
            std::cout << "boundary matrix reduction: " << bnd_time << " secs" << std::endl;
#endif
            ph.print_results(false);
            if (!cfg.out.empty()) ph.write_results(cfg.out);
            ph.reset();
        }
        else if (dtype == "ushort") {
            PH2D_multiThread<int> ph(computePH, write2HDD);
            auto start = std::chrono::high_resolution_clock::now();
            TopoGPU2D<int> topo2D(imgSize, bufferSize, blockSize, -1, false, false);
            topo2D.configure(imgSize);
            topo2D.run_frmFile(filename, dtype, ph);
            double bnd_time = ph.bndmat_reduction();
            auto stop = std::chrono::high_resolution_clock::now();
            std::cout << "Total time (chunky, 2D): "
                << std::chrono::duration_cast<std::chrono::microseconds>(stop - start).count() / 1000000.0
                << std::endl;
#ifdef ENABLE_TIMING
            topo2D.printDetailedTiming();
            std::cout << "boundary matrix reduction: " << bnd_time << " secs" << std::endl;
#endif
            ph.print_results(false);
            if (!cfg.out.empty()) ph.write_results(cfg.out);
            ph.reset();
        }
        else if (dtype == "int") {
            PH2D_multiThread<int> ph(computePH, write2HDD);
            auto start = std::chrono::high_resolution_clock::now();
            TopoGPU2D<int> topo2D(imgSize, bufferSize, blockSize, -1, false, false);
            topo2D.configure(imgSize);
            topo2D.run_frmFile(filename, dtype, ph);
            double bnd_time = ph.bndmat_reduction();
            auto stop = std::chrono::high_resolution_clock::now();
            std::cout << "Total time (chunky, 2D): "
                << std::chrono::duration_cast<std::chrono::microseconds>(stop - start).count() / 1000000.0
                << std::endl;
#ifdef ENABLE_TIMING
            topo2D.printDetailedTiming();
            std::cout << "boundary matrix reduction: " << bnd_time << " secs" << std::endl;
#endif
            ph.print_results(false);
            if (!cfg.out.empty()) ph.write_results(cfg.out);
            ph.reset();
        }
        else if (dtype == "float") {
            PH2D_multiThread<float> ph(computePH, write2HDD);
            auto start = std::chrono::high_resolution_clock::now();
            TopoGPU2D<float> topo2D(imgSize, bufferSize, blockSize, -1, false, false);
            topo2D.configure(imgSize);
            topo2D.run_frmFile(filename, dtype, ph);
            double bnd_time = ph.bndmat_reduction();
            auto stop = std::chrono::high_resolution_clock::now();
            std::cout << "Total time (chunky, 2D): "
                << std::chrono::duration_cast<std::chrono::microseconds>(stop - start).count() / 1000000.0
                << std::endl;
#ifdef ENABLE_TIMING
            topo2D.printDetailedTiming();
            std::cout << "boundary matrix reduction: " << bnd_time << " secs" << std::endl;
#endif
            ph.print_results(false);
            if (!cfg.out.empty()) ph.write_results(cfg.out);
            ph.reset();
        }
        else {
            std::fprintf(stderr, "Error: unknown datatype '%s'\n", dtype.c_str());
            return 1;
        }
    }

#if defined(WIN64) || defined(WIN32)
	if (output_peakRAM) printPeakMemoryUsage();
#endif

	return 0;
}