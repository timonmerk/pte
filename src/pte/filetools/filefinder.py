"""Find and filter files. Supports BIDSPath objects from `mne-bids`."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import mne_bids

from pte.filetools.filefinder_abc import DirectoryNotFoundError, FileFinder


def get_filefinder(
    datatype: str, hemispheres: dict | None = None, **kwargs
) -> FileFinder:
    """Create and return FileFinder of desired type.

    Parameters
    ----------
    datatype : str
        Allowed values for `datatype`: ["any", "bids"].

    Returns
    -------
    FileFinder
        Instance of FileFinder for reading given `datatype`.
    """
    finders = {
        "any": DefaultFinder,
        "bids": BIDSFinder,
    }
    datatype = datatype.lower()
    if datatype not in finders:
        raise FinderNotFoundError(datatype, finders)

    return finders[datatype](hemispheres=hemispheres, **kwargs)


@dataclass
class DefaultFinder(FileFinder):
    """Class for finding and handling any type of file."""

    def __iter__(self):
        self._n = 0
        return self

    def __next__(self) -> Any:
        if self._n == len(self.files):
            raise StopIteration
        file = self.files[self._n]
        self._n += 1
        return file

    def find_files(
        self,
        directory: Path | str,
        extensions: Sequence | str | None = None,
        keywords: list[str] | str | None = None,
        hemisphere: str | None = None,
        stimulation: str | None = None,
        medication: str | None = None,
        exclude: str | None = None,
        verbose: bool = False,
    ) -> None:
        """Find files in directory with optional
        keywords and extensions.

        Args:
            directory (string)
            keywords (list): e.g. ["SelfpacedRota", "ButtonPress] (optional)
            extensions (list): e.g. [".json" or "tsv"] (optional)
            verbose (bool): verbosity level (optional, default=True)
        """
        self.directory = Path(directory)
        if not self.directory.is_dir():
            raise DirectoryNotFoundError(self.directory)
        self._find_files(self.directory, extensions)
        self._filter_files(
            keywords=keywords,
            hemisphere=hemisphere,
            stimulation=stimulation,
            medication=medication,
            exclude=exclude,
        )
        if verbose:
            print(self)

    def filter_files(
        self,
        keywords: list | None = None,
        hemisphere: str | None = None,
        stimulation: str | None = None,
        medication: str | None = None,
        exclude: str | None = None,
        verbose: bool = False,
    ) -> None:
        """Filter filepaths for given parameters and return filtered list."""
        self._filter_files(
            keywords=keywords,
            hemisphere=hemisphere,
            stimulation=stimulation,
            medication=medication,
            exclude=exclude,
        )
        if verbose:
            print(self)


@dataclass
class BIDSFinder(FileFinder):
    """Class for finding and handling data files in BIDS-compliant format."""

    bids_root: str = field(init=False)

    def find_files(
        self,
        directory: str,
        extensions: Sequence | str | None = (".vhdr", ".edf"),
        keywords: list | None = None,
        hemisphere: str | None = None,
        stimulation: str | None = None,
        medication: str | None = None,
        exclude: str | None = None,
        verbose: bool = False,
    ) -> None:
        """Find files in directory with optional keywords and extensions.


        Parameters
        ----------
            directory (string)
            keywords (list): e.g. ["SelfpacedRota", "ButtonPress] (optional)
            extensions (list): e.g. [".json" or "tsv"] (optional)
            verbose (bool): verbosity level (optional, default=True)
        """
        self.directory = directory
        self._find_files(self.directory, extensions)
        self._filter_files(
            keywords=keywords,
            hemisphere=hemisphere,
            stimulation=stimulation,
            medication=medication,
            exclude=exclude,
        )
        self.files = self._make_bids_paths(self.files)
        if verbose:
            print(self)

    def filter_files(
        self,
        keywords: list | None = None,
        hemisphere: str | None = None,
        stimulation: str | None = None,
        medication: str | None = None,
        exclude: str | None = None,
        verbose: bool = False,
    ) -> None:
        """Filter list of filepaths for given parameters."""
        self.files = [str(file.fpath.resolve()) for file in self.files]
        self._filter_files(
            keywords=keywords,
            hemisphere=hemisphere,
            stimulation=stimulation,
            medication=medication,
            exclude=exclude,
        )
        self.files = self._make_bids_paths(self.files)
        if verbose:
            print(self)

    def _make_bids_paths(
        self, filepaths: list[str]
    ) -> list[mne_bids.BIDSPath]:

        """Create list of mne-bids BIDSPath objects from list of filepaths."""
        bids_paths = []
        for filepath in filepaths:
            # entities = mne_bids.get_entities_from_fname(filepath)
            try:
                bids_path = mne_bids.get_bids_path_from_fname(
                    fname=filepath, verbose=False
                )
                bids_path.update(root=self.directory)
            except ValueError as err:
                print(
                    f"ValueError while creating BIDS_Path object for file "
                    f"{filepath}: {err}"
                )
            else:
                bids_paths.append(bids_path)
        return bids_paths


class FinderNotFoundError(Exception):
    """Exception raised when invalid Finder is passed.

    Attributes:
        datatype -- input datatype which caused the error
        finders -- allowed datatypes
        message -- explanation of the error
    """

    def __init__(
        self,
        datatype,
        finders,
        message="Input `datatype` is not an allowed value.",
    ) -> None:
        self.datatype = datatype
        self.finders = tuple(val for val in finders)
        self.message = message
        super().__init__(self.message)

    def __str__(self) -> str:
        return (
            f"{self.message} Allowed values: {self.finders}."
            f" Got: {self.datatype}."
        )
