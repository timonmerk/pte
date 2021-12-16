"""Module for loading results from decoding experiments."""
import json
from pathlib import Path
from typing import Iterable, Optional, Union
import mne_bids

import numpy as np
import pandas as pd

import pte


def load_results(
    files_or_dir: Union[str, list, Path],
    keywords: Optional[Union[str, list]] = None,
    scoring_key: str = "balanced_accuracy",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load prediciton results from *results.csv"""
    # Create Dataframes from Files
    if not isinstance(files_or_dir, list):
        file_finder = pte.get_filefinder(datatype="any")
        file_finder.find_files(
            directory=files_or_dir,
            keywords=keywords,
            extensions=["results.csv"],
            verbose=True,
        )
        files_or_dir = file_finder.files
    results = []
    for file in files_or_dir:
        df = pd.read_csv(file, index_col=[0], header=[0])
        data = pd.melt(df, id_vars=["channel_name"], value_vars=[scoring_key])
        accuracies = []
        for ch_name in data["channel_name"].unique():
            accuracies.append(
                [
                    "LFP" if "LFP" in ch_name else "ECOG",
                    data[data.channel_name == ch_name]
                    .mean(numeric_only=True)
                    .value,
                ]
            )
        df_acc = pd.DataFrame(accuracies, columns=["Channels", scoring_key])
        df_lfp = df_acc[df_acc["Channels"] == "LFP"]
        df_ecog = df_acc[df_acc["Channels"] == "ECOG"]
        subject = mne_bids.get_entities_from_fname(file, on_error="ignore")[
            "subject"
        ]
        values = [
            file,
            subject,
            "OFF" if "MedOff" in file else "ON",
            "OFF" if "StimOff" in file else "ON",
            df["trials_used"].iloc[0],
            df["trials_discarded"].iloc[0],
        ]
        results.extend(
            [
                values + ["LFP", df_lfp[scoring_key].max()],
                values + ["ECOG", df_ecog[scoring_key].max()],
            ]
        )
    columns = [
        "filename",
        "subject",
        "medication",
        "stimulation",
        "trials_used",
        "trials_discarded",
        "channels",
        scoring_key,
    ]
    df_raw = pd.DataFrame(results, columns=columns)

    # Average raw results
    results_average = []
    for ch_name in df_raw["channels"].unique():
        df_ch = df_raw.loc[df_raw["channels"] == ch_name]
        for subject in df_ch["subject"].unique():
            df_subj = df_ch.loc[df_ch["subject"] == subject]
            series_single = pd.Series(
                df_subj.iloc[0].values, index=df_subj.columns
            ).drop("filename")
            series_single[scoring_key] = df_subj[scoring_key].mean()
            results_average.append(series_single)
    df_average = pd.DataFrame(results_average)

    # Rename columns
    df_average = df_average.rename(
        columns={
            col: " ".join([substr.capitalize() for substr in col.split("_")])
            for col in df_average.columns
        }
    )
    return df_average, df_raw


def load_predictions_timelocked(
    files_or_dir: Union[str, list, Path],
    sfreq: Optional[Union[int, float]] = None,
    baseline: Union[bool, tuple] = None,
    baseline_mode: str = "z-score",
    channels: Iterable = ("ECOG", "LFP"),
    keywords: Optional[Union[str, list]] = None,
    key_average: Optional[str] = None,
):
    """Load data from time-locked predictions."""
    if not isinstance(files_or_dir, list):
        file_finder = pte.get_filefinder(datatype="any")
        file_finder.find_files(
            directory=files_or_dir,
            keywords=keywords,
            extensions=["predictions_timelocked.json"],
            verbose=True,
        )
        files_or_dir = file_finder.files
    if baseline:
        base_start, base_end = _handle_baseline(baseline, sfreq)

    data = {ch_name: {} for ch_name in channels}
    for key, fpath in enumerate(files_or_dir):
        if key_average:
            key = mne_bids.get_entities_from_fname(fpath, on_error="ignore")[
                key_average
            ]
        with open(fpath, "r", encoding="utf-8") as file:
            preds = json.load(file)
        for ch_name in channels:
            if key not in data[ch_name]:
                data[ch_name][key] = []
            pred = np.mean(np.stack(preds[ch_name], axis=0), axis=0)
            if baseline:
                if baseline_mode == "std":
                    pred = pred / np.std(pred[base_start:base_end])
                else:  # baseline_mode == "z-score"
                    pred = (pred - np.mean(pred[base_start:base_end])) / (
                        np.std(pred[base_start:base_end])
                    )
            data[ch_name][key].append(pred)
    data_outer = []
    for _, value in data.items():
        data_inner = []
        for _, j in value.items():
            data_inner.append(np.array(j).mean(axis=0))
        data_outer.append(data_inner)
    data_outer = np.array(data_outer)
    return data_outer


def load_predictions_subject(
    files_or_dir: Union[str, list, Path],
    sfreq: Optional[Union[int, float]] = None,
    baseline: Union[bool, tuple] = None,
    baseline_mode: str = "z-score",
    keywords: Optional[Union[str, list]] = None,
    average_predictions: bool = False,
    concatenate_runs: bool = True,
    average_runs: bool = False,
) -> pd.DataFrame:
    """Load data from time-locked predictions."""
    if not isinstance(files_or_dir, list):
        file_finder = pte.get_filefinder(datatype="any")
        file_finder.find_files(
            directory=files_or_dir,
            keywords=keywords,
            extensions=["predictions_timelocked.json"],
            verbose=True,
        )
        files_or_dir = file_finder.files
    if baseline:
        base_start, base_end = _handle_baseline(baseline, sfreq)
    else:
        base_start, base_end = None, None

    df_list = []
    for fpath in files_or_dir:
        df_single = _load_predictions(
            fpath=fpath,
            baseline=baseline,
            baseline_mode=baseline_mode,
            base_start=base_start,
            base_end=base_end,
        )
        if average_predictions:
            df_single["Data"] = (
                df_single["Data"]
                .apply(np.mean, axis=0)
                .apply(np.expand_dims, axis=0)
            )
        df_list.append(df_single)
    df_all = pd.concat(df_list)
    if concatenate_runs:
        df_all = _concatenate_runs(data=df_all)
    if average_runs:
        df_all["Data"] = (
            df_all["Data"].apply(np.mean, axis=0).apply(np.expand_dims, axis=0)
        )
    return df_all


def _concatenate_runs(data: pd.DataFrame):
    """Concatenate predictions from different runs in a single patient."""
    data_list = []
    for ch_name in data["Channel Name"].unique():
        dat_ch = data[data["Channel Name"] == ch_name]
        for sub in dat_ch["Subject"].unique():
            dat_concat = np.vstack(
                dat_ch["Data"][dat_ch["Subject"] == sub].values
            )
            data_list.append([sub, ch_name, dat_concat])
    return pd.DataFrame(data_list, columns=["Subject", "Channel Name", "Data"])


def _load_predictions(
    fpath: Union[str, Path],
    baseline: Union[bool, tuple],
    baseline_mode: str,
    base_start: int,
    base_end: Optional[int],
) -> pd.DataFrame:
    """Load time-locked predictions from single file."""
    entities = mne_bids.get_entities_from_fname(fpath, on_error="ignore")
    with open(fpath, "r", encoding="utf-8") as file:
        preds = json.load(file)
    data_list = []
    for ch_name, pred in [
        (ch_name, pred)
        for ch_name, pred in preds.items()
        if any([keyw in ch_name for keyw in ["ECOG", "LFP"]])
    ]:
        pred_arr = np.stack(pred, axis=0)
        if baseline:
            pred_arr = _baseline_correct(
                pred_arr, baseline_mode, base_start, base_end
            )

        data_list.append(
            [
                entities["subject"],
                entities["session"],
                entities["task"],
                entities["run"],
                entities["acquisition"],
                ch_name,
                pred_arr,
            ]
        )
    data = pd.DataFrame(
        data_list,
        columns=[
            "Subject",
            "Session",
            "Task",
            "Run",
            "Acquisition",
            "Channel Name",
            "Data",
        ],
    )
    return data


def _handle_baseline(
    baseline: Optional[tuple], sfreq: Optional[Union[int, float]]
):
    """Return baseline start and end values for given baseline and sampling frequency."""
    if any(baseline) and not sfreq:
        raise ValueError(
            "If `baseline` is any value other than `None`, `False` or `(None, None)`, `sfreq` must be provided."
        )
    if not sfreq:
        sfreq = 0.0
    if baseline[0] is None:
        base_start = 0
    else:
        base_start = int(baseline[0] * sfreq)
    if baseline[1] is None:
        base_end = None
    else:
        base_end = int(baseline[1] * sfreq)
    return base_start, base_end


def _baseline_correct(
    data: np.ndarray,
    baseline_mode: str,
    base_start: Optional[int],
    base_end: Optional[int],
):
    """Baseline correct data."""
    data = data.T
    if baseline_mode == "std":
        data_corr = data / np.std(data[base_start:base_end], axis=0)
    else:  # baseline_mode == "z-score"
        data_corr = (data - np.mean(data[base_start:base_end], axis=0)) / (
            np.std(data[base_start:base_end], axis=0)
        )
    return data_corr.T