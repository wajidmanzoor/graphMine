#include <tot.h>

int main(int argc, char** argv)
{

    tot::CsrMatrix<int, float, tot::device_memory> A_csr;
    tot::CooMatrix<int, float, tot::device_memory> A_coo;
    tot::CooMatrix<int, float, tot::device_memory> A_coo_upper;

    tot::Config config = tot::program_options(argc, argv);

    tot::read_matrix_file(A_csr, config.input_file);

    tot::convert_csr_to_coo(A_coo, A_csr);
    A_csr.free();

    tot::convert_undirected(A_coo);

    tot::CUDATimer timer;

    if (config.extract) {
        timer.start();
        tot::extract_upper_triangular(A_coo);
        timer.stop();
        printf("[Extracting Upper Triangular] time: %f ms\n", timer.elapsed());
    }

    printf("\n--------------tot----------------\n");
    {
        timer.start();
        //+++++++++++++++++++++++++++++++++
        tot::BitmapCOO<int, float, tot::bmp64_t, 4, tot::device_memory> A_bmp;

        tot::convert_coo2bmp(A_coo, A_bmp);
        //+++++++++++++++++++++++++++++++++
        timer.stop();
        printf("[Converting to Bitmap] time: %lf ms\n", timer.elapsed());

        timer.start();
        //+ Execution

        auto count = tot::count_triangles_on_tensors(A_bmp, A_bmp, A_bmp);

        count = config.extract ? count : count / 6;
        //+ Execution
        timer.stop();
        printf("[Counting Triangles] time: %f ms\n", timer.elapsed());
        printf("Triangles (GPU): %d\n", count);
    }

    if (config.verify) {
        tot::convert_coo_to_csr(A_csr, A_coo);

        tot::CsrMatrix<int, float, tot::host_memory> A_csr_h;
        A_csr_h = A_csr;

        auto count_cpu = tot::bfs_tc(A_csr_h);
        count_cpu      = config.extract ? count_cpu : count_cpu / 3;
        printf("Triangles (CPU): %d\n", count_cpu);
    }
}