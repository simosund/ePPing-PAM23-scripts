# SPDX-License-Identifier: GPL-2.0-or-later
import pandas as pd
import os
import subprocess
import re
import sys
from io import StringIO

import util
import pping_ping_accuracy_viz as ppa_viz
import sar_data_loading as sdl


def _parse_kpping_rtts(pcap, pping_path="~/src/pping/pping"):
    p = subprocess.run([os.path.expanduser(pping_path), "-r", pcap, "-m"],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise ChildProcessError("pping failed parsing {}: {}".format(pcap, p.stderr))

    data = list()
    for line in p.stdout.split("\n"):
        parsed_info = ppa_viz.parse_epping_rtt_line(line)
        if parsed_info is not None:
            data.append(parsed_info)

    return pd.DataFrame(data)


def parse_kpping_rtts(pcap, pping_path="~/src/pping/pping"):
    return sdl._run_on_xz_file(_parse_kpping_rtts, pcap, pping_path=pping_path)


def _get_tshark_rtts(pcap):
    p = subprocess.run(["tshark", "-r", pcap, "-Y", "tcp.analysis.ack_rtt",
                        "-e", "frame.time_epoch",
                        "-e", "ip.src",
                        "-e", "tcp.srcport",
                        "-e", "ip.dst",
                        "-e", "tcp.dstport",
                        "-e", "tcp.analysis.ack_rtt",
                        "-e", "tcp.options.timestamp.tsecr",
                        "-e", "tcp.options.timestamp.tsval",
                        "-e", "tcp.ack_raw",
                        "-T", "fields", "-E", "separator=,", "-E", "header=y"],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise ChildProcessError("tshark failed in file {}: {}".format(pcap, p.stderr))

    data = pd.read_csv(StringIO(p.stdout), dtype={"frame.time_epoch": "str"})
    data = data.rename(columns={"frame.time_epoch": "timestamp",
                                "tcp.analysis.ack_rtt": "rtt",
                                "tcp.options.timestamp.tsval": "tsval",
                                "tcp.options.timestamp.tsecr": "tsecr",
                                "tcp.ack_raw": "ack"})

    data["timestamp"] = [util.parse_unix_timestamp(tstr)
                         for tstr in data["timestamp"]]

    col_idx = {col: i for i, col in enumerate(data.columns)}
    data["flow"] = ["{}:{}+{}:{}".format(row[col_idx["ip.src"]],
                                         row[col_idx["tcp.srcport"]],
                                         row[col_idx["ip.dst"]],
                                         row[col_idx["tcp.dstport"]])
                    for row in data.itertuples(index=False)]

    return data


def get_tshark_rtts(pcap):
    return sdl._run_on_xz_file(_get_tshark_rtts, pcap)


def _get_tcptrace_rtts(pcap):
    p = subprocess.run([os.path.expanduser("~/src/tcptrace/tcptrace"), "-Z", "-b", pcap], 
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise ChildProcessError("tcptrace failed on file {}: {}".format(pcap, p.stderr))

    dfs = list()
    flow_mapping = parse_tcptrace_flow_mapping(p.stdout)

    for flow_abr, flow in flow_mapping.items():
        rtt_file = flow_abr + "_rttraw.dat"
        rtts = pd.read_csv(rtt_file, sep=" ", header=None, names=["firstbyte", "rtt"])
        rtts["rtt"] = rtts["rtt"] * 1e-6
        rtts["flow"] = flow
        os.remove(rtt_file)
        dfs.append(rtts)

    return pd.concat(dfs, ignore_index=True)


def get_tcptrace_rtts(pcap):
    return sdl._run_on_xz_file(_get_tcptrace_rtts, pcap)


def parse_tcptrace_flow_mapping(text):
    flow_mapping = dict()
    for line in text.split("\n"):
        mapping = parse_tcptrace_flow_mapping_line(line)
        if mapping is not None:
            flow_mapping.update(mapping)
    return flow_mapping


def is_tcptrace_flow_mapping_line(line):
    return re.match("^\s*\d+: [\d\.:]+ - [\d\.:]+ \([a-z]2[a-z]\)", line) is not None


def parse_tcptrace_flow_mapping_line(line):
    if not is_tcptrace_flow_mapping_line(line):
        return None

    words = line.split()
    dst = words[1]
    src = words[3]
    src_letter, dst_letter = words[4][1:-1].split("2")
    return {"{}2{}".format(src_letter, dst_letter): "{}+{}".format(src, dst),
            "{}2{}".format(dst_letter, src_letter): "{}+{}".format(dst, src)}


def get_main_flow(flows, srcip="10.70.2.2"):
    flow_count = dict()
    for flow in flows:
        if flow.startswith(srcip):
            flow_count[flow] = flow_count.get(flow, 0) + 1

    max_f = None
    max_c = -1
    for flow, count in flow_count.items():
        if count > max_c:
            max_c = count
            max_f = flow

    return max_f


def parse_tcpdump_info(info_file):
    line_formats = {"captured": "packets captured",
                    "filtered": "packets received by filter",
                    "dropped": "packets dropped by kernel"}

    with util.open_compressed_file(info_file, mode="rt") as infile:
        lines = infile.readlines()

    data = dict()
    for key, line_fmt in line_formats.items():
        for line in lines:
            if line_fmt in line:
                data[key] = int(line.split()[0])

    return data


def get_epping_file(subfolder):
    return ppa_viz.get_file_with_unknown_suffix(
        os.path.join(subfolder, "e_pping", "M2"), "pping.out")


def get_pcap_file(subfolder):
    return ppa_viz.get_file_with_unknown_suffix(
        os.path.join(subfolder, "e_pping", "M2"), "packetdump.pcap")


def get_tcpdump_info_file(subfolder):
    return ppa_viz.get_file_with_unknown_suffix(
        os.path.join(subfolder, "e_pping", "M2"), "tcpdump_info.txt")


def _filter_and_format_data(df, srcip="10.70.2.2", delay=None):
    df = df.loc[df["flow"] == get_main_flow(df["flow"],
                                            srcip=srcip)].reset_index(drop=True)

    df["rtt_ms"] = df["rtt"] * 1e3
    df["rtt_us"] = df["rtt"] * 1e6
    if delay is not None:
        df["rtt_off"] = df["rtt"] - delay * 1e-3
        df["rtt_off_ms"] = df["rtt_off"] * 1e3
        df["rtt_off_us"] = df["rtt_off"] * 1e6

    return df


def load_all_rtt_data(root_folder, srcip="10.70.2.2",
                      pping_path="~/src/pping/pping",
                      tools=["tshark", "tcptrace", "PPing", "ePPing"],
                      normalize_timestamps=True):
    data = dict()

    dump_info = parse_tcpdump_info(get_tcpdump_info_file(root_folder))
    if dump_info["dropped"] > 0:
        print("Warning: tcpdump dropped packets in {}".format(
            get_tcpdump_info_file(root_folder)), file=sys.stderr)

    pcap = get_pcap_file(root_folder)
    if "tshark" in tools:
        data["tshark"] = _filter_and_format_data(get_tshark_rtts(pcap),
                                                 srcip=srcip)
    if "tcptrace" in tools:
        data["tcptrace"] = _filter_and_format_data(get_tcptrace_rtts(pcap),
                                                   srcip=srcip)
    if "PPing" in tools:
        data["PPing"] = _filter_and_format_data(
            parse_kpping_rtts(pcap, pping_path=pping_path), srcip=srcip)

    if "ePPing" in tools:
        epping_file = get_epping_file(root_folder)
        data["ePPing"] = _filter_and_format_data(
            ppa_viz.parse_epping_rtts(epping_file), srcip=srcip)


    if normalize_timestamps:
        tstamp_tools = [key for key in data.keys()
                        if "timestamp" in data[key].columns]
        tref = min([data[tool]["timestamp"].min()
                    for tool in tstamp_tools])
        for tool in tstamp_tools:
            data[tool]["timestamp"] = util.normalize_timestamps(
                data[tool]["timestamp"], tref)

    return data
