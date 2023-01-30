#!/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later

import argparse
import matplotlib.pyplot as plt

import common_plotting as complot
import sar_data_loading as sdl


def plot_interface_net_timeseries(per_if_dfs, iface, axes=None, grid=True,
                                  print_stats=True):
    if axes is None:
        axes = plt.gca()
    if iface not in per_if_dfs:
        axes.text(0.5, 0.5, "No data for {}".format(iface), va="center",
                  ha="center", transform=axes.transAxes)
        return axes

    data = per_if_dfs[iface]
    t = data["timestamp"].values

    axes.plot(t, data["rxbps"].values, c="C0", ls="-", label="Rx bps")
    axes.plot(t, data["txbps"].values, c="C1", ls="-", label="Tx bps")

    ax2 = axes.twinx()
    ax2.plot(t, data["rxpps"].values, c="C0", ls="--")
    axes.plot([], [], c="C0", ls="--", label="Rx pps")
    ax2.plot(t, data["txpps"].values, c="C1", ls="--")
    axes.plot([], [], c="C1", ls="--", label="Tx pps")

    axes.legend()
    axes.grid(grid)

    axes.set_xlabel("Time")
    axes.set_ylim(0)
    axes.set_ylabel("Throughput (bps)")
    ax2.set_ylim(0)
    ax2.set_ylabel("Packets per second")

    if print_stats:
        complot.plot_stats_table(data, cols=["rxbps", "txbps", "rxpps", "txpps"],
                                 loc="top", fmt="{:.4e}")

    return axes


def plot_interface_err_timeseries(per_if_dfs, iface, axes=None, grid=True,
                                  print_stats=True):
    if axes is None:
        axes = plt.gca()
    if iface not in per_if_dfs:
        axes.text(0.5, 0.5, "No data for {}".format(iface), va="center",
                  ha="center", transform=axes.transAxes)
        return axes

    data = per_if_dfs[iface]
    t = data["timestamp"].values

    axes.plot(t, data["rxdrop"].values, c="C0", ls="-", label="Rx drops")
    axes.plot(t, data["txdrop"].values, c="C1", ls="-", label="Tx drops")

    ax2 = axes.twinx()
    ax2.plot(t, data["rxerr"].values, c="C0", ls="--")
    axes.plot([], [], c="C0", ls="--", label="Rx err")
    ax2.plot(t, data["txerr"].values, c="C1", ls="--")
    axes.plot([], [], c="C1", ls="--", label="Tx err")

    axes.legend()
    axes.grid(grid)

    axes.set_xlabel("Time")
    axes.set_ylim(0)
    axes.set_ylabel("Packet drops / s")
    ax2.set_ylim(0)
    ax2.set_ylabel("Packets errors / s")

    if print_stats:
        complot.plot_stats_table(data, cols=["rxdrop", "txdrop", "rxerr", "txerr"],
                                 loc="top", fmt="{}")

    return axes


def plot_interface_stats(per_if_dfs, interfaces=None, title=None):
    if interfaces is None:
        interfaces = list(per_if_dfs.keys())

    n = len(interfaces)
    fig, axes = plt.subplots(4, n, figsize=(8 * n, 10), squeeze=False,
                             constrained_layout=True,
                             gridspec_kw={"height_ratios": [0.3, 1, 0.3, 1]})

    for i, iface in enumerate(interfaces):
        axes[0, i].axis("off")
        plot_interface_net_timeseries(per_if_dfs, iface, axes=axes[1, i])
        axes[2, i].axis("off")
        plot_interface_err_timeseries(per_if_dfs, iface, axes=axes[3, i])
        axes[1, i].text(0.01, 0.01, iface, va="bottom", ha="left",
                        transform=axes[1, i].transAxes)

    if title is not None:
        fig.suptitle(title)

    return fig


def main():
    parser = argparse.ArgumentParser(description="Plot network data from sar file")
    parser.add_argument("-i", "--input", type=str, help="sar input file", required=True)
    parser.add_argument("-o", "--output", type=str, help="image output file", required=False)
    parser.add_argument("-I", "--interface", nargs="+", type=str, help="interface to display", required=False)
    parser.add_argument("-T", "--title", type=str, help="figure title", required=False)
    args = parser.parse_args()

    net_json = sdl.load_sar_network_data(args.input)
    data = sdl.to_perinterface_df(net_json)

    fig = plot_interface_stats(data, args.interface, title=args.title)

    if args.output is not None:
        fig.savefig(args.output, bbox_inches="tight")
    else:
        plt.show()


if __name__ == "__main__":
    main()
