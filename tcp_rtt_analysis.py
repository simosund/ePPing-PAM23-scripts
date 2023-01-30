# SPDX-License-Identifier: GPL-2.0-or-later
import numpy as np
import pandas as pd
import sys

def compute_base_delay(rtts, ms_offsets=[i * 10 for i in range(11)], next_consistent=10):
    """
    More robust version which assumes that there will never be more than
    next_consistent RTTs at the current delay value which will exceede the
    next delay value.
    """
    offsets = np.array(ms_offsets) * 1e-3
    rtts = np.array(rtts)
    base_delay = np.zeros(len(rtts))
    
    start_idx = 0
    end_idx = 0
    for i in range(len(offsets) - 1):
        while (end_idx+next_consistent < len(rtts) and 
               any(rtts[end_idx:end_idx+next_consistent] < offsets[i+1])):
            end_idx += 1
        
        base_delay[start_idx:end_idx] = offsets[i]
        start_idx = end_idx
    
    base_delay[end_idx:] = offsets[-1]
    
    # Check monotonically increasing
    if not all(np.diff(base_delay) >= 0):
        print("Warning: Base delay not monotonically increasing", file=sys.stderr)
    
    return base_delay

def add_delay_offset(rtt_dfs, ms_offsets=[i * 10 for i in range(11)], verify=True):
    for rtt_tool in rtt_dfs.keys():
        df = rtt_dfs[rtt_tool]
        df["base_delay"] = compute_base_delay(df["rtt"], ms_offsets=ms_offsets)
        df["rtt_above"] = df["rtt"] - df["base_delay"]
        df["rtt_above_ms"] = df["rtt_above"] * 1e3
        df["rtt_above_us"] = df["rtt_above"] * 1e6
    
    if verify:
        verify_rtt_delays_consistent(rtt_dfs)
    
    return rtt_dfs

def verify_rtt_delays_consistent(rtt_dfs):
    rtt_tools = list(rtt_dfs.keys())
    min_tsecr = max(rtt_dfs[rtt_tool]["tsecr"].min() for rtt_tool in rtt_tools)
    max_tsecr = min(rtt_dfs[rtt_tool]["tsecr"].max() for rtt_tool in rtt_tools)
    df = rtt_dfs[rtt_tools[0]].drop_duplicates(subset="tsecr")
    df = df.query("tsecr >= @min_tsecr and tsecr <= @max_tsecr")
    ref = df["base_delay"].values
    consistent = True
    
    for rtt_tool in rtt_tools[1:]:
        df = rtt_dfs[rtt_tool].drop_duplicates(subset="tsecr")
        df = df.query("tsecr >= @min_tsecr and tsecr <= @max_tsecr")
        if not all(df["base_delay"].values == ref):
            print("Warning: base_delay for {} not consistent with {}".format(
                rtt_tool, rtt_tools[0]), file=sys.stderr)
            consistent = False
    
    return consistent

def filter_comparable_rtts(rtt_dfs):
    merge_cols = ["tsecr", "ack"]
    filt = rtt_dfs.copy()
    get_idxkey = lambda x: "{}_idx".format(x)
    
    # Get rid of duplicate TSecr and add idx to columns
    for rtt_tool in list(filt.keys()):
        df = filt[rtt_tool].copy()
        if not all([mc in df.columns for mc in merge_cols]):
            print("Warning: {} does not have the required columns {} - dropping it".format(
                rtt_tool, merge_cols), file=sys.stderr)
            del filt[rtt_tool]
            continue
        
        df[get_idxkey(rtt_tool)] = np.arange(len(df))
        filt[rtt_tool] = df
    
    # Find common RTTs (by merging on merge_cols)
    rtt_tools = list(filt.keys())
    merge_keys = filt[rtt_tools[0]][merge_cols + [get_idxkey(rtt_tools[0])]]
    for rtt_tool in rtt_tools[1:]:
        merge_keys = merge_keys.merge(filt[rtt_tool][merge_cols + [get_idxkey(rtt_tool)]], 
                                      on=merge_cols, how="inner", validate="1:1")
    
    for rtt_tool in rtt_tools:
        if len(merge_keys) < len(filt[rtt_tool]):
            print("Warning: {} entries from {} missing in common set".format(
                len(filt[rtt_tool]) - len(merge_keys), rtt_tool), file=sys.stderr)
        
        idx = merge_keys[get_idxkey(rtt_tool)].values
        filt[rtt_tool] = filt[rtt_tool].iloc[idx].reset_index(drop=True)
    
    return filt
