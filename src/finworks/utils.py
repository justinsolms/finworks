#!/usr/bin/env python
# -*- coding: utf-8 -*-
# <nbformat>3.0</nbformat>

"""Utility functions and classes that can't be grouped in a specific module.

Copyright (C) 2015 Justin Solms <justinsolms@gmail.com>.
This file is part of the finworks module.
The finworks module can not be modified, copied and/or
distributed without the express permission of Justin Solms.

"""

import re
import subprocess
import datetime

import pandas as pd


# datetime to date-string converter
def date_to_str(df):
    """Convert Timestamp objects to test date-strings."""
    df.replace({pd.NaT: None}, inplace=True)
    # All dates to date strings
    for index, row in df.iterrows():
        for column, item in row.items():
            if (
                isinstance(item, pd.Timestamp)
                or isinstance(item, datetime.date)
                or isinstance(item, datetime.datetime)
            ):
                # Not sure why I must do this 0!?! Else it does not work
                df.loc[index, column] = 0
                # Convert
                try:
                    df.loc[index, column] = item.strftime("%Y-%m-%d")
                except ValueError:
                    df.loc[index, column] = None


# TODO: Import form a common utils.py
def datepair_to_datetimes(from_date=None, to_date=None):
    """Need to parse all dates to `datetime`."""
    if from_date is None:
        from_date = datetime.datetime(1900, 1, 1)
    elif isinstance(from_date, datetime.datetime):
        pass
    elif isinstance(from_date, datetime.date):
        from_date = datetime.datetime(from_date.year, from_date.month, from_date.day)
    elif isinstance(from_date, str):
        from_date = datetime.datetime.strptime(from_date, "%Y-%m-%d")
    else:
        raise ValueError("Unexpected `from_date` argument.")

    if to_date is None:
        to_date = datetime.datetime.today()
    elif isinstance(to_date, str):
        to_date = datetime.datetime.strptime(to_date, "%Y-%m-%d")
    elif isinstance(to_date, datetime.datetime):
        pass
    elif isinstance(to_date, datetime.date):
        to_date = datetime.datetime(to_date.year, to_date.month, to_date.day)
    else:
        raise ValueError("Unexpected `to_date` argument.")

    return from_date, to_date


class SSHCommand(object):
    def __init__(self, host, user, source_url):
        self.host = host
        self.user = user
        self.source_url = source_url

    def curl_get(self, command):
        # SSH connection.
        url = "{}/{}".format(self.source_url, command)
        # Note the careful packaging of the curl command and its URL in two
        # different type of enclosing quote marks using backlashes (\"). This
        # is important as any ampersands would otherwise be interpreted as
        # delineating separate commands.
        cli_cmd = "\"curl '{}'\"".format(url)
        ssh = subprocess.Popen(
            "ssh {user}@{host} {cmd}".format(
                user=self.user,
                host=self.host,
                cmd=cli_cmd,
            ),
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # %% Read stdout as one single line
        result = ssh.stdout.read()  # Not readline!
        if result == "":
            error = ssh.stderr.readlines()
            msg = "SSH Error at host {}: {}".format(self.host, error[-1])
            raise Exception(msg)

        return result


def version_file(file_spec, vtype="copy"):
    """Copy or rename existing file before overwriting the same name file.

    The purpose of the VersionFile function is to ensure that an existing file
    is copied (or renamed, as indicated by the optional second parameter)
    **before** you open it for writing or updating and therefore modify it. It
    is polite to make such backups of files before you mangle them. The actual
    copy or renaming is performed by shutil.copy and os.rename, respectively,
    so the only issue is what name to use as the target.

    A popular way to determine backups' names is versioning (i.e., appending to
    the filename a gradually incrementing number). This recipe determines the
    new_name by first extracting the filename's root (just in case you call it
    with an already-versioned filename) and then successively appending to that
    root the further extensions .000, .001, and so on, until a name built in
    this manner does not correspond to any existing file. Then, and only then,
    is the name used as the target of a copy or renaming. Note that VersionFile
    is limited to 1,000 versions, so you should have an archive plan after
    that. You also need the file to exist before it is first versioned—you
    cannot back up what does not yet exist.

    Referenced from `Python Cookbook`_, Credit to Robin Parmar.

    .. `Python Cookbook`: https://www.oreilly.com/library/view/python-cookbook/0596001673/ch04s26.html
    """
    import os
    import shutil

    if os.path.isfile(file_spec):
        # or, do other error checking:
        if vtype not in ["copy", "rename"]:
            vtype = "copy"

        # Determine root filename so the extension doesn't get longer
        n, e = os.path.splitext(file_spec)

        # Is e an integer?
        try:
            num = int(e)  # noqa: F841
            root = n
        except ValueError:
            root = file_spec

        # Find next available file version
        for i in range(1000):
            new_file = "%s.%03d" % (root, i)
            if not os.path.isfile(new_file):
                if vtype == "copy":
                    shutil.copy(file_spec, new_file)
                else:
                    os.rename(file_spec, new_file)
                return 1

    return 0

def url_to_filename(url: str) -> str:
    """Converts a URL into a Linux-safe filename by replacing special characters.

    Replaces the following characters:
    - "http://" or "https://" with ""
    - "/" with "_"
    - ":" with "_"
    - "?" with "_"
    - "-" with "_"

    Parameters
    ----------
    url: str
        The URL to convert.

    Returns
    -------
    str
        A sanitized filename.
    """
    # Remove protocol (http:// or https://)
    url = re.sub(r'^https?://', '', url)
    url = url.replace('/', '_')
    url = url.replace(':', '_')
    url = url.replace('?', '_')
    url = url.replace('-', '_')

    return url
