#!/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import scipy.stats as stats
import pathlib
import sys
import re
import argparse

import util
import common_plotting as complot


def parse_epping_rtts(filename):
    data = list()

    with util.open_compressed_file(filename, mode="rt") as infile:
        for line in infile:
            parsed_info = parse_epping_rtt_line(line.rstrip())

            if parsed_info is not None:
                data.append(parsed_info)

    return pd.DataFrame(data)


def parse_epping_rtt_line(line):
    standard_format = is_epping_standard_rtt_line(line)
    ppviz_format = is_epping_ppviz_rtt_line(line)
    if not standard_format and not ppviz_format:
        return None

    words = line.split()
    flow = words[-1]

    if standard_format:
        time = words[0]
        rtt = float(words[1]) / 1000
    else:
        time = pd.to_datetime(words[0], unit="s")
        rtt = float(words[1])

    return {"timestamp": time, "rtt": rtt, "flow": flow}


def is_epping_standard_rtt_line(line):
    return re.match(
        "^\d{2}:\d{2}:\d{2}\.\d+ \d+\.\d+ ms .* [\d\.:]+\+[\d\.:]+$",
        line) is not None


def is_epping_ppviz_rtt_line(line):
    return re.match(
        "^\d+\.\d+ \d+\.\d+ .* [\d\.:]+\+[\d\.:]+$",
        line) is not None


def parse_ping_rtts(filename):
    data = list()

    with util.open_compressed_file(filename, mode="rt") as infile:
        for line in infile:
            parsed_info = parse_ping_rtt_line(line.rstrip())

            if parsed_info is not None:
                data.append(parsed_info)

    return pd.DataFrame(data)

def parse_ping_rtt_line(line):
    if not is_ping_rtt_line(line):
        return None

    words = line.split()
    if words[0].startswith("[") and words[0].endswith("]"):
        time = pd.to_datetime(words[0][1:-1], unit="s")
        offset = 1
    else:
        time = None
        offset = 0

    dst = words[3 + offset][:-1]
    seq = int(words[4 + offset].split("=")[1])

    rtt_str = words[-2].split("=")[1]
    rtt = float(words[-2].split("=")[1]) / 1000
    n_dec = len(rtt_str) - rtt_str.find(".") - 1 if rtt_str.find(".") >= 0 else 0
    rtt_prec = 10**(-3 - n_dec)

    return {"timestamp": time, "rtt": rtt, "rtt_prec": rtt_prec, "dst": dst,
            "seq": seq}


def is_ping_rtt_line(line):
    return re.match(
        "^(\[\d+\.\d+\] )?\d+ bytes from [\d\.:]+: icmp_seq=\d+ .* time=\d+(\.\d+)? ms$",
        line) is not None


def read_rtt_data(data_folder):
    data = dict()

    ping_file = get_file_with_unknown_suffix(data_folder, "ping.out")
    if ping_file is not None:
        data["ping"] = parse_ping_rtts(ping_file)
    else:
        print("Warning: No ping file found in {}".format(data_folder))

    epping_file = get_file_with_unknown_suffix(data_folder, "pping.out")
    if epping_file is not None:
        data["ePPing"] = parse_epping_rtts(epping_file)
    else:
        print("Warning: No ePPing file found in {}".format(data_folder))

    return data if len(data) > 0 else None


def get_file_with_unknown_suffix(folder, filename):
    files = list(pathlib.Path(folder).glob(filename + "*"))
    if len(files) > 1:
        print("Warning: Multiple files matching {}/{}*, returning first".format(
            folder, filename), file=sys.stderr)
    return files[0] if len(files) > 0 else None


def plot_rtt_dist(data, axes=None, **kwargs):
    if axes is None:
        fig, axes = plt.subplots(figsize=(8, 5))

    complot.plot_pergroup_histogram(data, col="rtt", axes=axes,
                                    print_stats=True,
                                    stat_kwargs={"fmt": "{:.4e}"}, **kwargs)
    axes.set_xlabel("RTT (s)")

    return axes


def plot_rtt_diff(data, axes=None, group_on_prec=False, **kwargs):
    if "ping" not in data and "ePPing" not in data:
        raise ValueError("Need both ping and ePPing data to cal")

    if len(data["ping"]) != len(data["ePPing"]):
        raise ValueError("ping and ePPing data of different size - cannot correlate")

    diff = data["ping"][["rtt", "rtt_prec"]].copy()
    diff["rtt"] = diff["rtt"] - data["ePPing"]["rtt"]

    diff_groups = {"Difference": diff}
    if group_on_prec:
        for prec_level, prec_data in diff.groupby("rtt_prec"):
            diff_groups["precision=" + str(prec_level)] = prec_data

    if axes is None:
        fig, axes = plt.subplots(figsize=(8, 5))

    complot.plot_pergroup_histogram(diff_groups, col="rtt", axes=axes,
                                    print_stats=True,
                                    stat_kwargs={"fmt": "{:.4e}"}, **kwargs)
    axes.set_xlabel("RTT-difference (s)")

    return axes


def plot_rtt_timeseries(data, normalize_timestamps=True, axes=None,
                        timestamp_type="time", max_length=None,
                        print_correlation=True, **kwargs):
    data_to_use = dict()
    if timestamp_type == "time":
        data_to_use = {key: df.copy for key, df in data.items()
                       if np.issubdtype(df["timestamp"].dtype, np.datetime64)}
        if normalize_timestamps:
            time_ref = min(df["timestamp"].min() for df in data_to_use.values())
            for df in data_to_use.values():
                df["timestamp"] = util.normalize_timestamps(df["timestamp"],
                                                            time_ref)
    elif timestamp_type == "order":
        lens = [len(df) for df in data.values()]
        if not all(l == min(lens) for l in lens):
            printf("Warning: Different size on ping data, plotting on order may be misleading",
                   file=sys.stderr)
        for key, df in data.items():
            df = df.copy()
            df["timestamp"] = np.arange(len(df))
            data_to_use[key] = df
    else:
        raise ValueError("timestamp type must be 'time' or 'order'")

    if max_length is not None:
        for key, val in data_to_use.items():
            data_to_use[key] = val.iloc[:max_length]

    if axes is None:
        _, axes = plt.subplots(figsize=(8, 5))

    if len(data_to_use) < 0:
        axes.text(0.5, 0.5, "No data", va="center", ha="center",
                  fontsize=20, color="red", transform=axes.transAxes)
        return axes

    complot.plot_pergroup_timeseries(data_to_use, "rtt", print_stats=True,
                                     stat_kwargs={"fmt": "{:.4e}"}, **kwargs)

    if print_correlation:
        rtts = [d["rtt"] for d in data_to_use.values()]
        if len(rtts) == 2 and len(rtts[0]) == len(rtts[1]) and len(rtts[0] > 1):
            r = stats.pearsonr(rtts[0], rtts[1])[0]
            axes.text(0.99, 0.01, "r={:.3f}".format(r), va="bottom", ha="right",
                      transform=axes.transAxes)

    return axes


def main():
    parser = argparse.ArgumentParser(description="Visualize ss -tiO log")
    parser.add_argument("-i", "--input", type=str, help="ss -tiO log file",
                        required=True)
    parser.add_argument("-o", "--output", type=str, help="image output file",
                        required=False)
    parser.add_argument("-T", "--title", type=str, help="figure title",
                        required=False)
    parser.add_argument("-d", "--dst-filter", type=str, help="only include flows to dst",
                        required=False)
    parser.add_argument("-g", "--guess-flows", help="guess which flows to include",
                        action="store_true", required=False)
    args = parser.parse_args()

    data = load_ss_tcp_data(args.input, dst=args.dst_filter,
                            filter_main_flows=args.guess_flows)
    fig = plot_ss_tcp_data(data)

    if args.output is not None:
        fig.savefig(args.output, bbox_inches="tight")
    else:
        plt.show()

    return


if __name__ == "__main__":
    main()
