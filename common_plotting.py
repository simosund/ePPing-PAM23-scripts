# SPDX-License-Identifier: GPL-2.0-or-later
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


def get_n_groups(group_dfs):
    return len([group for group in group_dfs if group != "all"])


def auto_alpha(n):
    if n < 2:
        return 1.0
    return max(1/100, 1/1.03**n)


def plot_stats_table(df, cols=None, axes=None, fmt="{:.3f}", only_all=False,
                     func_map=None, funcs=("min", "median", "mean", "max", "std"),
                     include_rowlabels=True, include_collabels=True, **kwargs):
    fmap = {"count": lambda x: pd.notnull(x).sum(),
            "min": np.nanmin,
            "max": np.nanmax,
            "median": np.nanmedian,
            "mean": np.nanmean,
            "std": lambda x: np.nanstd(x, ddof=1),
            "q1": lambda x: np.nanpercentile(x, 25),
            "q2": lambda x: np.nanpercentile(x, 50),
            "q3": lambda x: np.nanpercentile(x, 75),
            "pctl-1": lambda x: np.nanpercentile(x, 1),
            "pctl-99": lambda x: np.nanpercentile(x, 99)}

    if func_map is not None:
        fmap.update(func_map)

    if axes is None:
        axes = plt.gca()
    if cols is None:
        cols = df.columns
    if len(cols) < 1:
        return axes

    collabels = funcs if include_collabels else None
    rowlabels = []
    cells = []

    for col in cols:
        rowlabels.append(col)
        cells.append([fmt.format(np.nan if df[col].notnull().sum() == 0 and func != "count"
                                 else fmap[func](df[col].values))
                      for func in funcs])

    if not include_rowlabels:
        rowlabels = None
    axes.table(cellText=cells, rowLabels=rowlabels, colLabels=collabels, **kwargs)
    return axes


def group_df_to_single_df(groupwise_df, col):
    return pd.DataFrame({group: df[col] for group, df in groupwise_df.items()})


def plot_pergroup_timeseries(group_dfs, col, axes=None, max_groups=10,
                             groups=None, normalize_all=True, print_stats=True,
                             stats_only_all="auto", grid=True, alpha="auto",
                             legend=True, stat_kwargs=None, **kwargs):
    if axes is None:
        axes = plt.gca()

    if groups is not None:
        group_dfs = {group: group_dfs[group] for group in groups}

    norm = max(1, get_n_groups(group_dfs)) if normalize_all else 1

    many_groups = get_n_groups(group_dfs) > max_groups
    if stats_only_all == "auto":
        stats_only_all = many_groups
    if alpha == "auto":
        alpha = auto_alpha(get_n_groups(group_dfs))

    for group, data in group_dfs.items():
        if group == "all":
            axes.plot(data["timestamp"].values, data[col].values/norm,
                      label="average", color="k", linewidth=2, zorder=2.5)
        else:
            color = "C0" if many_groups else None
            label = None if many_groups else group
            axes.plot(data["timestamp"].values, data[col].values, label=label,
                      color=color, alpha=alpha, **kwargs)

    axes.grid(grid)
    axes.set_xlabel("Time")
    if legend and len(axes.get_legend_handles_labels()[0]) > 0:
        axes.legend()

    if print_stats:
        stat_kws = {"loc": "top", "cols": ["all"] if stats_only_all else None}
        if stat_kwargs is not None:
            stat_kws.update(stat_kwargs)

        plot_stats_table(group_df_to_single_df(group_dfs, col), axes=axes,
                         **stat_kws)

    return axes


def plot_cdf(x, axes=None, **kwargs):
    if axes is None:
        axes = plt.gca()

    x = np.array(x)
    x = np.sort(x[pd.notnull(x)])
    y = np.linspace(1/len(x), 1, len(x))
    axes.plot(x, y, **kwargs)

    axes.set_ylabel("CDF")
    axes.set_ylim(0, 1)
    return axes


def plot_pergroup_cdf(group_dfs, col, axes=None, groups=None,
                      normalize_all=True, print_stats=False, grid=True,
                      legend=True, stat_kwargs=None, **kwargs):
    if axes is None:
        axes = plt.gca()

    if groups is not None:
        group_dfs = {group: group_dfs[group] for group in groups}

    norm = max(1, get_n_groups(group_dfs)) if normalize_all else 1

    for group, df in group_dfs.items():
        if group == "all":
            plot_cdf(df[col].values/norm, axes=axes, label="average",
                     color="k", linewidth=2, zorder=2.5)
        else:
            plot_cdf(df[col].values, axes=axes, label=group, **kwargs)

    axes.grid(grid)
    if legend:
        axes.legend()

    if print_stats:
        default_kwargs = {"loc": "top"}
        if stat_kwargs is not None:
            default_kwargs.update(stat_kwargs)
        plot_stats_table(group_df_to_single_df(group_dfs, col), axes=axes,
                         **default_kwargs)

    return axes


def plot_pergroup_histogram(group_dfs, col, axes=None, groups=None,
                            normalize_all=True, print_stats=False, bins="auto",
                            n_bins=100, alpha="auto", histtype="step",
                            density=True, grid=True, legend=True,
                            stat_kwargs=None, **kwargs):
    if axes is None:
        axes = plt.gca()

    if groups is not None:
        group_dfs = {group: group_dfs[group] for group in groups}

    if np.isscalar(bins) and bins == "auto":
        gmin = min(data[col].min() for data in group_dfs.values())
        gmax = max(data[col].max() for data in group_dfs.values())
        if gmin == gmax:
            gmax += 0.5
            gmin -= 0.5
        pad = (gmax - gmin) * 0.01
        bins = np.linspace(gmin-pad, gmax+pad, n_bins+1)

    if alpha == "auto":
        alpha = auto_alpha(get_n_groups(group_dfs))

    norm = max(1, get_n_groups(group_dfs)) if normalize_all else 1

    for group, df in group_dfs.items():
        if group == "all":
            axes.hist(df[col].values/norm, bins=bins, histtype=histtype,
                      density=density, color="k", label="average ({})".format(
                          len(df[col].values)), alpha=alpha, **kwargs)
        else:
            axes.hist(df[col].values, bins=bins, histtype=histtype,
                      density=density, label="{} ({})".format(
                          group, df[col].notnull().sum()),
                      alpha=alpha, **kwargs)

    axes.set_ylabel("Frequency")
    axes.grid(grid)
    if legend:
        axes.legend()

    if print_stats:
        default_kwargs = {"loc": "top"}
        if stat_kwargs is not None:
            default_kwargs.update(stat_kwargs)
        plot_stats_table(group_df_to_single_df(group_dfs, col), axes=axes, **default_kwargs)

    return axes
