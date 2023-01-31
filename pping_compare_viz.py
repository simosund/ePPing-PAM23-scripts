#!/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
import matplotlib.pyplot as plt
import argparse

import process_data as prodat
import common_plotting as complot
import sar_cpu_viz


def plot_network_throughput(interface_dfs, axes=None, **kwargs):
    axes = complot.plot_pergroup_timeseries(interface_dfs, "txbps", axes=axes,
                                            stat_kwargs={"fmt": "{:.3e}"},
                                            **kwargs)
    _, ymax = axes.get_ylim()
    axes.set_ylim(0, 1.05*ymax)
    axes.set_ylabel("Throughput (bps)")
    axes.set_xlabel("Time (s)")


def plot_pping_output(pping_data, axes=None, grid=True, legend=True):
    if axes is None:
        axes = plt.gca()

    axes.plot([], [])  # Use up first color cycle
    complot.plot_pergroup_timeseries(pping_data, "rtt_events", legend=False)

    filt_pping_data = {pping + " filtered": data for pping, data in
                       pping_data.items() if "filtered_rtt_events" in data}
    if len(filt_pping_data) > 0:
        axes.set_prop_cycle(None)  # Reset color cycle
        axes.plot([], [])  # Use up first color cycle
        complot.plot_pergroup_timeseries(filt_pping_data, "filtered_rtt_events",
                                         ls="--", legend=False)

    axes.set_ylim(0)
    axes.set_xlabel("Time (s)")
    axes.set_ylabel("Events per second")
    axes.grid(grid)
    if legend:
        axes.legend()

    return axes


def plot_comparsion_plot(cpu_data, net_data, pping_data, title=None):
    fig, axes = plt.subplots(6, 1, figsize=(8, 16), constrained_layout=True,
                             gridspec_kw={"height_ratios": [0.2, 1, 0.1, 1, 0.1, 1]})

    axes[0].axis("off")
    sar_cpu_viz.plot_percpu_timeseries(cpu_data, axes=axes[1])
    axes[2].axis("off")
    plot_network_throughput(net_data, axes=axes[3])
    axes[4].axis("off")
    plot_pping_output(pping_data, axes=axes[5])

    return fig


def main():
    parser = argparse.ArgumentParser("Plot graphs comparing the performance overhead of pping versions")
    parser.add_argument("-i", "--input", type=str, help="root folder of the results from run_tests.sh", required=True)
    parser.add_argument("-o", "--output", type=str, help="image output file", required=False)
    parser.add_argument("-I", "--interface", type=str, help="interface pping is running on", default="ens192", required=False)
    parser.add_argument("-s", "--source-ip", type=str, help="src-ip used to count filtered report", required=False, default=None)
    parser.add_argument("-O", "--omit", type=int, help="nr seconds to omit from start of test", required=False, default=0)
    args = parser.parse_args()

    cpu_data = prodat.load_cpu_data(args.input, omit=args.omit)
    net_data = prodat.load_network_data(args.input, interface=args.interface,
                                        omit=args.omit)
    pping_data = prodat.load_pping_reports(args.input, src_ip=args.source_ip,
                                           omit=args.omit)

    fig = plot_comparsion_plot(cpu_data, net_data, pping_data)
    fig.suptitle("Comparing performance of pping variants")

    if args.output is not None:
        fig.savefig(args.output, bbox_inches="tight")
    else:
        plt.show()

    return


if __name__ == "__main__":
    main()
