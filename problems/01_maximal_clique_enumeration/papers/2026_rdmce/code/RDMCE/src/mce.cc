#include "mce.h"

const int BOUND = 128;
const size_t VISIT_FLAG = 0xdeadbeef;
struct GroupInfoNode
{
  size_t cur_neighbor;
  size_t next_group_id;
  size_t size;
};
class GroupHelper
{
public:
  GroupHelper()
  {
    groups_.emplace_back(GroupInfoNode());
    groups_[0].cur_neighbor = INF;
    groups_[0].next_group_id = INF;
    groups_[0].size = INF;
  }
  size_t GetCurGroupId(size_t previous_group_id, vid_t cur_neighbor)
  {
    size_t ret_group_id;
    if (groups_[previous_group_id].cur_neighbor == cur_neighbor)
    {
      ret_group_id = groups_[previous_group_id].next_group_id;
      groups_[ret_group_id].size++;
    }
    else
    {
      if (s_.size() == 0)
      {
        ret_group_id = groups_.size();
        groups_.emplace_back(GroupInfoNode());
      }
      else
      {
        ret_group_id = s_.back();
        s_.pop_back();
      }
      groups_[previous_group_id].cur_neighbor = cur_neighbor;
      groups_[previous_group_id].next_group_id = ret_group_id;

      groups_[ret_group_id].cur_neighbor = INF;
      groups_[ret_group_id].next_group_id = INF;
      groups_[ret_group_id].size = 1;
    }
    if (--groups_[previous_group_id].size == 0)
      s_.push_back(previous_group_id);
    return ret_group_id;
  }
  bool IsFirst(size_t group_id)
  {
    bool ret = groups_[group_id].cur_neighbor != VISIT_FLAG;
    groups_[group_id].cur_neighbor = VISIT_FLAG;
    return ret;
  }

private:
  std::vector<GroupInfoNode> groups_;
  std::vector<size_t> s_;
};

void MceSolver::Solve(MceAlgorithm algo)
{
  printf("BOUND = %d\n", BOUND);
  timer_.Start();
  for (vid_t v0 = 0; v0 < g_.GetNumVertices(); v0++)
  {
    vlist_t R, P, X;
    R.emplace_back(v0);
    for (vid_t v1 : g_.N(v0))
    {
      if (v0 > v1)
        X.emplace_back(v1);
      else
        P.emplace_back(v1);
    }
    if (P.empty())
    {
      if (X.empty())
        IncrementMceCount();
      continue;
    }
    if (algo == MceAlgorithm::BKPivot)
      BKPivot(R, P, X);
    else if (algo == MceAlgorithm::BKFixedMem)
      BKFixedMem(R, P, X);
    else if (algo == MceAlgorithm::BKFixedMemPivot)
      BKFixedMemPivot(R, P, X);
    else if (algo == MceAlgorithm::BKFixedMemPivotLn)
      BKFixedMemPivotLn(R, P, X);
    else if (algo == MceAlgorithm::BKFixedMemPivotBit)
      BKFixedMemPivotBit2(R, P, X);

    // for (vid_t v1 : g_.N(v0))
    // {
    //   if (v0 > v1)
    //     continue;
    //   vlist_t cand;
    //   std::set_intersection(g_.N(v0).begin(), g_.N(v0).end(), g_.N(v1).begin(), g_.N(v1).end(), std::back_inserter(cand));
    //   vlist_t R, P, X;
    //   R.emplace_back(v0);
    //   R.emplace_back(v1);
    //   for (auto c : cand)
    //   {
    //     if (c > v1)
    //       P.emplace_back(c);
    //     else
    //       X.emplace_back(c);
    //   }
    //   if (P.empty())
    //   {
    //     if (X.empty())
    //       IncrementMceCount();
    //     continue;
    //   }
    //   if (X.size() > (P.size() + 1) * 16)
    //     X = std::move(Partition(P, X));

    //   if (algo == MceAlgorithm::BKPivot)
    //     BKPivot(R, P, X);
    //   else if (algo == MceAlgorithm::BKFixedMem)
    //     BKFixedMem(R, P, X);
    //   else if (algo == MceAlgorithm::BKFixedMemPivot)
    //     BKFixedMemPivot(R, P, X);
    //   else if (algo == MceAlgorithm::BKFixedMemPivotLn)
    //     BKFixedMemPivotLn(R, P, X);
    //   else if (algo == MceAlgorithm::BKFixedMemPivotBit)
    //     BKFixedMemPivotBit2(R, P, X);
    // }
  }
  timer_.Stop();
  // std::cout << "Total time: " << timer_.Elapsed() << "s" << std::endl;
  // std::cout << "Bit time: " << debug_timer_.Elapsed() << "s" << std::endl;
}

void MceSolver::BKPivot(vlist_t &R, vlist_t &P, vlist_t &X, std::function<void(vlist_t &, vlist_t &, vlist_t &)> callback,
                        size_t bound)
{
  if (P.empty())
  {
    if (X.empty())
    {
      IncrementMceCount();
    }
    return;
  }

  if (callback != nullptr && P.size() <= bound)
  {
    callback(R, P, X);
    return;
  }

  vid_t pivot = P[0];
  size_t max_neighbors = 0;

  for (auto v : P)
  {
    size_t neighbors_count = SetIntersectionCount(g_.N(v), P);
    if (neighbors_count > max_neighbors)
    {
      max_neighbors = neighbors_count;
      pivot = v;
    }
  }
  for (auto v : X)
  {
    size_t neighbors_count = SetIntersectionCount(g_.N(v), P);
    if (neighbors_count > max_neighbors)
    {
      max_neighbors = neighbors_count;
      pivot = v;
    }
  }

  vlist_t P_cand;
  std::set_difference(P.begin(), P.end(), g_.N(pivot).begin(), g_.N(pivot).end(),
                      std::back_inserter(P_cand));

  for (auto vp : P_cand)
  {
    vlist_t R1, P1, X1;
    R1 = R;
    R1.emplace_back(vp); // out of order
    const vlist_t &Nvp = g_.N(vp);
    std::set_intersection(P.begin(), P.end(), Nvp.begin(), Nvp.end(),
                          std::back_inserter(P1));
    std::set_intersection(X.begin(), X.end(), Nvp.begin(), Nvp.end(),
                          std::back_inserter(X1));
    BKPivot(R1, P1, X1, callback, bound);
    P.erase(std::find(P.begin(), P.end(), vp));
    auto it = std::lower_bound(X.begin(), X.end(), vp);
    X.insert(it, vp);
  }
}

void MceSolver::BKFixedMem(vlist_t &R, vlist_t &P, vlist_t &X)
{
  std::vector<VertexMce> RPX;
  for (auto v : R)
    RPX.emplace_back(VertexMce(v, STATE_R));
  for (auto v : P)
    RPX.emplace_back(VertexMce(v, STATE_P));
  for (auto v : X)
    RPX.emplace_back(VertexMce(v, STATE_X));
  std::sort(RPX.begin(), RPX.end());
  size_t level = 1;
  while (level > 0)
  {
    bool has_p = false, has_x = false;
    vid_t vp;
    for (auto &v : RPX)
    {
      if (v.IsP())
      {
        has_p = true;
        vp = v.v_;
        v.Update(EVENT_SET_R, level);
        break;
      }
      else if (v.IsX())
      {
        has_x = true;
      }
    }

    if (has_p)
    {
      auto &neighbors = g_.N(vp);
      int i = 0, j = 0;
      while (i < RPX.size() && j < neighbors.size())
      {
        if (RPX[i].v_ == neighbors[j])
        {
          i++;
          j++;
        }
        else if (RPX[i].v_ < neighbors[j])
        {
          RPX[i].Update(EVENT_SET_E, level);
          i++;
        }
        else
        {
          j++;
        }
      }
      while (i < RPX.size())
      {
        RPX[i].Update(EVENT_SET_E, level);
        i++;
      }
      level++;
    }
    else
    {
      if (!has_x)
      {
        IncrementMceCount();
      }
      level--;
      for (auto &v : RPX)
        v.Update(EVENT_RESTORE_AUTO, level);
    }
  }
}

void MceSolver::BKFixedMemPivot(vlist_t &R, vlist_t &P, vlist_t &X)
{
  auto SelectPivot = [&](const vlist_t &P, const vlist_t &X) -> vid_t
  {
    assert(!P.empty());
    vid_t pivot = P[0];
    size_t max_neighbors = 0;
    for (auto v : P)
    {
      size_t neighbors_count = SetIntersectionCount(g_.N(v), P);
      if (neighbors_count > max_neighbors)
      {
        max_neighbors = neighbors_count;
        pivot = v;
      }
    }
    for (auto v : X)
    {
      size_t neighbors_count = SetIntersectionCount(g_.N(v), P);
      if (neighbors_count > max_neighbors)
      {
        max_neighbors = neighbors_count;
        pivot = v;
      }
    }

    return pivot;
  };

  if (P.empty())
  {
    if (X.empty())
    {
      IncrementMceCount();
    }
    return;
  }
  std::vector<VertexMce> RPX;
  for (auto v : R)
    RPX.emplace_back(VertexMce(v, STATE_R));
  for (auto v : P)
    RPX.emplace_back(VertexMce(v, STATE_P));
  for (auto v : X)
    RPX.emplace_back(VertexMce(v, STATE_X));
  std::sort(RPX.begin(), RPX.end());
  size_t level = 1;

  vid_t pivot;
  vlist_t pivot_stack, P_buffer, X_buffer;

  pivot = SelectPivot(P, X);
  pivot_stack.emplace_back(pivot);

  while (level > 0)
  {
    bool has_p = false, has_x = false, has_vp = false;
    vid_t vp;

    pivot = pivot_stack[level - 1];
    auto iter_cur = g_.N(pivot).begin();
    auto iter_end = g_.N(pivot).end();

    for (auto &v : RPX)
    {
      if (v.IsP())
      {
        has_p = true;
        while (iter_cur != iter_end && *iter_cur < v.v_)
          iter_cur++;
        if (iter_cur == iter_end || *iter_cur > v.v_)
        {
          has_vp = true;
          vp = v.v_;
          v.Update(EVENT_SET_R, level);
          break;
        }
      }
      else if (v.IsX())
      {
        has_x = true;
      }
    }

    if (has_vp)
    {
      auto &neighbors = g_.N(vp);
      int i = 0, j = 0;

      while (i < RPX.size() && j < neighbors.size())
      {
        if (RPX[i].v_ == neighbors[j])
        {
          i++;
          j++;
        }
        else if (RPX[i].v_ < neighbors[j])
        {
          RPX[i].Update(EVENT_SET_E, level);
          i++;
        }
        else
        {
          j++;
        }
      }
      while (i < RPX.size())
      {
        RPX[i].Update(EVENT_SET_E, level);
        i++;
      }

      P_buffer.clear();
      X_buffer.clear();
      for (auto &v : RPX)
      {
        if (v.IsP())
          P_buffer.emplace_back(v.v_);
        else if (v.IsX())
          X_buffer.emplace_back(v.v_);
      }

      pivot = (P_buffer.empty()) ? 0 : SelectPivot(P_buffer, X_buffer);
      pivot_stack.emplace_back(pivot);

      level++;
    }
    else
    {
      if (!has_x && !has_p)
      {
        IncrementMceCount();
      }
      level--;
      if (pivot_stack.size() > level)
        pivot_stack.pop_back();
      for (auto &v : RPX)
        v.Update(EVENT_RESTORE_AUTO, level);
    }
  }
}

class VertexMceExt : public VertexMce
{
public:
  union
  {
    size_t local_neighbors;
    uint64_t global_neighbors;
  };
  VertexMceExt(vid_t v, VertexState state) : VertexMce(v, state) {}
};

void MceSolver::BKFixedMemPivotLn(vlist_t &R, vlist_t &P, vlist_t &X)
{

  if (P.empty())
  {
    if (X.empty())
    {
      IncrementMceCount();
    }
    return;
  }

  std::vector<VertexMceExt> RPX;
  vlist_t pivot_stack;
  for (auto v : X)
    RPX.emplace_back(VertexMceExt(v, STATE_X));
  for (auto v : R)
    RPX.emplace_back(VertexMceExt(v, STATE_R));
  for (auto v : P)
    RPX.emplace_back(VertexMceExt(v, STATE_P));

  auto SelectPivotLn = [&]() -> vid_t
  {
    vid_t pivot = 0;
    size_t max_neighbors = 0;

    for (auto &v : RPX)
      v.local_neighbors = 0;
    for (auto &v : RPX)
    {
      if (v.IsP())
      {
        if (max_neighbors == 0)
          pivot = v.v_;
        int i = 0, j = 0;
        while (i < RPX.size() && j < g_.N(v.v_).size())
        {
          if (RPX[i].v_ == g_.N(v.v_)[j])
          {
            if (RPX[i].IsP() || RPX[i].IsX())
            {
              size_t ln = ++RPX[i].local_neighbors;
              if (ln > max_neighbors)
              {
                max_neighbors = ln;
                pivot = RPX[i].v_;
              }
            }
            i++;
            j++;
          }
          else if (RPX[i].v_ < g_.N(v.v_)[j])
            i++;
          else
            j++;
        }
      }
    }
    return pivot;
  };

  size_t level = 1;

  vid_t pivot = SelectPivotLn();
  pivot_stack.emplace_back(pivot);

  while (level > 0)
  {
    bool has_p = false, has_x = false, has_vp = false;
    vid_t vp;

    pivot = pivot_stack[level - 1];

    auto iter_cur = g_.N(pivot).begin();
    auto iter_end = g_.N(pivot).end();

    for (auto &v : RPX)
    {
      if (v.IsP())
      {
        has_p = true;
        while (iter_cur != iter_end && *iter_cur < v.v_)
          iter_cur++;
        if (iter_cur == iter_end || *iter_cur > v.v_)
        {
          has_vp = true;
          vp = v.v_;
          v.Update(EVENT_SET_R, level);
          break;
        }
      }
      else if (v.IsX())
      {
        has_x = true;
      }
    }

    if (has_vp)
    {
      auto &neighbors = g_.N(vp);
      int i = 0, j = 0;

      while (i < RPX.size() && j < neighbors.size())
      {
        if (RPX[i].v_ == neighbors[j])
        {
          i++;
          j++;
        }
        else if (RPX[i].v_ < neighbors[j])
        {
          RPX[i].Update(EVENT_SET_E, level);
          i++;
        }
        else
        {
          j++;
        }
      }
      while (i < RPX.size())
      {
        RPX[i].Update(EVENT_SET_E, level);
        i++;
      }

      pivot = SelectPivotLn();
      pivot_stack.emplace_back(pivot);
      level++;
    }
    else
    {
      if (!has_x && !has_p)
      {
        IncrementMceCount();
      }
      level--;
      if (pivot_stack.size() > level)
        pivot_stack.pop_back();
      for (auto &v : RPX)
        v.Update(EVENT_RESTORE_AUTO, level);
    }
  }
}

void MceSolver::BKFixedMemBit(vlist_t &R, vlist_t &P, vlist_t &X)
{
  if (P.size() > 64 || P.empty())
  {
    BKPivot(R, P, X, [this](vlist_t &r, vlist_t &p, vlist_t &x)
            { this->BKFixedMemBit(r, p, x); }, 64);
    return;
  }
  auto IntersectToBitmap = [&](const vlist_t &P, const vlist_t &V)
  {
    assert(P.size() <= 64);
    uint64_t bitmap = 0;
    int i = 0, j = 0;
    while (i < P.size() && j < V.size())
    {
      if (P[i] == V[j])
      {
        bitmap |= (1 << (P.size() - 1 - i));
        i++;
        j++;
      }
      else if (P[i] < V[j])
      {
        i++;
      }
      else
      {
        j++;
      }
    }
    return bitmap;
  };
  std::vector<uint64_t> bitmaps;
  for (auto v : P)
    bitmaps.emplace_back(IntersectToBitmap(P, g_.N(v)));
  for (auto v : X)
    bitmaps.emplace_back(IntersectToBitmap(P, g_.N(v)));
  uint64_t r_bit = 1 << (P.size() - 1); // Init R

  while (r_bit > 0)
  {
    // Check whether R is valid
    uint64_t lsb = r_bit & -r_bit;
    uint64_t r_bit_orig = r_bit - lsb;
    uint64_t pid = P.size() - __builtin_ctzll(lsb) - 1;

    bool backtrack = true;
    if ((bitmaps[pid] & r_bit_orig) == r_bit_orig) // R is valid
    {
      for (pid = pid + 1; pid < P.size(); pid++)
      {
        if ((bitmaps[pid] & r_bit) == r_bit)
        {
          backtrack = false;
          r_bit = r_bit | (1 << (P.size() - pid - 1));
          break;
        }
      }

      if (backtrack) // P is empty
      {
        bool is_maximal = true;
        for (auto bit : bitmaps)
        {
          if ((bit & r_bit) == r_bit)
          {
            is_maximal = false;
            break;
          }
        }
        if (is_maximal)
        {
          IncrementMceCount();
        }
      }
    }

    if (backtrack)
    {
      uint64_t lsb = r_bit & -r_bit;
      uint64_t r_bit_orig = r_bit - lsb;
      if (lsb > 1)
        r_bit = r_bit_orig + (lsb >> 1);
      else if (r_bit_orig == 0)
        r_bit = 0;
      else
      {
        r_bit = r_bit_orig;
        lsb = r_bit & -r_bit;
        r_bit = r_bit - lsb + (lsb >> 1);
      }
    }
  }
}

template <typename T = uint64_t>
class BitVectorAllocater;

template <typename T = uint64_t>
class BitVec
{
private:
  const BitVectorAllocater<T> &allocator;
  T *data;

public:
  BitVec() = delete;
  BitVec(const BitVectorAllocater<T> &allocator, T *data) : allocator(allocator), data(data) {}

  // Bit operations
  void Intersect(const BitVec<T> &src1, const BitVec<T> &src2)
  {
    for (size_t i = 0; i < allocator.sizeOfItem; ++i)
      data[i] = src1.data[i] & src2.data[i];
  }
  void Difference(const BitVec<T> &src1, const BitVec<T> &src2)
  {
    for (size_t i = 0; i < allocator.sizeOfItem; ++i)
    {
      data[i] = src1.data[i] & ~src2.data[i];
    }
  }

  size_t IntersectCount(const BitVec<T> &other) const
  {
    size_t count = 0;
    for (size_t i = 0; i < allocator.sizeOfItem; ++i)
    {
      count += __builtin_popcountll(static_cast<unsigned long long>(data[i] & other.data[i]));
    }
    return count;
  }

  bool IsSubset(const BitVec<T> &other) const
  {
    for (size_t i = 0; i < allocator.sizeOfItem; ++i)
      if ((data[i] & ~other.data[i]) != 0)
        return false;
    return true;
  }
  size_t CountBits() const
  {
    size_t count = 0;
    for (size_t i = 0; i < allocator.sizeOfItem; ++i)
    {
      count += __builtin_popcountll(static_cast<unsigned long long>(data[i]));
    }
    return count;
  }
  void SetBit(size_t idx)
  {
    size_t block = idx / (sizeof(T) * 8);
    size_t offset = idx % (sizeof(T) * 8);
    data[block] |= (static_cast<T>(1) << offset);
  }
  void ResetBit(size_t idx)
  {
    size_t block = idx / (sizeof(T) * 8);
    size_t offset = idx % (sizeof(T) * 8);
    data[block] &= ~(static_cast<T>(1) << offset);
  }
  size_t FindFirstSetBit() const
  {
    for (size_t i = 0; i < allocator.sizeOfItem; ++i)
    {
      if (data[i] != 0)
      {
        return i * sizeof(T) * 8 + __builtin_ctzll(static_cast<unsigned long long>(data[i]));
      }
    }
    return INF;
  }

  void SetFullMask()
  {
    size_t remaining_bits = allocator.itemPerVec;
    for (size_t i = 0; i < allocator.sizeOfItem; ++i)
    {
      if (remaining_bits >= sizeof(T) * 8)
      {
        data[i] = ~static_cast<T>(0); // 全为1
        remaining_bits -= sizeof(T) * 8;
      }
      else
      {
        data[i] = (static_cast<T>(1) << remaining_bits) - 1; // 部分为1
        break;
      }
    }
  }
};

template <typename T>
class BitVectorAllocater
{
private:
  size_t bvCount;
  std::vector<T> memory;

public:
  const size_t itemPerVec;
  const size_t sizeOfItem;
  BitVectorAllocater() = delete;
  BitVectorAllocater(size_t items) : itemPerVec(items),
                                     sizeOfItem((items + sizeof(T) * 8 - 1) / (sizeof(T) * 8)),
                                     bvCount(0) {}
  ~BitVectorAllocater() { memory.clear(); }
  // Insert
  BitVec<T> PushBack()
  {
    for (size_t i = 0; i < sizeOfItem; i++)
      memory.emplace_back((T)0ULL);
    bvCount++;
    return BitVec<T>(*this, &memory[(bvCount - 1) * sizeOfItem]);
  }

  BitVec<T> PushBackCopy()
  {
    for (size_t i = 0; i < sizeOfItem; i++)
    {
      memory.emplace_back(memory[(bvCount - 1) * sizeOfItem + i]);
    }
    bvCount++;
    return BitVec<T>(*this, &memory[(bvCount - 1) * sizeOfItem]);
  }

  BitVec<T> PushBackBySetIntersection(const vlist_t &P, const vlist_t &V)
  {
    BitVec<T> bv = PushBack();
    int i = 0, j = 0;
    while (i < P.size() && j < V.size())
    {
      if (P[i] == V[j])
      {
        bv.SetBit(i);
        i++;
        j++;
      }
      else if (P[i] < V[j])
      {
        i++;
      }
      else
      {
        j++;
      }
    }
    // for (size_t i = 0; i < P.size(); i++)
    // {
    //   auto it = std::find(V.begin(), V.end(), P[i]);
    //   if (it != V.end())
    //     bv.SetBit(i);
    // }
    return bv;
  }

  // Delete
  void PopBack()
  {
    for (size_t i = 0; i < sizeOfItem; i++)
      memory.pop_back();
    bvCount--;
  }
  // Select
  BitVec<T> GetVecByIdx(size_t idx)
  {
    assert(idx < bvCount);
    return BitVec<T>(*this, &memory[idx * sizeOfItem]);
  }

  BitVec<T> Back()
  {
    assert(bvCount > 0);
    return BitVec<T>(*this, &memory[(bvCount - 1) * sizeOfItem]);
  }

  size_t Size() { return bvCount; }
};

void MceSolver::BKFixedMemPivotBit(vlist_t &R, vlist_t &P, vlist_t &X)
{
  if (P.size() > BOUND || P.empty())
  {
    BKPivot(R, P, X, [this](vlist_t &r, vlist_t &p, vlist_t &x)
            { this->BKFixedMemPivotBit(r, p, x); }, BOUND);
    return;
  }

  BitVectorAllocater bitmaps(P.size());
  for (auto v : P)
    bitmaps.PushBackBySetIntersection(P, g_.N(v));
  for (auto v : X)
    bitmaps.PushBackBySetIntersection(P, g_.N(v));
  BitVectorAllocater rrs(P.size());
  BitVectorAllocater pps(P.size());
  BitVectorAllocater pp_masks(P.size());
  BitVectorAllocater local_values(P.size());
  local_values.PushBack();

  auto PivotMask = [&]()
  {
    pp_masks.PushBack();
    size_t mask_bits = 0;
    for (int i = 0; i < bitmaps.Size(); i++)
    {
      if (rrs.Back().IsSubset(bitmaps.GetVecByIdx(i)))
      {
        size_t tmp_bits = pps.Back().IntersectCount(bitmaps.GetVecByIdx(i));
        if (tmp_bits > mask_bits)
        {
          pp_masks.Back().Intersect(pps.Back(), bitmaps.GetVecByIdx(i));
          mask_bits = tmp_bits;
        }
      }
    }
  };

  rrs.PushBack();
  pps.PushBack();
  pps.Back().SetFullMask();
  PivotMask();

  while (rrs.Size() != 0)
  {
    auto valid_p_bit = local_values.Back();
    valid_p_bit.Difference(pps.Back(), pp_masks.Back());
    if (valid_p_bit.CountBits() == 0)
    {
      bool is_maximal = true;
      for (int i = 0; i < bitmaps.Size(); i++)
      {
        if (rrs.Back().IsSubset(bitmaps.GetVecByIdx(i)))
        {
          is_maximal = false;
          break;
        }
      }
      if (is_maximal)
      {
        IncrementMceCount();
      }
      rrs.PopBack();
      pps.PopBack();
      pp_masks.PopBack();
    }
    else
    {
      vid_t pivot = valid_p_bit.FindFirstSetBit();
      pps.Back().ResetBit(pivot);
      rrs.PushBackCopy().SetBit(pivot);
      pps.PushBackCopy();
      pps.Back().Intersect(pps.Back(), bitmaps.GetVecByIdx(pivot));
      PivotMask();
    }
  }
}

void MceSolver::BKFixedMemPivotBit2(vlist_t &R, vlist_t &P, vlist_t &X)
{
  if (P.size() > BOUND || P.empty())
  {
    BKPivot(R, P, X, [this](vlist_t &r, vlist_t &p, vlist_t &x)
            { this->BKFixedMemPivotBit2(r, p, x); }, BOUND);
    return;
  }

  std::vector<uint64_t> bitmaps;
  size_t itemPerVec = P.size();
  size_t sizeOfItem = (itemPerVec + 63) / 64;

  // Set bitmaps
  for (int i = 0; i < P.size() + X.size(); i++)
  {
    vid_t v = i < P.size() ? P[i] : X[i - P.size()];
    for (int j = 0; j < sizeOfItem; j++)
      bitmaps.emplace_back(0ULL);
    size_t start_id = bitmaps.size() - sizeOfItem;
    size_t vid = 0, pid = 0;
    bool is_connected = false;
    while (vid < g_.N(v).size() && pid < P.size())
    {
      if (g_.N(v)[vid] == P[pid])
      {
        is_connected = true;
        bitmaps[start_id + pid / 64] |= (1ULL << (pid % 64));
        vid++;
        pid++;
      }
      else if (g_.N(v)[vid] < P[pid])
        vid++;
      else
        pid++;
    }
    // if (!is_connected)
    // {
    //   for (int j = 0; j < sizeOfItem; j++)
    //     bitmaps.pop_back();
    // }
  }

  // for (int i = 0; i < P.size() + X.size(); i++)
  // {
  //   if (i < P.size())
  //     printf("\033[32m%04llx\033[39m ", bitmaps[i]);
  //   else
  //     printf("\033[30m%04llx\033[39m ", bitmaps[i]);
  // }
  // printf("\n");

  size_t sizeOfBitmaps = bitmaps.size() / sizeOfItem;

  // if (sizeOfBitmaps > 2048)
  // {
  //   std::cout << "sizeOfBitmaps: " << sizeOfBitmaps << " P size: " << P.size() << std::endl;
  //   return;
  // }

  std::vector<uint64_t> rrs, pps, vpps;
  auto GetValidPByPivot = [&]()
  {
    vid_t pivot_id = 0;
    size_t max_neighbors = 0;
    for (int i = 0; i < sizeOfBitmaps; i++)
    {
      size_t cur_neighbors = 0;
      for (int j = 0; j < sizeOfItem; j++)
      {
        if ((rrs[rrs.size() - sizeOfItem + j] & ~bitmaps[i * sizeOfItem + j]) != 0ULL)
        {
          cur_neighbors = 0;
          break;
        }
        cur_neighbors += __builtin_popcountll(bitmaps[i * sizeOfItem + j] & pps[pps.size() - sizeOfItem + j]);
      }
      if (cur_neighbors > max_neighbors)
      {
        max_neighbors = cur_neighbors;
        pivot_id = i;
      }
    }
    for (int j = 0; j < sizeOfItem; j++)
    {
      if (max_neighbors == 0)
        vpps.emplace_back(pps[pps.size() - sizeOfItem + j]);
      else
        vpps.emplace_back(pps[pps.size() - sizeOfItem + j] & ~bitmaps[pivot_id * sizeOfItem + j]);
    }
  };

  for (int i = 0; i < sizeOfItem; i++)
  {
    rrs.emplace_back(0ULL);
    if (64 * i + 64 < P.size())
      pps.emplace_back(~0ULL);
    else
      pps.emplace_back((~0ULL) >> (64 - P.size() % 64));
  }
  GetValidPByPivot();

  while (!rrs.empty())
  {
    size_t pid = INF;
    for (int i = 0; i < sizeOfItem; i++)
    {
      if (vpps[vpps.size() - sizeOfItem + i] != 0ULL)
      {
        pid = i * 64 + __builtin_ctzll(vpps[vpps.size() - sizeOfItem + i]);
        break;
      }
    }
    if (pid == INF)
    {
      bool is_maximal = true;
      for (int i = 0; i < sizeOfBitmaps; i++)
      {
        int j;
        for (j = 0; j < sizeOfItem; j++)
          if ((rrs[rrs.size() - sizeOfItem + j] & ~bitmaps[i * sizeOfItem + j]) != 0ULL)
            break;
        if (j == sizeOfItem)
        {
          is_maximal = false;
          break;
        }
      }
      if (is_maximal)
        IncrementMceCount();
      for (int j = 0; j < sizeOfItem; j++)
      {
        rrs.pop_back();
        pps.pop_back();
        vpps.pop_back();
      }
    }
    else
    {
      pps[pps.size() - sizeOfItem + pid / 64] &= ~(1ULL << (pid % 64));
      vpps[pps.size() - sizeOfItem + pid / 64] &= ~(1ULL << (pid % 64));
      for (int j = 0; j < sizeOfItem; j++)
      {
        rrs.emplace_back(rrs[rrs.size() - sizeOfItem]);
        pps.emplace_back(pps[pps.size() - sizeOfItem] & bitmaps[pid * sizeOfItem + j]);
      }
      rrs[rrs.size() - sizeOfItem + pid / 64] |= (1ULL << (pid % 64));
      GetValidPByPivot();
    }
  }
}

void MceSolver::BKMixed(vlist_t &R, vlist_t &P, vlist_t &X)
{
  if (P.empty())
  {
    if (X.empty())
      IncrementMceCount();
  }
  else if (P.size() < BOUND)
    BKFixedMemPivotBit2(R, P, X);
  else
  {
  }
}

vlist_t MceSolver::Partition(const vlist_t &P, const vlist_t &X)
{
  vlist_t X_prime;
  vlist_t group_array(X.size(), 0);
  GroupHelper g_helper;
  for (auto vp : P)
  {
    size_t x_id = 0;
    for (auto vp_neighbor : g_.N(vp))
    {
      while (x_id < X.size() && vp_neighbor > X[x_id])
        x_id++;
      if (x_id == X.size())
        break;
      if (X[x_id] == vp_neighbor)
        group_array[x_id] = g_helper.GetCurGroupId(group_array[x_id], vp);
    }
  }
  for (int i = 0; i < X.size(); i++)
  {
    if (g_helper.IsFirst(group_array[i]))
      X_prime.emplace_back(X[i]);
  }
  return X_prime;
}

// void MceSolver::BKFixedMemPivotBit(vlist_t &R, vlist_t &P, vlist_t &X)
// {

//   if (P.size() > BOUND || P.empty())
//   {
//     BKPivot(R, P, X, [this](vlist_t &r, vlist_t &p, vlist_t &x)
//             { this->BKFixedMemPivotBit(r, p, x); }, BOUND);
//     return;
//   }

//   auto IntersectToBitmap = [&](const vlist_t &P, const vlist_t &V)
//   {
//     assert(P.size() <= 64);
//     uint64_t bitmap = 0;
//     int i = 0, j = 0;
//     while (i < P.size() && j < V.size())
//     {
//       if (P[i] == V[j])
//       {
//         bitmap |= (1ULL << (P.size() - 1 - i));
//         i++;
//         j++;
//       }
//       else if (P[i] < V[j])
//       {
//         i++;
//       }
//       else
//       {
//         j++;
//       }
//     }
//     return bitmap;
//   };

//   std::vector<uint64_t> bitmaps;
//   size_t p_size = P.size();

// #define CHECK_BOUND 10
//   if (P.size() <= CHECK_BOUND)
//   {
//     uint64_t check_bit[1ULL << (CHECK_BOUND - 6)];
//     for (size_t i = 0; i < (1ULL << (CHECK_BOUND - 6)); i++)
//       check_bit[i] = 0ULL;
//     for (auto v : P)
//     {
//       auto bit = IntersectToBitmap(P, g_.N(v));
//       bitmaps.emplace_back(bit);
//     }
//     for (auto v : X)
//     {
//       auto bit = IntersectToBitmap(P, g_.N(v));
//       if ((check_bit[bit >> 6] & (1ULL << (bit & 63))) == 0ULL)
//       {
//         bitmaps.emplace_back(bit);
//         check_bit[bit >> 6] |= (1ULL << (bit & 63));
//       }
//     }
//   }
//   else
//   {
//     for (auto v : P)
//       bitmaps.emplace_back(IntersectToBitmap(P, g_.N(v)));
//     for (auto v : X)
//       bitmaps.emplace_back(IntersectToBitmap(P, g_.N(v)));
//   }

//   auto PivotMask = [&](uint64_t r_bit, uint64_t p_bit)
//   {
//     uint64_t mask = 0;
//     for (auto &bit : bitmaps)
//     {
//       if ((r_bit & bit) == r_bit)
//       {
//         uint64_t tmp = p_bit & bit;
//         if (CountBit(tmp) > CountBit(mask))
//           mask = tmp;
//       }
//     }
//     return mask;
//   };

//   std::vector<uint64_t> rrs, pps, pp_masks;

//   rrs.emplace_back(0ULL);
//   pps.emplace_back((~0ULL) >> (64 - p_size));
//   pp_masks.emplace_back(PivotMask(0ULL, (~0ULL) >> (64 - p_size)));
//   while (!pps.empty())
//   {
//     uint64_t &r_bit = rrs.back();
//     uint64_t &p_bit = pps.back();
//     uint64_t &pp_mask = pp_masks.back();
//     uint64_t valid_p_bit = p_bit & (~pp_mask);

//     if (valid_p_bit == 0ULL) // vp is empty
//     {
//       bool is_maximal = true;
//       for (auto bit : bitmaps)
//       {
//         if ((r_bit & bit) == r_bit)
//         {
//           is_maximal = false;
//           break;
//         }
//       }
//       if (is_maximal)
//       {
//         IncrementMceCount();
//       }

//       rrs.pop_back();
//       pps.pop_back();
//       pp_masks.pop_back();
//     }
//     else
//     {
//       uint64_t vp_hot = valid_p_bit & -valid_p_bit;
//       uint64_t vp_id = p_size - __builtin_ctzll(vp_hot) - 1;
//       p_bit = p_bit & (~vp_hot);
//       uint64_t next_r = r_bit | vp_hot;
//       uint64_t next_p = p_bit & bitmaps[vp_id];
//       uint64_t next_pp_mask = PivotMask(next_r, next_p);
//       rrs.emplace_back(next_r);
//       pps.emplace_back(next_p);
//       pp_masks.emplace_back(next_pp_mask);
//     }
//   }
// }
