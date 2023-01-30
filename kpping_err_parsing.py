# SPDX-License-Identifier: GPL-2.0-or-later
import numpy as np
import pandas as pd
import re
import os

import util
import pping_ping_accuracy_viz as ppa_viz
import process_data as prodat

def is_kpping_first_ts_line(line):
    return line.startswith("First packet at ")

def parse_kpping_first_ts(line):
    if not is_kpping_first_ts_line(line):
        return None
    
    return pd.to_datetime(line[16:])

def is_kpping_summary_line(line):
    return re.match("\d+ flows, \d+ packets", line) is not None

def parse_kpping_summary_line(line):
    if not is_kpping_summary_line(line):
        return None
    
    return int(line.split()[2])

def parse_kpping_errfile(err_file, report_frequency=1.0, filter_timerange=None, norm_timestamps=True):
    t = None
    data = {"timestamp": [], "processed_packets": []}
    report_frequency = int(report_frequency * 1e9) # Convert from s to ns
    
    with util.open_compressed_file(err_file, mode="rt") as infile:
        for line in infile:
            if t is None:
                t = parse_kpping_first_ts(line)
            else:
                proc_pkts = parse_kpping_summary_line(line)
                if proc_pkts is not None:
                    data["timestamp"].append(t)
                    data["processed_packets"].append(proc_pkts)
                    t += np.timedelta64(report_frequency, "ns")
    
    df = pd.DataFrame(data)
    if filter_timerange is not None:
        df = df.loc[df["timestamp"].between(filter_timerange[0], filter_timerange[1])]
    if norm_timestamps:
        time_ref = None if filter_timerange is None else filter_timerange[0]
        df["timestamp"] = util.normalize_timestamps(df["timestamp"], time_ref)
        
    return df

def get_pping_errfile(subfolder):
    return ppa_viz.get_file_with_unknown_suffix(os.path.join(subfolder, "M2"), "pping.err")

def load_kpping_err(root_folder, omit=0, **kwargs):
    data = dict()
    
    kpping_folder = os.path.join(root_folder, "k_pping")
    if not os.path.exists(kpping_folder):
        return None
    
    test_interval = prodat.get_test_interval(kpping_folder, omit=omit)
    err_file = get_pping_errfile(kpping_folder)
    if err_file is not None:
        df = parse_kpping_errfile(err_file, filter_timerange=test_interval, **kwargs)
        if df is not None:
            data["PPing"] = df
    
    return data

def load_all_kpping_err(root_folder, **kwargs):
    return prodat._load_all(root_folder, load_kpping_err, **kwargs)
