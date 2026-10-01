// Copyright 2026 Michael S. Gilbert II
// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <Kokkos_Core.hpp>
#include <iostream>
#include <cstdint>
#include "core_types.h"

struct cluster_data {
    using Device = typename matrix_t::device_type;
    using scalar_t = typename matrix_t::value_type;
    using ordinal_t = typename matrix_t::ordinal_type;
    using wgt_vt = Kokkos::View<scalar_t*, Device>;
    using exec_space = typename matrix_t::execution_space;
    using policy_t = Kokkos::RangePolicy<exec_space>;

    // metadata that is preserved between levels in the clustering scheme
    wgt_vt total_deg;
    edge_offset_t uncut = 0;
    edge_offset_t top_nnz = 0;
    double obj = -1.0;
    ordinal_t label_count;

    // metadata needed between local move iterations
    edge_offset_t last_pval = 0;

    // objective scaling
    double lambda = 1.0;

    static edge_offset_t sum(const wgt_vt wdeg){
        edge_offset_t result = 0;
        Kokkos::parallel_reduce("sum view", policy_t(0, wdeg.size()), KOKKOS_LAMBDA(const ordinal_t i, edge_offset_t& update){
            update += wdeg(i);
        }, result);
        return result;
    }

    cluster_data(const matrix_t g, const wgt_vt wdeg, double _lambda) {
        total_deg = wgt_vt("total degree of clusters", g.numRows());
        top_nnz = g.nnz();
        Kokkos::deep_copy(exec_space(), total_deg, wdeg);
        uncut = 0;
        label_count = g.numRows();
        lambda = _lambda;
        update_objective();
    }

    void reset(const matrix_t g, const wgt_vt wdeg) {
        wgt_vt td_lhs = Kokkos::subview(total_deg, std::make_pair((ordinal_t)0, g.numRows()));
        Kokkos::deep_copy(td_lhs, wdeg);
        uncut = 0;
        label_count = g.numRows();
        update_objective();
    }

    void copy(const cluster_data& rhs){
        wgt_vt td_lhs = Kokkos::subview(total_deg, std::make_pair((ordinal_t)0, rhs.label_count));
        wgt_vt td_rhs = Kokkos::subview(rhs.total_deg, std::make_pair((ordinal_t)0, rhs.label_count));
        Kokkos::deep_copy(exec_space(), td_lhs, td_rhs);
        top_nnz = rhs.top_nnz;
        uncut = rhs.uncut;
        obj = rhs.obj;
        label_count = rhs.label_count;
        lambda = rhs.lambda;
    }

    cluster_data(const cluster_data& rhs){
        total_deg = wgt_vt(Kokkos::ViewAllocateWithoutInitializing("total degree of clusters"), rhs.total_deg.extent(0));
        copy(rhs);
    }

    double get_penalty_modifier() const {
        return lambda;
    }

    void update_objective() {
        // avoid implicit capture of "this"
        wgt_vt total = total_deg;
        int64_t square_sum = 0;
        Kokkos::parallel_reduce("sum of squares", policy_t(0, label_count), KOKKOS_LAMBDA(const ordinal_t l, int64_t& update){
            int64_t c_size = total(l);
            update += c_size*c_size;
        }, square_sum);
        double m = uncut;
        m -= lambda * static_cast<double>(square_sum);
        obj = m;
    }

    virtual void print(std::ostream& os) const {
        os << "Objective: " << obj;
    }

    // derived objectives need to apply scaling to obj
    virtual double get_objective() const {
        return obj;
    }

    friend std::ostream& operator<<(std::ostream& os, const cluster_data& cd) {
        os << "Cut: " << (cd.top_nnz - cd.uncut) / 2 << "; ";
        cd.print(os);
        os << "; Labels: " << cd.label_count;
        return os;
    }

    virtual ~cluster_data(){}
};

// these derived classes manage the calculation of lambda and normalizing of the objective
struct modularity : public cluster_data {
    using Device = typename matrix_t::device_type;
    using scalar_t = typename matrix_t::value_type;
    using wgt_vt = Kokkos::View<scalar_t*, Device>;

    double inv_gdeg = 0;

    modularity(const matrix_t g, const wgt_vt wdeg, double _penalty_scale, bool uniform) : cluster_data(g, wdeg, 1.0) {
        edge_offset_t g_deg = 0;
        if(uniform) g_deg = g.nnz();
        else g_deg = cluster_data::sum(wdeg);
        inv_gdeg = 1.0 / static_cast<double>(g_deg);
        cluster_data::lambda = _penalty_scale * inv_gdeg;
    }

    virtual double get_objective() const override {
        return cluster_data::obj * inv_gdeg;
    }

    virtual void print(std::ostream& os) const override {
        os << "Modularity: " << get_objective();
    }

    virtual ~modularity(){}
};

struct constant_potts : public cluster_data {
    using Device = typename matrix_t::device_type;
    using scalar_t = typename matrix_t::value_type;
    using wgt_vt = Kokkos::View<scalar_t*, Device>;

    ordinal_t v_total = 0;

    constant_potts(const matrix_t g, const wgt_vt wdeg, double _penalty_scale) : cluster_data(g, wdeg, 1.0) {
        v_total = g.numRows();
        cluster_data::lambda = _penalty_scale * 0.5;
    }

    virtual double get_objective() const override {
        return cluster_data::obj + cluster_data::lambda*v_total;
    }

    virtual void print(std::ostream& os) const override {
        os << "Constant-Potts: " << get_objective();
    }

    virtual ~constant_potts(){}
};

struct normalized_lcc : public cluster_data {
    using Device = typename matrix_t::device_type;
    using scalar_t = typename matrix_t::value_type;
    using wgt_vt = Kokkos::View<scalar_t*, Device>;

    edge_offset_t g_deg = 0;

    normalized_lcc(const matrix_t g, const wgt_vt wdeg, double _penalty_scale, bool edge_uniform) : cluster_data(g, wdeg, 1.0) {
        if(edge_uniform) g_deg = g.nnz();
        else g_deg = cluster_data::sum(g.values);
        uint64_t v_total = cluster_data::sum(wdeg);
        double denom = static_cast<double>(v_total * v_total);
        cluster_data::lambda = _penalty_scale * static_cast<double>(g_deg) / denom;
    }

    virtual double get_objective() const override {
        return cluster_data::obj / static_cast<double>(g_deg);
    }

    virtual void print(std::ostream& os) const override {
        os << "Normalized LambdaCC: " << get_objective();
    }

    virtual ~normalized_lcc(){}
};