import logging

import multiprocessing as mp
import pandas as pd
import tqdm
import time

from spacemake.util import message_aggregation, FASTQ_src

logger_name = "spacemake.snakemake.scripts.n_intersect_sequences"
logger = logging.getLogger(logger_name)
AVAILABLE_CPUS = mp.cpu_count()

def setup_parser(parser):
    parser.add_argument(
        "--query",
        type=str,
        help="query reads file for lookup into 'target'(s) database",
        default=None,
    )

    parser.add_argument(
        "--query-tag",
        type=str,
        help="if input is a bam file, the specified tag will be used as the sequence",
        default="CB"
    )

    parser.add_argument(
        "--query-plain-skip",
        type=int,
        help="number of lines to skip, if target input is a plain text file",
        default=None
    )

    parser.add_argument(
        "--query-plain-column",
        type=int,
        help="column to parse from query, if input is a plain text file",
        default=None
    )

    parser.add_argument(
        "--target",
        type=str,
        nargs="+",
        help="target puck files against which search is performed",
        required=True,
    )

    parser.add_argument(
        "--target-id",
        type=str,
        nargs="+",
        help="target puck ids for summary output",
        default=None
    )

    parser.add_argument(
        "--target-tag",
        type=str,
        help="if input is a bam file, the specified tag will be used as the sequence",
        default="CB"
    )

    parser.add_argument(
        "--target-plain-skip",
        type=int,
        help="number of lines to skip, if target input is a plain text file",
        default=None
    )

    parser.add_argument(
        "--target-plain-column",
        type=int,
        help="column to parse from target, if input is a plain text file",
        default=None
    )

    parser.add_argument(
        "--summary-output",
        type=str,
        help="a summary output file containing the number of matches between query and target, per target file",
        required=True,
    )

    parser.add_argument(
        "--n-jobs",
        type=int,
        help='number of parallel jobs (up to {AVAILABLE_CPUS} in this machine) for database lookup',
        metavar=f"[0-{AVAILABLE_CPUS-1}]", 
        choices=range(0,AVAILABLE_CPUS),
        default=1,
    )

    return parser

def BAM_src(src, tag : str = None):
    import pysam

    bam = pysam.AlignmentFile(src, "rb", check_sq=False)
    for read in tqdm.tqdm(bam.fetch(until_eof=True)):
        if tag is None:
            yield read.query_name, read.query_sequence, read.query_qualities
        else:
            yield None, read.get_tag(tag), None

def plain_src(f : str, skip : int = 0, column : int = 0):
    reads = pd.read_csv(f, sep='\t', skiprows=skip)
    reads = reads.iloc[:, column]

    for read in reads:
        yield None, read, None

def read_with_tag(fname: str, tag: str = None, skip: int = None, column : int = 0):
    import gzip

    if type(fname) is not str:
        src = FASTQ_src(fname)  # assume its a stream or file-like object already
    elif fname.endswith(".txt") or fname.endswith(".txt.gz"):
        src = plain_src(fname, skip, column)
    elif fname.endswith(".gz"):
        src = FASTQ_src(gzip.open(fname, mode="rt"))
    elif fname.endswith(".bam"):
        src = BAM_src(fname, tag=tag)
    else:
        src = FASTQ_src(open(fname))
        
    for _, seq, _ in src:
        yield seq

# TODO: use a partial function
def find_matches(f):
    global query_seqs, args
    
    start = time.time()
    target = set(read_with_tag(f, args.target_tag, args.target_plain_skip, args.target_plain_column))
    n_matches = len(target.intersection(query_seqs))
    pct_matches_target = n_matches/len(target)
    print(f"queried {f} in {(time.time()-start)} s")

    return (f, n_matches, len(target), n_matches, pct_matches_target)
    
@message_aggregation(logger_name)
def cmdline():
    """cmdline."""
    import argparse
    # TODO: universally load tsv or csv files; agnostic to format of puck barcode
    # behavior as similar as possible to main.smk create_spatial_barcode_file rule!

    global args, query_seqs

    parser = argparse.ArgumentParser(
        allow_abbrev=False,
        description="calculate the number of shared sequences between a query and target(s) file(s)",
    )
    parser = setup_parser(parser)

    args = parser.parse_args()

    query_seqs = read_with_tag(args.query, args.query_tag, args.query_plain_skip, args.query_plain_column)
    logger.info(f"read query file from '{args.query}'")

    # get unique reads into a global context
    query_seqs = set(query_seqs)
    logger.info(f"hashed unique query reads")
    logger.info(f"querying against {len(args.target)} targets with {args.n_jobs} parallel jobs")

    with mp.Pool(args.n_jobs) as pool:
        results = pool.map(find_matches, args.target)
    
    df = pd.DataFrame(results, columns=['puck_barcode_file', 'puck_barcode_file', 'n_barcodes', 'n_matching', 'matching_ratio'])
    if args.target_id is not None and len(args.target_id) == len(args.target):
        df['puck_barcode_file_id'] = args.target_id
    df.to_csv(args.summary_output)


if __name__ == "__main__":
    cmdline()