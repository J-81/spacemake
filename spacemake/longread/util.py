from collections import defaultdict
import numpy as np


def count_dict_collapse_misc(
    counts, misc_thresh=0.01, total=1, add_up=None, sig_intact=None
):
    out_counts = defaultdict(int)
    out_frac = defaultdict(float)

    misc = 0
    sum = 0
    if sig_intact is not None:
        complete = ",".join(sig_intact)
        everything = set(sig_intact)
    else:
        complete = None
        everything = set()

    def relkey(key):
        if sig_intact is None:
            return key

        if key == complete:
            return "complete"

        obs = set(key.split(","))
        there = obs & everything
        extra = obs - everything
        missing = everything - obs

        if len(missing) <= len(there):
            res = "missing_" + ",".join(sorted(missing))
        else:
            res = "only_" + ",".join(sorted(there))
        if extra:
            res += "_extra_" + ",".join(sorted(extra))

        return res

    for key, n in sorted(counts.items()):
        key = relkey(key)
        sum += n
        f = n / float(total)
        if f < misc_thresh:
            misc += n
        else:
            out_counts[key] = n
            out_frac[key] = f

    if misc > 0:
        out_counts["misc"] += misc
        out_frac["misc"] += misc / float(total)

    if add_up is None:
        other = total - sum
    else:
        other = total - counts[add_up]

    if other > 0:
        out_counts["N/A"] += other
        out_frac["N/A"] += other / float(total)

    return out_counts, out_frac


def count_dict_out(counts, title, misc_thresh=0.01, total=1, **kw):
    print(f"### {title}")
    colname = title.replace(" ", "_")
    out_counts, out_frac = count_dict_collapse_misc(counts, misc_thresh, total, **kw)
    for key, count in sorted(out_counts.items(), key=lambda x: -x[1]):
        print(f"{colname}\t{key}\t{count}\t{out_frac[key]:.3f}")

    return out_counts, out_frac


def count_dict_split(counts, pattern, name):
    import re

    out_d = defaultdict(int)
    for key, value in counts.items():
        if re.search(pattern, key):
            out_d[name] += value
        else:
            out_d[key] += value

    return out_d


def count_dict_to_df(counts, kind="", n_total=0):
    keys_values = sorted(counts.items(), key=lambda x: -x[1])
    import pandas as pd

    df = pd.DataFrame(data=keys_values, columns=["name", "count"])
    if n_total:
        df = df.append({"name": "n_total", "count": n_total}, ignore_index=True)
        df["fraction"] = df["count"] / n_total
    if kind:
        df["kind"] = kind
    return df


def count_dict_from_df(df, kind):
    df = df.query(f"kind == '{kind}'")
    # print(df)
    keys = df["name"]
    values = df["count"]
    return dict(zip(keys, values))


def gather_data_from_overview(df, samples, attr, na=np.nan):
    # print(df)
    # maybe not the most elegant, but doesn't crash on missing values.
    # TODO: look at pivot for a cleaner implementation
    x = np.arange(len(samples))
    # print(attr, samples)
    raw = [df.query(f"sample == '{s}'")[attr].values for s in samples]
    y = [r[0] if len(r) else na for r in raw]

    return x, y
