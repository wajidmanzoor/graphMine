#include <cuda.h>
#include <cuda_runtime.h>
#include <cooperative_groups.h>



//__device__ float stat_edf[INT_MAX];


__device__ void best_i(int i, int val, int * best_, int depth){
/*if(i<depth){
  int old=0;
  if(val <best_[i]){
  old=  atomicMin(&best_[i],val ); }
  else{ old= val +100;}
if(old>val){ best_i(i+1,old, best_, depth); }
else if(old<val){best_i(i+1,val, best_, depth);}
}*/


for (int i1=0;i1<depth;i1++){
  int old=0;
  if(val <best_[i1]){
  old=  atomicMin(&best_[i1],val ); }
  else{ old= val -1;}

if(old>val){ //best_i(i+1,old, best_, depth);
val=old;
 }
//else if(old<val){//best_i(i+1,val, best_, depth);}
}

}

extern "C"
__global__ void eval(float * initail_eval, int g1_nb_operation, int g2_nb_operation, float co1, float co2, float ce1, float ce2, int index_g1, int old_size, int * remain_g2, int *  old_opf, int * old_opt, int * adj_mat_g1, int * adj_mat_g2, int * weight_g1, int * weight_g2, float * result, int * best_ , int * nb_)
{
    int id = blockIdx.x * blockDim.x + threadIdx.x;
    int offset_remain= blockIdx.x*g2_nb_operation;
    int offset_old= blockIdx.x*g1_nb_operation;
    __shared__ int shared_result[1000];
    extern __shared__ int stat_edf[];
     float cost=initail_eval[blockIdx.x];
     stat_edf[threadIdx.x]= -1;
    int opf=index_g1;
    if(old_opf[offset_old]>0)
    {
     if(id==0){
      best_[0]=INT_MAX-10000; best_[1]=INT_MAX-10000;best_[2]=INT_MAX-10000;best_[3]=INT_MAX-10000;best_[4]=INT_MAX-10000;
      best_[5]=INT_MAX-10000; best_[6]=INT_MAX-10000;best_[7]=INT_MAX-10000;best_[8]=INT_MAX-10000;best_[9]=INT_MAX-10000;
    nb_[0]=0; nb_[1]=0; nb_[2]=0;nb_[3]=0; nb_[4]=0;nb_[5]=0; nb_[6]=0; nb_[7]=0;nb_[8]=0; nb_[9]=0;
  
     }
   
    //result[id]=100;
    //printf("\n%d : %d", id, remain_g2[id]);
    //printf("\n%d : %d %d", id, old_opf[0] , old_opt[0]);
    //printf("\n id %d %.2f %.2f",id,adj_mat_g1[id],adj_mat_g2[id]);
     
       if(old_size>0) for (int i1=0;i1<old_size;i1=i1+blockDim.x){
        int i=i1+threadIdx.x;
        //if(threadIdx.x==0)
       if(i<old_size) { //printf("\n reached %d old size:%d, adj mat:%f", id,old_size, adj_mat_g1[opf*g1_nb_operation+old_opf[i]-1]);
     {stat_edf[/*offset_old+*/ i]= adj_mat_g1[(opf)*g1_nb_operation+old_opf[offset_old+ i]-1];
        //  if(blockIdx.x==2)  printf("\n node:%d opf (index_g1)%d old_opf:%d stat_edf %.2f",blockIdx.x,opf, old_opf[i], stat_edf[i]);
     }
      
     } 
    }
  

  // Shared memory array for efficient sorting within a block


  //__shared__ int nb_local_best;
  shared_result[threadIdx.x]=INT_MAX;
 //if(threadIdx.x==0){nb_local_best=0;} 
}else{
  result[id]=1000000;
  shared_result[threadIdx.x]=INT_MAX;
}

    __syncthreads(); 

 if(old_opf[offset_old]>0)
    {
    int opt= remain_g2[offset_remain+ threadIdx.x];
/*if(id==0){printf("\n opf:%d", index_g1+1);
for (int i=0;i<g2_nb_operation;i++){
 // printf("\neval i:%d  opt:%d ", i, old_opt[i]);
   printf("\nremain i:%d  op:%d ", i, remain_g2[i]);
}
 }*/
    if(opt >=0 && opt<= g2_nb_operation)
    {
    if(fabsf (weight_g1[index_g1]-weight_g2[opt-1])>0.001)cost=cost+co1; 
      float implied_edge_cot=0;
      for (int i=0;i<old_size;i++){
        
        int o_t= old_opt[offset_old +i];
       int x =-1;
       int status=stat_edf[/*offset_old+*/ i];
        if(o_t>=0){
        x =adj_mat_g2[(opt-1)*g2_nb_operation+o_t-1];
       
        if((x>=0)&&(status>=0)){ if(fabsf (x-status) > 0.001) {implied_edge_cot=implied_edge_cot+ce1;} }
        else if((x>=0)||(status>=0)){implied_edge_cot=implied_edge_cot+ce2; }
        } else if(status>=0){implied_edge_cot=implied_edge_cot+ce2;        }
          //if (id==2*g2_nb_operation) printf("\n node:%d opt :%d o_t:%d x:%.2f status:%.2f implied_cost: %.2f cost:%.2f ",blockIdx.x,opt,o_t, x , status, implied_edge_cot,cost);
     }
     cost=cost+implied_edge_cot;
     result[id]=cost;
     shared_result[threadIdx.x]=(int)cost*1000;
   //if(opt==1)  printf("\n 2-thread :%d  opt:%d cost:%.2f",threadIdx.x,opt,cost );

    }
    else{
      result[id]=1000000;
      shared_result[threadIdx.x]=(int)INT_MAX;        

/*&&(g1_nb_operation>g2_nb_operation)*/
       if((threadIdx.x==(g2_nb_operation-1)))
       { 
          //============= d eletion of the node ==================================   
          float cost1=initail_eval[blockIdx.x]+co2; 
          float implied_edge_cot=0;
          for (int i=0;i<old_size;i++){
          int status=stat_edf[i];
          if(status>=0){implied_edge_cot=implied_edge_cot+ce2;} 
              }

          cost1=cost1+implied_edge_cot;
         
        if(result[id]>cost1){
        result[id]=cost1;
        shared_result[threadIdx.x]=(int)cost1*1000;
       // if(index_g1>g2_nb_operation)
       // {shared_result[threadIdx.x]=shared_result[threadIdx.x]+0*co2*1000;}
        }
          }
          
          }
   // if(id==0)printf(" node: %d, inital result:%.2f", blockIdx.x,initail_eval[blockIdx.x] );
    }
    __syncthreads(); 
     // get my local rank 
     int my_rank=0;
     for (int i=0;i<blockDim.x;i++){
     if(shared_result[i]<shared_result[threadIdx.x])my_rank++;
     else if(shared_result[i]==shared_result[threadIdx.x])if(i!=threadIdx.x && i<threadIdx.x)my_rank++; 
     }
 //   __syncthreads(); 
 //if(my_rank==0||my_rank==1){printf ("\n block:%d idx:%d , rank:%d  value:%d",blockIdx.x,threadIdx.x,my_rank,shared_result[threadIdx.x]);}
if((shared_result[threadIdx.x]<INT_MAX)&&(my_rank==0||my_rank==1||my_rank==2||my_rank==3||my_rank==4))
{
  best_i(0,shared_result[threadIdx.x],best_,8);
// atomicMax(&best_[9],shared_result[threadIdx.x] );
}else if(shared_result[threadIdx.x]<INT_MAX){
 }
  /*
   int old=  atomicMin(&best_[0],shared_result[threadIdx.x] );
  // printf("\nold %d, me:%d, best_0:%d", old, shared_result[threadIdx.x], best_[0]);
   if(old>shared_result[threadIdx.x]){int old2= atomicMin(&best_[1],old );
  
      if(old2>old){ atomicMin(&best_[2],old2 );}
      if(old2<old) { atomicMin(&best_[2],old );}
  
  }
   if(old<shared_result[threadIdx.x]) {int old2= atomicMin(&best_[1],shared_result[threadIdx.x] );

       if(old2>shared_result[threadIdx.x]){ atomicMin(&best_[2],old2 );}
       if(old2<shared_result[threadIdx.x]) { atomicMin(&best_[2],shared_result[threadIdx.x] );}
  }*/

//if(my_rank==1){
//   if(shared_result[threadIdx.x]!=best_[0]){int old= atomicMin(&best_[1],shared_result[threadIdx.x] ); }//if(old!=shared_result[threadIdx.x]){atomicMin(&best_[2],shared_result[threadIdx.x] );}}
//}
//if(my_rank==1){
 //    atomicMax(&best_[2],shared_result[threadIdx.x] );
//}



}

extern "C"
__global__ void gpu_unprocessed(float * initail_eval, int g1_nb_operation, int g2_nb_operation, float co1, float co2, float ce1, float ce2, int index_g1, int old_size, int * remain_g2, int *  old_opf, int * old_opt, int * adj_mat_g1, int * adj_mat_g2, int * weight_g1, int * weight_g2, float * result, int * best_ , int * nb_, int kbest )
{   //int kbest=100;
    int id = blockIdx.x * blockDim.x + threadIdx.x;
    int offset_remain= id*g2_nb_operation;
    int offset_old=id*g1_nb_operation;
    bool in=false;
      __shared__ int shared_result[1024];
    shared_result[threadIdx.x]=INT_MAX;      
   if(id==0){
      best_[0]=INT_MAX; 
    }



     
    if(id<kbest)
    {

     
  float cost=initail_eval[id];
    
//printf("\n initial cost thread:%d cost:%.2f",id,cost);
/*if(id==0)
{printf("\n opf:%d", index_g1+1);
for (int i=0;i<g2_nb_operation;i++){
 // printf("\neval i:%d  opt:%d ", i, old_opt[i]);
   printf("\nremain i:%d  op:%d ", i, remain_g2[i]);
}
 }*/


int add_old[1000];  int add_ind=0;
for (int l=0;l<g2_nb_operation;l++){
int r_opt= remain_g2[offset_remain+l];
 if(r_opt >=0 && r_opt<= g2_nb_operation)
    {
    cost=cost+co2; 
      float implied_edge_cot=0;
      for (int i=0;i<g1_nb_operation;i++){
        int o_t= old_opt[offset_old +i];
       int x =-1;
        if(o_t>=0){
        x =adj_mat_g2[(r_opt-1)*g2_nb_operation+o_t-1];
       
        if((x>=0)){ {implied_edge_cot=implied_edge_cot+ce2;} }
         // if (id==0) 
         //printf("\n %d opt :%d o_t:%d x:%.2f status:%.2f implied_cost: %.2f cost:%.2f ",blockIdx.x,r_opt,o_t, x , -1, implied_edge_cot,cost);
     }}

     if(add_ind>0) for (int i=0;i<add_ind;i++){
        
        int o_t= add_old[i];
       int x =-1;
        if(o_t>=0){
        x =adj_mat_g2[(r_opt-1)*g2_nb_operation+o_t-1];
       
        if((x>=0)){ {implied_edge_cot=implied_edge_cot+ce2;} }
          //if (id==2*g2_nb_operation) printf("\n node:%d opt :%d o_t:%d x:%.2f status:%.2f implied_cost: %.2f cost:%.2f ",blockIdx.x,opt,o_t, x , status, implied_edge_cot,cost);
     }}

     add_old[add_ind]=r_opt;
     add_ind++;




     cost=cost+implied_edge_cot;
     
  // if(id==0)  printf("\n 2-thread :%d  opt:%d cost:%.2f",threadIdx.x,r_opt,cost );


}
}
//if(id==0)
//printf("\n thread:%d cost:%.2f",id,cost);
result[id]=cost;
shared_result[threadIdx.x]=(int)cost*1000;

}else{
 // result[id]=1000000;
  shared_result[threadIdx.x]=(int)INT_MAX;
}
          
   // if(id==0)printf(" node: %d, inital result:%.2f", blockIdx.x,initail_eval[blockIdx.x] );

    __syncthreads(); 
     // get my local rank 
     int my_rank=0;
     for (int i=0;i<blockDim.x;i++){
     if(shared_result[i]<shared_result[threadIdx.x])my_rank++;
     else if(shared_result[i]==shared_result[threadIdx.x])if(i!=threadIdx.x && i<threadIdx.x)my_rank++; 
     }
    __syncthreads(); 
 //if(my_rank==0||my_rank==1){printf ("\n block:%d idx:%d , rank:%d  value:%d",blockIdx.x,threadIdx.x,my_rank,shared_result[threadIdx.x]);}
if((shared_result[threadIdx.x]<INT_MAX)&&(my_rank==0))
{
 int old=  atomicMin(&best_[0],shared_result[threadIdx.x] ); 
 if(old>shared_result[threadIdx.x]){
 int old_id=atomicExch(&best_[1], id);
 //if(old_id>=0)if(result[old_id]<result[id]){atomicExch(&best_[1], old_id);}
//  best_[1]=id;
  //printf("\n best:%d:ind:%d",shared_result[threadIdx.x]/1000, id);
 }
}

}

__device__ int nb_extra;  
extern "C"
__global__ void sort(float *result,  int*  best_, int * nb_,  int * thx_rank)
{
   int id = blockIdx.x * blockDim.x + threadIdx.x;
   int my_nb=INT_MAX;
   if(id==0)nb_extra=0;
  //if(id==0)printf("\nblock: %d best 1:%d  best 2:%d best 3:%d", blockIdx.x, best_[0], best_[1], best_[2]);
   int my_result=(int) result[id]*1000;
     int l_best_1= best_[0];
   int l_best_2= best_[1];
   int l_best_3=best_[2];
   int l_best_4= best_[3];
   int l_best_5=best_[4];
  int l_best_6= best_[5];
   int l_best_7= best_[6];
   int l_best_8=best_[7];
   int l_best_9= best_[8];
   int l_best_10=best_[9];
   //if(id==0) {nb_[0]=0;nb_[1]=0; nb_[2]=0;nb_[3]=0; nb_[4]=0;}
   //else{   int l_1= best_[0];int l_2= best_[1]; int l_32= best_[1];}
  // if(blockIdx.x==0) printf("\n avant sort lb1 1:%d lb2:%d id:%d my result:%d",l_best_1,l_best_2,id, my_result);


__syncthreads();
   if(my_result<=l_best_1){
   my_nb =  atomicAdd(&nb_[0], 1);
   }
   else if(my_result<=l_best_2){
  my_nb =   atomicAdd(&nb_[1], 1);
   }
   else if(my_result<=l_best_3){
    my_nb =  atomicAdd(&nb_[2], 1);
   }  else if(my_result<=l_best_4){
    my_nb =  atomicAdd(&nb_[3], 1);
   }  else if(my_result<=l_best_5){
    my_nb =  atomicAdd(&nb_[4], 1);
   } else  if(my_result<=l_best_6){
   my_nb =  atomicAdd(&nb_[5], 1);
   }
   else if(my_result<=l_best_7){
  my_nb =   atomicAdd(&nb_[6], 1);
   }
   else if(my_result<=l_best_8){
    my_nb =  atomicAdd(&nb_[7], 1);
   }  else if(my_result<=l_best_9){
    my_nb =  atomicAdd(&nb_[8], 1);
   }  else if(my_result<=l_best_10){
    my_nb =  atomicAdd(&nb_[9], 1);
   }

  thx_rank[id]=my_nb;


//if(id==0)printf("\n best1:%d best2:%d  best3:%d best4:%d best9:%d",l_best_1,l_best_2,l_best_3,l_best_4,l_best_9);

}


extern "C"
__global__ void update_data_1(int index_g1,int const g1_nb_operation,int const g2_nb_operation, int k1,  int * thx_rank, int *  nb_, float * result, int * remain_g2, int * old_opf, int * old_opt, int * temp_remain, int * temp_old_opf, int * temp_old_opt, int * best_, int * start_position)
{ int id = blockIdx.x * blockDim.x + threadIdx.x;
 //if(id==0) {for (int i=0;i<10;i++)printf("\n i:%d best:%d NB:%d", i, best_[i], nb_[i]);}
 int nb_1=nb_[0]; int nb_2=nb_[1]; int nb_3=nb_[2]; int nb_4=nb_[3];int nb_5=nb_[4];
int   my_nb=   thx_rank[id];
 int nb_6=nb_[5]; int nb_7=nb_[6]; int nb_8=nb_[7]; int nb_9=nb_[8];int nb_10=nb_[9];

   int my_result=(int) result[id]*1000;
   int l_best_1= best_[0];
   int l_best_2= best_[1];
   int l_best_3=best_[2];
   int l_best_4= best_[3];
   int l_best_5=best_[4];
   int l_best_6= best_[5];
   int l_best_7= best_[6];
   int l_best_8=best_[7];
   int l_best_9= best_[8];
   int l_best_10= best_[9];
   // if(threadIdx.x==g2_nb_operation-1)if(my_result<=l_best_1)my_result=l_best_1+10;
 
  if(my_result<=l_best_1){
   my_nb =  my_nb;
   }
 else
  if(my_result<=l_best_2){
   my_nb =  my_nb+nb_1;
   }
   else if(my_result<=l_best_3){
  my_nb =   my_nb+nb_1+nb_2;
   }
   else if(my_result<=l_best_4){
 my_nb =   my_nb+nb_1+nb_2+nb_3;
   }  else if(my_result<=l_best_5){
 my_nb =   my_nb+nb_1+nb_2+nb_3+nb_4;
   } 
    else if(my_result<=l_best_6){
   my_nb =  my_nb+nb_1+nb_2+nb_3+nb_4+nb_5;
   }
   else if(my_result<=l_best_7){
  my_nb =   my_nb+nb_1+nb_2+nb_3+nb_4+nb_5+nb_6;
   }
   else if(my_result<=l_best_8){
 my_nb =   my_nb+nb_1+nb_2+nb_3+nb_4+nb_5+nb_6+nb_7;
   }  else if(my_result<=l_best_9){
 my_nb =    my_nb+nb_1+nb_2+nb_3+nb_4+nb_5+nb_6+nb_7+nb_8;
   }  else if(my_result<=l_best_10){
 my_nb =    my_nb+nb_1+nb_2+nb_3+nb_4+nb_5+nb_6+nb_7+nb_8+nb_9;
   } //else if(){ } 

 /*if((3*th_total+id)>INT_MAX)my_nb=INT_MAX-1000;
   } else if(my_result!=INT_MAX0) {
    my_nb=INT_MAX;
//    if((4*th_total+id)>INT_MAX)my_nb=INT_MAX;
   }
//__syncthreads();


//__syncthreads();
 
 */
   int k= k1;
   int node_id=-1; 
 int offset_remain= blockIdx.x*g2_nb_operation;
 int offset_old_f= blockIdx.x*g1_nb_operation;
  temp_remain[id]=remain_g2[id];
int df=(int)(g1_nb_operation/g2_nb_operation)+1;
  for (int i=0;i<df;i++){
      int i_th= i*blockDim.x+threadIdx.x;
    //   printf("\navant if  g1 nb ops:%d  block dim :%d copy done remain i12:%d  temp %d , muli:%d ",  g1_nb_operation,blockDim.x,i_th, temp_old_opt[offset_old_f+i_th],i );
      if(i_th<g1_nb_operation){
        temp_old_opf[offset_old_f+i_th]=old_opf[offset_old_f+i_th];
        temp_old_opt[offset_old_f+i_th]=old_opt[offset_old_f+i_th];
    //    printf("\n g1 nb ops:%d copy done remain i12:%d  temp %d",  g1_nb_operation,i_th, temp_old_opt[offset_old_f+i_th] );
      }
     
      
      __syncthreads();
    }
  /*int my_nb= thx_rank[id];

  int l_nb_1=nb_[0];
  int l_nb_2= nb_[1]; 
    int l_nb_3= nb_[2]; 
  //if(id==0) printf("\n nb1 :%d nb2:%d nb3:%d",l_nb_1, l_nb_2, nb_[2]);
  if (my_nb<=l_nb_1){node_id=my_nb;}
  else if((l_nb_1<k) && ((my_nb-3*th_total)<0) ){
    my_nb=l_nb_1+my_nb-2*th_total; 
    if (my_nb<k){node_id=my_nb;}
  } else if(((l_nb_1+l_nb_2)<k && ((my_nb-4*th_total)<0))){
  my_nb=l_nb_1+l_nb_2+ my_nb-3*th_total;
  if (my_nb<k){node_id=my_nb;}
  }
  else if((l_nb_1+l_nb_2+l_nb_3)<k){
    if((l_nb_1+l_nb_2+l_nb_3+nb_extra)<k&& my_nb!=INT_MAX)
    {
      int nb_e=atomicAdd(&nb_extra,1);
      if(nb_e>0){
    my_nb=l_nb_1+l_nb_2+l_nb_3+ nb_e;}else{my_nb=l_nb_1+l_nb_2+l_nb_3+ nb_extra;}}

*/

  if (my_nb<k){node_id=my_nb;
 // printf("\n extra node id:%d",node_id);
  }
  


  if(node_id<k && node_id>=0){
  thx_rank[id]=node_id;
  start_position[node_id]=blockIdx.x;
   //int opt= remain_g2[offset_remain+ threadIdx.x];
   //  if(node_id==0) 
   //   printf("\nblock:%d thx:%d opt:%d best:%d result:%.2f",blockIdx.x, threadIdx.x,opt,node_id,result[id]);
  }else{ thx_rank[id]=INT_MAX;}

  //if(id==0) printf("\n nb1:%d nb2:%d  nb3:%d nb4:%d nb9:%d",nb_1,nb_2, nb_3, nb_4, nb_9);

}


extern "C"
__global__ void copyVectors(int const g1_nb_operation,int const g2_nb_operation,int * remain_g2, int * old_opf, int * old_opt, int * l_remain, int * l_old_opf, int * l_old_opt, int* startPositions) {


    int id = blockIdx.x * blockDim.x + threadIdx.x; 
    int fr=startPositions[blockIdx.x];
  int node_id=blockIdx.x;//thx_rank[id];
  int offset_remain_f=-1, offset_old_f=-1;
 int offset_remain_t=-1, offset_old_t=-1;
 
  offset_remain_f= fr*g2_nb_operation;
  offset_old_f= fr*g1_nb_operation;
  offset_remain_t= node_id*g2_nb_operation;
  offset_old_t= node_id*g1_nb_operation; 
//
 //for(int i=0;i<g2_nb_operation;i++)
{  remain_g2[offset_remain_t+threadIdx.x]=l_remain[offset_remain_f+threadIdx.x];}

      for (int i=0;i<g1_nb_operation;i=i+blockDim.x){
      if((i+threadIdx.x)<g1_nb_operation){
      old_opf[offset_old_t+i+threadIdx.x]=l_old_opf[offset_old_f+i+threadIdx.x];
      old_opt[offset_old_t+i+threadIdx.x]=l_old_opt[offset_old_f+i+threadIdx.x];}
       }
}


//__device__ int l_remain[6000000];
//__device__ int l_old_opt[6000000];
//__device__ int l_old_opf[6000000];
extern "C"
__global__ void update_data_2(int index_g1,int const g1_nb_operation,int const g2_nb_operation, int k1,  int * thx_rank, int *  nb_, float * result, int * remain_g2, int * old_opf, int * old_opt, float * partial_cost, int * l_remain, int * l_old_opf, int * l_old_opt)
{ int id = blockIdx.x * blockDim.x + threadIdx.x; 
  int node_id=thx_rank[id];
  int offset_remain_f=-1, offset_old_f=-1;
 int offset_remain_t=-1, offset_old_t=-1;
  offset_remain_f= blockIdx.x*g2_nb_operation;
  offset_old_f= blockIdx.x*g1_nb_operation;


//__syncthreads();

 //__shared__ int opt;// remain_g2[offset_remain_f+ threadIdx.x];
  //

 // __shared__ int nb_nodes;
 // __shared__ int pos;
 //__shared__  int done;
int k=k1;
 // if(threadIdx.x==0){nb_nodes=0;done=0;}
//__syncthreads();
 // int my_turn=100000;
  if(node_id<k && node_id>=0){
  //my_turn=  atomicAdd(&nb_nodes,1);
 // if(my_turn<0||my_turn>blockDim.x){my_turn=  atomicAdd(&nb_nodes,1); my_turn--;}
  partial_cost[node_id]= result[id];
 //if(node_id==0) 
  offset_remain_t= node_id*g2_nb_operation;
  offset_old_t= node_id*g1_nb_operation; 
 int opt= l_remain[offset_remain_f+ threadIdx.x];
//
// for(int i=0;i<g2_nb_operation;i++)
//{  remain_g2[offset_remain_t+i]=l_remain[offset_remain_f+i];}

  remain_g2[offset_remain_t+threadIdx.x]=-1;

 //printf("\n thx:%d  block:%d  id:%d  node-id:%d  result:%.2f opt:%d  new val remain:%d " , threadIdx.x, blockIdx.x, id, node_id, result[id], opt,remain_g2[offset_remain_t+threadIdx.x]);
 int done1 =0;
    /*  for (int i=0;i<g1_nb_operation;i++){
      int i_th= i;//*blockDim.x+threadIdx.x;
      old_opf[offset_old_t+i_th]=l_old_opf[offset_old_f+i_th];
      old_opt[offset_old_t+i_th]=l_old_opt[offset_old_f+i_th];
    //  printf("\n thx:%d offset:%d  old opt i:%d :%d", threadIdx.x,offset_old_t, i, old_opt[offset_old_t+i]);
     // if(old_opf[offset_old_t+i_th]<0 &&  done1==0){
        done1++;    }*/
   //
  // printf ("\n node id:%d adding into old block:%d thx: %d opf:%d opt:%d offset:%d",node_id,blockIdx.x,threadIdx.x, index_g1+1,opt, offset_old_t);
     
      old_opf[offset_old_t+index_g1]=index_g1+1;
     //
     if(threadIdx.x==(g2_nb_operation-1)) opt=-1;
     
      old_opt[offset_old_t+index_g1]=opt;

     //if(offset_old_t==0&&node_id==0)  
     //printf("\n node id:%d opf:%d opt:%d",node_id, old_opf[offset_old_t+index_g1], old_opt[offset_old_t+index_g1] );
      //}

        
    

      }
  
}






// if(node_id>=0&&my_nb==99) printf("\n thread:%d my id:%d result:%.2f",id, my_nb, result[id]);




struct ValueIndexPair {
  float value;
  int index;
  // Comparison function for sorting based on value (descending order)
  __device__ bool operator<(const ValueIndexPair& other) const {
    return value > other.value; // Choose '>' for descending order

  }
};


