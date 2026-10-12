//package imoprt_exoprt_jgrapht_gxl;

/**
 * Created by user on 22/06/2017.
 */
public class HashFunction {

    public static int getHash(String S) // Rolling hash (Rabin Krap function)
    {
//        http://algs4.cs.princeton.edu/53substring/RabinKarp.java.html
//        R = 256;
//        m = key.length();
//        q = longRandomPrime(); // a large prime, small enough to avoid long overflow
//        // Compute hash for key[0..m-1].
//        private long hash(String key, int m) {
//        long h = 0;
//        for (int j = 0; j < m; j++)
//            h = (R * h + key.charAt(j)) % q;
//        return h;
//        }

        int H = 0;

        int Seed = 256;
        //int Prime = 997;
        int Prime = 2147483647; // (2^31)-1  : a large prime number < 2^32  (it's fits in 32 bits)

        for (int i = 0; i < S.length(); i++)
            H = (H * Seed + S.charAt(i)) % Prime;

        return H;
    }

}
