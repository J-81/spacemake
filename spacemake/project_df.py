import pandas as pd
import os
import yaml
import math
import argparse
import datetime
import re
import logging
import time

from spacemake.errors import *
from spacemake.config import ConfigFile
from spacemake.util import message_aggregation, assert_file, str_to_list
from spacemake.snakemake.variables import puck_barcode_files_summary
from typing import List, Dict

logger_name = "spacemake.project_df"
logger = logging.getLogger(logger_name)
# logging.basicConfig(level=logging.INFO)


def get_project_sample_parser(allow_multiple=False, prepend="", help_extra=""):
    """
    Return a parser for project_id's and sample_id's

    :param allow_multiple: if true, we allow multiple projects and samples,
        and the parser will have a `--project_id_list` and a `--sample_id_list`
        parameter
    :param prepend: a string that will be prepended before the arguments
    :param help_extra: extra help message
    :return: a parser object
    :rtype: argparse.ArgumentParser
    """
    logger.info(f"get_project_sample_parser(prepend={prepend}) called")

    parser = argparse.ArgumentParser(allow_abbrev=False, add_help=False)
    project_argument = "project_id"
    sample_argument = "sample_id"
    required = True
    nargs = None
    default = None

    if allow_multiple:
        project_argument = f"{project_argument}_list"
        sample_argument = f"{sample_argument}_list"
        required = False
        nargs = "*"
        default = []

    parser.add_argument(
        f"--{prepend}{project_argument}",
        type=str,
        required=required,
        nargs=nargs,
        default=default,
        help=f"{project_argument} {help_extra}",
    )

    parser.add_argument(
        f"--{prepend}{sample_argument}",
        type=str,
        required=required,
        nargs=nargs,
        default=default,
        help=f"{sample_argument} {help_extra}",
    )

    return parser


def get_add_sample_sheet_parser():
    """
    Returns parser for sample sheet addition

    :return: parser
    :rtype: argparse.ArgumentParser
    """
    logger.info("get_add_sample_sheet_parser() called")
    parser = argparse.ArgumentParser(
        allow_abbrev=False,
        description="add a new sample sheet to the samples",
        add_help=False,
    )

    parser.add_argument(
        "--sample_sheet",
        type=str,
        help="the path to the Illumina sample sheet",
        required=True,
    )
    parser.add_argument(
        "--basecalls_dir",
        type=str,
        help="path to the basecalls directory",
        required=True,
    )

    return parser


def get_sample_main_variables_parser(
    species_required=False,
    main_variables=["barcode_flavor", "species", "puck", "run_mode", "map_strategy"],
):
    parser = argparse.ArgumentParser(allow_abbrev=False, add_help=False)
    logger.info(
        f"get_sample_main_variables_parser called with main_variables={main_variables}"
    )

    if "barcode_flavor" in main_variables:
        parser.add_argument(
            "--barcode_flavor", type=str, help="barcode flavor for this sample"
        )

    if "species" in main_variables:
        parser.add_argument(
            "--species",
            type=str,
            help="add the name of the species for this sample",
            required=species_required,
        )

    if "map_strategy" in main_variables:
        parser.add_argument(
            "--map_strategy",
            type=str,
            help="string constant definining mapping strategy. Can be multi-stage and use bowtie2 or STAR (see documentation)",
            required=False,
            default=None,
        )

    if "puck" in main_variables:
        parser.add_argument(
            "--puck",
            type=str,
            help="name of the puck for this sample. if puck_type contains a \n"
            + "`barcodes` path to a coordinate file, those coordinates\n"
            + " will be used when processing this sample. if \n"
            + " not provided, a default puck will be used with \n"
            + "width_um=3000, spot_diameter_um=10",
        )

        parser.add_argument(
            "--puck_barcode_file_id",
            type=str,
            help="puck_barcode_file_id of the sample to be added/update",
            nargs="+",
        )

    parser.add_argument(
        "--puck_barcode_file",
        type=str,
        nargs="+",
        help="the path to the file contining (x,y) positions of the barcodes",
    )

    if "run_mode" in main_variables:
        parser.add_argument(
            "--run_mode",
            type=str,
            nargs="+",
            help="run_mode names for this sample.\n"
            + "the sample will be processed using the provided run_modes.\n"
            + "for merged samples, if left empty, the run_modes of the \n"
            + "merged (input) samples will be intersected.\n",
        )

    return parser


def get_sample_extra_info_parser():
    logger.info("get_sample_extra_info_parser() called")
    parser = argparse.ArgumentParser(allow_abbrev=False, add_help=False)

    parser.add_argument(
        "--investigator",
        type=str,
        help="add the name of the investigator(s) responsible for this sample",
    )

    parser.add_argument("--experiment", type=str, help="description of the experiment")

    parser.add_argument(
        "--sequencing_date",
        type=datetime.date.fromisoformat,
        help="sequencing date of the sample. format: YYYY-MM-DD",
    )

    return parser


def get_data_parser(reads_required=False):
    """
    Returns a parser which contain extra arguments for a given sample.
    The returned parser will contain the --R1, --R2, --longreads,
    --longread-signature, --barcode_flavor, --species, --puck,  --puck_barcode_file_id,
    --puck_barcode_file, --investigator, --experiment, --sequencing_date,
    --run_mode arguments.

    :param species_required: if true, the --species argument will be required
        during parsing.
    :param reads_required: if true, --R1, --R2, and --longreads arguments will be
        required during parsing.
    """
    parser = argparse.ArgumentParser(allow_abbrev=False, add_help=False)
    logger.info("get_data_parser() called")
    parser.add_argument(
        "--R1",
        type=str,
        help=".fastq.gz file path to R1 reads",
        nargs="+",
        required=reads_required,
    )

    parser.add_argument(
        "--R2",
        type=str,
        help=".fastq.gz file path to R2 reads",
        nargs="+",
        required=reads_required,
    )

    parser.add_argument(
        "--dge",
        type=str,
        help="Path to dge matrix. spacemake can also handle already processed"
        + " digital expression data",
        required=reads_required,
    )

    parser.add_argument(
        "--longreads",
        type=str,
        help="fastq(.gz)|fq(.gz)|bam file path to pacbio long reads for library debugging",
        required=reads_required,
    )

    parser.add_argument(
        "--longread-signature",
        type=str,
        help="identify the expected longread signature (see longread.yaml)",
    )

    return parser


def get_set_remove_variable_subparsers(
    parent_parser, variable_name, func, prepend="", allow_multiple=False
):
    """get_set_remove_variable_subparsers.

    :param parent_parser:
    :param variable_name:
    :param func:
    :param prepend:
    :param allow_multiple:
    """
    if allow_multiple:
        nargs = "+"
    else:
        nargs = None

    logger.info(f"get_set_remove_variable_subparsers(varname={variable_name}) called")

    def get_action_parser(action):
        """get_action_parser.

        :param action:
        """
        action_parser = parent_parser.add_parser(
            f"{action}_{variable_name}",
            parents=[get_project_sample_parser(allow_multiple=True)],
            description=f"{action} {variable_name} for several projects/samples",
            help=f"{action} {variable_name} for several projects/samples",
        )
        action_parser.add_argument(
            f"--{variable_name}", type=str, required=True, nargs=nargs
        )
        action_parser.set_defaults(func=func, variable=variable_name, action=action)

        return action_parser

    set_parser = get_action_parser("set")

    if allow_multiple:
        set_parser.add_argument("--keep_old", action="store_true")

        remove_parser = get_action_parser("remove")


def get_action_sample_parser(parent_parser, action, func):
    """get_action_sample_parser.

    :param parent_parser:
    :param action:
    :param func:
    """
    logger.info(f"get_action_sample_parser(action={action}) called")
    if action not in ["add", "update", "delete", "merge"]:
        raise ValueError(f"Invalid action: {action}")

    if action == "merge":
        parser_name = "merge_samples"
        msg = "merge samples"
        parents = [
            get_project_sample_parser(
                prepend="merged_", help_extra="of the newly created merged sample"
            ),
            get_project_sample_parser(
                allow_multiple=True, help_extra="of the samples to be merged"
            ),
        ]
    else:
        parser_name = f"{action}_sample"
        msg = f"{action} a sample"
        parents = [get_project_sample_parser()]

    if action == "add":
        # add arguments for species, run_mode, barcode_flavor and puck
        parents.append(
            get_sample_main_variables_parser(
                species_required=True,
            )
        )
        # add arguments for R1/R1, dge, longread
        parents.append(get_data_parser())
        # add arguments for extra sample info
        parents.append(get_sample_extra_info_parser())
    elif action == "update":
        # add main variables parser
        parents.append(get_sample_main_variables_parser())

        # add possibility to add extra info
        parents.append(get_sample_extra_info_parser())
    elif action == "merge":
        # add main variables parser
        # when merging, only let the user overwrite puck and run_mode
        parents.append(
            get_sample_main_variables_parser(
                main_variables=["run_mode", "puck"],
            )
        )

        # add possibility to add extra info
        parents.append(get_sample_extra_info_parser())

    sample_parser = parent_parser.add_parser(
        parser_name, description=msg, help=msg, parents=parents
    )
    sample_parser.set_defaults(func=func, action=action)


def setup_project_parser(pdf, parent_parser_subparsers):
    """setup_project_parser.

    :param pdf:
    :param attach_to:
    """
    parser = parent_parser_subparsers.add_parser(
        "projects",
        help="manage projects and samples",
        description="Using one of the subcommands specified below, it is possible to"
        + " add/update/remove projects and their settings",
    )
    subparsers = parser.add_subparsers()

    help_desc = {
        "add_sample_sheet": "add projects and samples from Illumina sample sheet",
        "add_samples_from_yaml": "add several samples at once from a .yaml file",
        "merge_samples": "merge several samples into one. "
        + "samples need to have the same species",
        "list": "list several project(s) and sample(s) and their settings",
    }

    # ADD/UPDATE/DELETE/MERGE sample(s)
    # get parsers for adding, deleting and updating a sample
    for action in ["add", "update", "delete"]:
        get_action_sample_parser(
            subparsers,
            action,
            # attach the function to the parser
            func=lambda args: add_update_delete_sample_cmdline(pdf, args),
        )

    # get parser for merging
    get_action_sample_parser(
        subparsers, "merge", func=lambda args: merge_samples_cmdline(pdf, args)
    )

    # LIST PROJECTS
    # always show these variables
    always_show = [
        "puck_barcode_file_id",
        "species",
        "investigator",
        "sequencing_date",
        "experiment",
        "run_mode",
        "barcode_flavor",
        "map_strategy",
    ]
    remaining_options = [
        x for x in pdf.project_df_default_values.keys() if x not in always_show
    ]
    list_projects = subparsers.add_parser(
        "list",
        description=help_desc["list"],
        help=help_desc["list"],
        parents=[
            get_project_sample_parser(
                allow_multiple=True,
                help_extra="subset the data. If none provided, all will be displayed",
            )
        ],
    )
    list_projects.add_argument(
        "--variables",
        help="which extra variables to display per sample? "
        + f"{always_show} will always be shown.",
        choices=remaining_options,
        default=[],
        nargs="*",
    )
    list_projects.set_defaults(
        func=lambda args: list_projects_cmdline(pdf, args), always_show=always_show
    )

    # ADD SAMPLE SHEET
    sample_add_sample_sheet = subparsers.add_parser(
        "add_sample_sheet",
        description=help_desc["add_sample_sheet"],
        help=help_desc["add_sample_sheet"],
        parents=[get_add_sample_sheet_parser()],
    )
    sample_add_sample_sheet.set_defaults(
        func=lambda args: add_sample_sheet_cmdline(pdf, args)
    )

    # ADD SAMPLES FROM YAML
    sample_add_samples_yaml = subparsers.add_parser(
        "add_samples_from_yaml",
        description=help_desc["add_samples_from_yaml"],
        help=help_desc["add_samples_from_yaml"],
    )
    sample_add_samples_yaml.add_argument(
        "--samples_yaml",
        type=str,
        required=True,
        help="path to the .yaml file containing sample info",
    )
    sample_add_samples_yaml.set_defaults(
        func=lambda args: add_samples_from_yaml_cmdline(pdf, args)
    )

    # get set/remove parser for each main variable
    # this will add parser for:
    # setting/removing run_mode
    # setting species
    # setting puck
    # setting barcode_flavor
    # NOTE: the ConfigFile.main_variable_sg2type keys determine
    # which commandline args will be defined for the parser.
    # this is a little un-intuitive...
    # TODO: cleaner factory functions for the commandline-parsers
    for main_var_sg, main_var_type in ConfigFile.main_variable_sg2type.items():
        allow_multiple = False
        if isinstance(main_var_type, str) and main_var_type.endswith("_list"):
            allow_multiple = True

        get_set_remove_variable_subparsers(
            subparsers,
            variable_name=main_var_sg,
            func=lambda args: set_remove_variable_cmdline(pdf, args),
            allow_multiple=allow_multiple,
        )
    return parser


@message_aggregation(logger_name)
def add_update_delete_sample_cmdline(pdf, args):
    """add_update_delete_sample_cmdline.

    :param pdf:
    :param args:
    """
    action = args["action"]

    # remove the action from args
    del args["action"]

    if action == "add" or action == "update":
        func = lambda **kwargs: pdf.add_update_sample(action=action, **kwargs)
    elif action == "delete":
        func = pdf.delete_sample

    sample = func(**args)
    pdf.dump()


@message_aggregation(logger_name)
def add_sample_sheet_cmdline(pdf, args):
    """add_sample_sheet_cmdline.

    :param pdf:
    :param args:
    """
    pdf.add_sample_sheet(args["sample_sheet"], args["basecalls_dir"])

    pdf.dump()


@message_aggregation(logger_name)
def add_samples_from_yaml_cmdline(pdf, args):
    """add_samples_from_yaml_cmdline.

    :param pdf:
    :param args:
    """
    pdf.add_samples_from_yaml(args["samples_yaml"])

    pdf.dump()


@message_aggregation(logger_name)
def set_remove_variable_cmdline(pdf, args):
    """set_remove_variable_cmdline.

    :param pdf:
    :param args:
    """
    variable_name = args["variable"]
    action = args["action"]

    variable_key = args[variable_name]

    pdf.set_remove_variable(
        variable_name=variable_name,
        variable_key=variable_key,
        action=action,
        project_id_list=args["project_id_list"],
        sample_id_list=args["sample_id_list"],
        keep_old=args.get("keep_old", False),
    )

    pdf.dump()


@message_aggregation(logger_name)
def merge_samples_cmdline(pdf, args):
    """merge_samples_cmdline.

    :param pdf:
    :param args:
    """
    pdf.merge_samples(**args)

    pdf.dump()


@message_aggregation(logger_name)
def list_projects_cmdline(pdf, args):
    """list_projects_cmdline.

    :param pdf:
    :param args:
    """
    projects = args["project_id_list"]
    samples = args["sample_id_list"]
    variables = args["always_show"] + args["variables"]

    df = pdf.df
    logger = logging.getLogger(logger_name)

    if projects != [] or samples != []:
        df = df.query("project_id in @projects or sample_id in @samples")
        logger.inof(f"listing projects: {projects} and samples: {samples}")
    else:
        logger.info("listing all projects and samples")

    logger.info(f"variables used: {variables}")

    # print the table
    logger.info(df.loc[:, variables].__str__())


class ProjectDF:
    """
    ProjectDF: class responsible for managing spacemake projects.

    :param file_path: path to the project_df.csv file, where we will save the project list.
    :param config: config file object
    :type config: ConfigFile
    :param df: A pandas dataframe, containing one row per sample
    :type df: pd.DataFrame
    """

    # default values of the project dataframe columns
    project_df_default_values = {
        "puck_barcode_file_id": ["no_spatial_data"],
        "sample_sheet": None,
        "species": None,
        "demux_barcode_mismatch": 1,
        "demux_dir": None,
        "basecalls_dir": None,
        "R1": None,
        "R2": None,
        "longreads": None,
        "longread_signature": None,
        "investigator": "unknown",
        "sequencing_date": "unknown",
        "experiment": "unknown",
        "puck_barcode_file": None,
        "run_mode": ["default"],
        "barcode_flavor": "default",
        "is_merged": False,
        "merged_from": [],
        "puck": "default",
        "dge": None,
        "map_strategy": {  # default mapping strategy changes depending on if we have rRNA or not
            True: "bowtie2:rRNA,STAR:genome:final",  # map in parallel to rRNA and genome (default so far)
            False: "STAR:genome:final",  # w/o rRNA, map to genome directly
        },
    }

    project_df_dtypes = {
        "puck_barcode_file_id": "object",
        "sample_sheet": "str",
        "species": "str",
        "demux_barcode_mismatch": "int64",
        "demux_dir": "str",
        "basecalls_dir": "str",
        "R1": "object",
        "R2": "object",
        "longreads": "str",
        "longread_signature": "str",
        "investigator": "str",
        "sequencing_date": "str",
        "experiment": "str",
        "puck_barcode_file": "object",
        "run_mode": "object",
        "barcode_flavor": "str",
        "is_merged": "bool",
        "merged_from": "object",
        "puck": "str",
        "dge": "str",
    }

    def __init__(self, file_path, config: ConfigFile = None):
        """__init__.

        :param file_path: path to pandas data frame (saved as .csv)
        :param config: ConfigFile
        :type config: ConfigFile
        """
        self.file_path = file_path
        self.config = config

        if os.path.isfile(file_path):
            attempts = 0
            failed = False

            while not failed:
                try:
                    self.df = pd.read_csv(
                        file_path,
                        index_col=["project_id", "sample_id"],
                        na_values=["None", "none"],
                        dtype=self.project_df_dtypes,
                    )
                    failed = True
                except pd.errors.EmptyDataError as e:
                    if attempts < 5:
                        # wait 5 seconds before retrying
                        time.sleep(5)
                        attempts = attempts + 1
                        continue
                    else:
                        raise e
                        failed = True

            if self.df.empty:
                self.create_empty_df()
            else:
                # 'fix' the dataframe if there are inconsistencies
                self.fix()
        else:
            self.create_empty_df()

        self.logger = logging.getLogger(logger_name)

    def create_empty_df(self):
        index = pd.MultiIndex(
            names=["project_id", "sample_id"], levels=[[], []], codes=[[], []]
        )
        self.df = pd.DataFrame(self.project_df_default_values, index=index)

        self.df = self.df.astype(self.project_df_dtypes)

    def compute_max_barcode_mismatch(self, indices: List[str]) -> int:
        """compute_max_barcode_mismatch.

        :param indices: List of illumina I7 index barcodes
        :type indices: List[str]
        :return: the maximum mismatch to be allowed for this set of index barcodes
        :rtype: int
        """
        num_samples = len(indices)

        if num_samples == 1:
            return 4
        else:
            max_mismatch = 3
            for i in range(num_samples - 1):
                for j in range(i + 1, num_samples):
                    hd = self.hamming_distance(indices[i], indices[j])
                    max_mismatch = min(max_mismatch, math.ceil(hd / 2) - 1)

        return max_mismatch

    def hamming_distance(self, string1: str, string2: str) -> int:
        """Cacluate hamming distance between two strings

        :param string1:
        :type string1: str
        :param string2:
        :type string2: str
        :rtype: int
        """
        return sum(c1 != c2 for c1, c2 in zip(string1, string2))

    def find_barcode_file(self, puck_barcode_file_id: str) -> str:
        """Tries to find path of a barcode file, using the puck_barcode_file_id.

        :param puck_barcode_file_id: puck_barcode_file_id of the puck we are looking for.
        :type puck_barcode_file_id: str
        :return: path of the puck file, containing barcodes, or None
        :rtype: str
        """
        # first find directory of puck file

        # return none or the path of the file
        def get_barcode_file(path):
            """get_barcode_file.

            :param path:
            """
            if os.path.isfile(path):
                return path

            return None

        def find_dir(name, path):
            """find_dir.

            :param name:
            :param path:
            """
            for root, dirs, files in os.walk(path):
                if name in dirs:
                    return os.path.join(root, name)

        puck_dir = find_dir(puck_barcode_file_id, self.config.puck_data["root"])
        path = None

        if puck_dir is not None:
            # puck dir exists, look for barcode file pattern
            path = os.path.join(puck_dir, self.config.puck_data["barcode_file"])

            return get_barcode_file(path)
        else:
            return self.project_df_default_values["puck_barcode_file"]

    def get_sample_info(self, project_id: str, sample_id: str) -> Dict:
        """get_sample_info.

        :param project_id:
        :type project_id: str
        :param sample_id:
        :type sample_id: str
        :return: A dictionary containing all the values of a given sample, from the ProjectDF.
        :rtype: Dict
        """
        # returns sample info from the projects df
        self.assert_sample(project_id, sample_id)
        out_dict = self.df.loc[(project_id, sample_id)].to_dict()

        return out_dict

    def is_external(self, project_id: str, sample_id: str) -> bool:
        """is_external.

        :param project_id:
        :type project_id: str
        :param sample_id:
        :type sample_id: str
        :rtype: bool
        """
        self.assert_sample(project_id, sample_id)

        data = self.df.loc[
            (project_id, sample_id),
            [
                "R1",
                "R2",
                "basecalls_dir",
                "sample_sheet",
                "longreads",
                "dge",
                "is_merged",
            ],
        ]

        self.logger.debug(
            f"project_id={project_id} sample_id={sample_id} "
            + f"R1,2={bool(data.R1 and data.R2)} "
            + f"basecall={(data.basecalls_dir and data.sample_sheet)} "
            + f"longreads={bool(data.longreads)} dge={bool(data.dge)} "
            + f"is_merged={bool(data.is_merged)}"
        )
        if (
            (data.R1 and data.R2)
            or (data.basecalls_dir and data.sample_sheet)
            or (data.longreads)
            and not data.dge
            or data.is_merged
        ):
            return False
        elif data.dge:
            return True
        else:
            raise SpacemakeError(
                f"Sample with id (project_id, sample_id)="
                + f"({project_id}, {sample_id}) is invalid."
            )

    def has_dge(self, project_id: str, sample_id: str) -> bool:
        """Returns True if a has dge. for Pacbio only samples returns False.

        :param project_id:
        :type project_id: str
        :param sample_id:
        :type sample_id: str
        :rtype: bool
        """
        self.assert_sample(project_id, sample_id)

        data = self.df.loc[
            (project_id, sample_id),
            [
                "R1",
                "R2",
                "basecalls_dir",
                "sample_sheet",
                "longreads",
                "dge",
                "is_merged",
            ],
        ]

        if (
            data.is_merged
            or (data.R1 and data.R2)
            or (data.sample_sheet and data.basecalls_dir)
            or data.dge
        ):
            return True
        elif data.longreads:
            return False
        else:
            raise SpacemakeError(
                f"Sample with id (project_id, sample_id)="
                + f"({project_id}, {sample_id}) is invalid."
            )

    def is_spatial(
        self, project_id: str, sample_id: str, puck_barcode_file_id: str
    ) -> bool:
        """Returns true if a sample with index (project_id, sample_id) is spatial,
        meaning that it has spatial barcodes attached.

        :param project_id:
        :type project_id: str
        :param sample_id:
        :type sample_id: str
        :rtype: bool
        """
        self.assert_sample(project_id, sample_id)
        puck_barcode_file = self.get_puck_barcode_file(
            project_id=project_id,
            sample_id=sample_id,
            puck_barcode_file_id=puck_barcode_file_id,
        )

        if puck_barcode_file is not None:
            return True
        else:
            return False

    def get_default_map_strategy_for_species(self, species):
        have_rRNA = "rRNA" in self.config.variables["species"][species]
        map_strategy = self.project_df_default_values["map_strategy"][have_rRNA]
        print(
            f"getting default for '{species}' have_rRNA={have_rRNA} -> {map_strategy}"
        )
        return map_strategy

    def fix(self):
        import numpy as np

        # convert types
        self.df = self.df.where(pd.notnull(self.df), None)
        self.df = self.df.replace({np.nan: None})
        # replacing NaN with None

        # rename puck_id to puck_barcode_file_id, for backward
        # compatibility
        self.df.rename(
            columns={"puck_id": "puck_barcode_file_id"},
            inplace=True,
        )

        # convert list values stored as string
        self.df.run_mode = self.df.run_mode.apply(str_to_list)
        self.df.merged_from = self.df.merged_from.apply(str_to_list)

        # convert R1/R2 to list, if they are stored as string
        self.df.R1 = self.df.R1.apply(str_to_list)
        self.df.R2 = self.df.R2.apply(str_to_list)

        self.df.puck_barcode_file_id = self.df.puck_barcode_file_id.apply(str_to_list)
        self.df.puck_barcode_file = self.df.puck_barcode_file.apply(str_to_list)

        project_list = []
        # required if upgrading from pre-longread tree
        if not "longreads" in self.df.columns:
            self.df["longreads"] = None

        if not "longread_signature" in self.df.columns:
            self.df["longread_signature"] = None

        # required if upgrading from pre-bowtie2/map-strategy tree
        if not "map_strategy" in self.df.columns:
            self.df["map_strategy"] = self.df["species"].apply(
                self.get_default_map_strategy_for_species
            )

        # per row updates
        # first create a series of a
        for ix, row in self.df.iterrows():
            s = pd.Series(self.project_df_default_values)

            # update puck barcode file info
            # for samples which have shared barcodes, and this barcode info is
            # stored in a puck, in the config file, before the id was set to
            # the name of the puck, and the puck_barcode_file was set to None.
            # Here we populate the puck_barcode_file into the path to the actual
            # file so that no errors are caused downstream.
            if (
                row["puck_barcode_file"] is None
                and row["puck_barcode_file_id"] is not None
            ):
                if len(row["puck_barcode_file_id"]) > 1:
                    raise SpacemakeError(
                        "When no barcode file provided, there "
                        + "only should be one id available"
                    )

                pbf_id = row["puck_barcode_file_id"][0]
                if pbf_id not in self.project_df_default_values["puck_barcode_file_id"]:
                    puck = self.config.get_puck(pbf_id)

                    row["puck_barcode_file"] = [puck.variables["barcodes"]]

            s.update(row)
            s.name = row.name
            project_list.append(s)

        self.df = pd.concat(project_list, axis=1).T
        self.df.is_merged = self.df.is_merged.astype(bool)
        self.df.index.names = ["project_id", "sample_id"]

    def get_puck_barcode_file(
        self, project_id: str, sample_id: str, puck_barcode_file_id: str
    ) -> str:
        if (
            puck_barcode_file_id
            in self.project_df_default_values["puck_barcode_file_id"]
        ):
            # if sample is not spatial, or we request the non-spatial puck
            return None
        else:
            ids = self.get_metadata(
                "puck_barcode_file_id", sample_id=sample_id, project_id=project_id
            )

            puck_barcode_files = self.get_metadata(
                "puck_barcode_file", sample_id=sample_id, project_id=project_id
            )

            # if no puck_barcode_file is provided, it means that barcode
            # file has to be fetched from the puck itself
            if puck_barcode_files is not None:
                for pid, pbf in zip(ids, puck_barcode_files):
                    if pid == puck_barcode_file_id:
                        return pbf

                return None

    def get_puck_barcode_ids_and_files(
        self,
        project_id: str,
        sample_id: str,
    ) -> str:
        puck_barcode_file_ids = self.get_metadata(
            "puck_barcode_file_id", project_id=project_id, sample_id=sample_id
        )

        puck_barcode_files = self.get_metadata(
            "puck_barcode_file", project_id=project_id, sample_id=sample_id
        )

        out_puck_barcode_files = []
        out_puck_barcode_file_ids = []

        # return only id-file pairs, for which file is not none
        if puck_barcode_files is not None:
            for pbf_id, pbf in zip(puck_barcode_file_ids, puck_barcode_files):
                out_puck_barcode_files.append(pbf)
                out_puck_barcode_file_ids.append(pbf_id)

        return out_puck_barcode_file_ids, out_puck_barcode_files

    def get_matching_puck_barcode_file_ids(
        self,
        project_id: str,
        sample_id: str,
    ):
        summary_file = puck_barcode_files_summary.format(
            project_id=project_id, sample_id=sample_id
        )

        if not os.path.isfile(summary_file):
            return self.project_df_default_values["puck_barcode_file_id"]

        df = pd.read_csv(summary_file)

        # Comment the following line that restricts the analysis of some tiles.
        # All tiles provided will now be processed -- it's up to the user to
        # provide a meaningful list of tiles.
        #
        # df = df.loc[(df.n_matching > 500) & (df.matching_ratio > 0.1)]

        pdf_ids = df.puck_barcode_file_id.to_list()

        pdf_ids.append(self.project_df_default_values["puck_barcode_file_id"][0])

        return pdf_ids

    def get_puck_barcode_file_metrics(
        self,
        project_id: str,
        sample_id: str,
        puck_barcode_file_id: str,
    ):
        summary_file = puck_barcode_files_summary.format(
            project_id=project_id, sample_id=sample_id
        )

        if not os.path.isfile(summary_file):
            return None

        df = pd.read_csv(summary_file)

        df = df.loc[df.puck_barcode_file_id == puck_barcode_file_id]

        if df.empty:
            return None
        else:
            return df.iloc[0].to_dict()

    def get_puck_variables(
        self, project_id: str, sample_id: str, return_empty=False
    ) -> Dict:
        """get_puck_variables.

        :param project_id: project_id of a sample
        :type project_id: str
        :param sample_id: sample_id of a sample
        :type sample_id: str
        :param return_empty:
        :return: A dictionary containing the puck variables of a given sample
        :rtype: Dict
        """
        puck_name = self.get_metadata(
            "puck", project_id=project_id, sample_id=sample_id
        )

        return self.config.get_puck(puck_name, return_empty=return_empty).variables

    def get_metadata(self, field, project_id=None, sample_id=None, **kwargs):
        """get_metadata.

        :param field:
        :param project_id:
        :param sample_id:
        :param kwargs:
        """
        df = self.df
        if sample_id is not None:
            df = df.query("sample_id == @sample_id")

        if project_id is not None:
            df = df.query("project_id == @project_id")

        for key, value in kwargs.items():
            df = df.loc[df.loc[:, key] == value]

        dl = df.loc[:, field].to_list()
        if len(dl):
            return dl[0]
        else:
            return ""

    def dump(self):
        """dump."""
        self.df.to_csv(self.file_path)

    def add_sample_sheet(self, sample_sheet_path, basecalls_dir):
        """add_sample_sheet.

        :param sample_sheet_path:
        :param basecalls_dir:
        """
        with open(sample_sheet_path) as sample_sheet:
            ix = 0
            investigator = None
            sequencing_date = None

            for line in sample_sheet:
                line = line.strip("\n")
                if "Investigator" in line:
                    investigator = line.split(",")[1]
                if "Date" in line:
                    sequencing_date = line.split(",")[1]
                if "[Data]" in line:
                    # the counter ix stops here
                    break
                else:
                    ix = ix + 1

        # read everything after [Data]
        df = pd.read_csv(sample_sheet_path, skiprows=ix + 1)
        # rename columns
        to_rename = {
            "Sample_ID": "sample_id",
            "Sample_Name": "puck_barcode_file_id",
            "Sample_Project": "project_id",
            "Description": "experiment",
            "index": "index",
        }
        df.rename(
            columns=to_rename,
            inplace=True,
        )
        # select only renamed columns
        df = df[to_rename.values()]
        df["species"] = df["experiment"].str.split("_").str[-1]
        df["investigator"] = investigator
        df["sequencing_date"] = sequencing_date

        # rename columns
        df["basecalls_dir"] = basecalls_dir
        df["demux_barcode_mismatch"] = self.compute_max_barcode_mismatch(df["index"])
        df["sample_sheet"] = sample_sheet_path
        df["demux_dir"] = (
            df["sample_sheet"].str.split("/").str[-1].str.split(".").str[0]
        )
        df["puck_barcode_file"] = df.puck_barcode_file_id.apply(self.find_barcode_file)
        df.set_index(["project_id", "sample_id"], inplace=True)

        for ix, row in df.iterrows():
            self.add_update_sample(project_id=ix[0], sample_id=ix[1], **row.to_dict())

    def assert_index_value(self, index_value, index_level):
        if not isinstance(index_value, list):
            index_value = [index_value]

        ixs = self.df.index.get_level_values(index_level)

        for ixv in index_value:
            if ixv not in ixs:
                raise ProjectSampleNotFoundError(index_level, ixv)

    def sample_exists(self, project_id=None, sample_id=None):
        """sample_exists.

        :param project_id:
        :param sample_id:
        """
        if project_id is None or sample_id is None:
            raise Exception(
                f"you need to provide a sample_id and project_id to check if sample exists"
            )
        else:
            ix = (project_id, sample_id)

            return ix in self.df.index

    def assert_sample(self, project_id, sample_id):
        if not self.sample_exists(project_id, sample_id):
            raise ProjectSampleNotFoundError(
                "(project_id, sample_id)", (project_id, sample_id)
            )

    def assert_run_mode(self, project_id, sample_id, run_mode_name):
        variables = self.get_sample_info(project_id, sample_id)

        if run_mode_name not in variables["run_mode"]:
            raise SpacemakeError(
                f"(project_id, sample_id)=({project_id},"
                + f"{sample_id}) has no run_mode={run_mode_name}\n"
                + f'run_mode has to be one of {variables["run_mode"]}'
            )

    def add_update_sample(
        self,
        action=None,
        project_id=None,
        sample_id=None,
        R1=None,
        R2=None,
        dge=None,
        longreads=None,
        longread_signature=None,
        sample_sheet=None,
        basecalls_dir=None,
        is_merged=False,
        return_series=False,
        map_strategy=None,
        puck_barcode_file=None,
        puck_barcode_file_id=None,
        **kwargs,
    ):
        """add_update_sample.

        :param action:
        :param project_id:
        :param sample_id:
        :param R1:
        :param R2:
        :param dge:
        :param longreads:
        :param longread_signature:
        :param sample_sheet:
        :param basecalls_dir:
        :param is_merged:
        :param return_series:
        :param map_strategy:
        :param kwargs:
        """
        ix = (project_id, sample_id)
        sample_exists = self.sample_exists(*ix)

        if action is None and sample_exists:
            action = "update"
        elif action is None and not sample_exists:
            action = "add"
        elif action == "add" and sample_exists:
            raise SampleAlreadyExistsError(ix)
        elif action == "update" and not sample_exists:
            raise ProjectSampleNotFoundError("(project_id, sample_id)", ix)

        if action == "add":
            self.logger.info(f"Adding sample {ix}")
        elif action == "update":
            self.logger.info(f"Updating sample {ix}")
        else:
            raise ValueError(f"Unknown action {action}")

        # check variables
        # First we check if R1 and R2 is present.
        # If not, we check for longreads. If provided, we also need
        #   --longread-signature
        # If longreads not provided, we try with basecalls_dir and sample_sheet
        #   (only used by add_sample_sheet command)
        # If those area also not provided, we try to add a simple dge
        if action == "add" and (R1 is None or R2 is None) and not is_merged:
            self.logger.info("R1 or R2 not provided, trying longreads")

            if not longreads:
                self.logger.info(
                    "longreads not provided, trying basecalls_dir and sample_sheet"
                )
                if basecalls_dir is None or sample_sheet is None:
                    self.logger.info(
                        "basecalls_dir or sample_sheet not provided, trying dge"
                    )
                    if not dge:
                        raise SpacemakeError(
                            "Neither R1 & R2, longreads, basecalls_dir & "
                            + "sample_sheet, nor dge were provided.\n"
                            + "Some reads/data has to be provided"
                        )
            else:
                if not longread_signature:
                    raise SpacemakeError(
                        "adding longreads requires to set --longread-signature as well (e.g. dropseq, chromium, noUMI, default, visium, slideseq_bc14,...)"
                    )

        # assert files first
        assert_file(R1, default_value=None, extension=".fastq.gz")
        assert_file(R2, default_value=None, extension=".fastq.gz")
        assert_file(longreads, default_value=None, extension="all")
        assert_file(
            dge,
            default_value=None,
            extension=[".h5", ".csv", ".h5ad", ".loom", ".txt", ".txt.gz"],
        )

        # assign reads
        # if there are strings, make them lists, as one sample can have many read files
        if R1 is not None and isinstance(R1, str):
            R1 = [R1]

        if R2 is not None and isinstance(R2, str):
            R2 = [R2]

        if R1 is not None and R2 is not None:
            if len(R1) != len(R2):
                raise SpacemakeError(
                    f"Trying to set an unmatching number of "
                    + f"read pairs for sample: {ix}.\n"
                    + f"# of R1 files = {len(R1)}\n"
                    + f"# of R2 files = {len(R2)}"
                )

        if "run_mode" in kwargs and isinstance(kwargs["run_mode"], str):
            # if a single run mode is provided as a string
            # create a list manually
            kwargs["run_mode"] = [kwargs["run_mode"]]

        # check if run mode exists
        for run_mode in kwargs.get("run_mode", []):
            if not self.config.variable_exists("run_modes", run_mode):
                raise ConfigVariableNotFoundError("run_modes", run_mode)

        config_variables_to_check = {
            "pucks": "puck",
            "barcode_flavors": "barcode_flavor",
            "species": "species",
        }

        for cv_plural, cv_singular in config_variables_to_check.items():
            if cv_singular in kwargs.keys():
                if not self.config.variable_exists(cv_plural, kwargs[cv_singular]):
                    raise ConfigVariableNotFoundError(cv_singular, kwargs[cv_singular])

        # if everything correct, add or update
        # first populate kwargs
        kwargs["R1"] = R1
        kwargs["R2"] = R2
        kwargs["dge"] = dge
        kwargs["longreads"] = longreads
        kwargs["longread_signature"] = longread_signature
        kwargs["sample_sheet"] = sample_sheet
        kwargs["basecalls_dir"] = basecalls_dir
        kwargs["is_merged"] = is_merged

        if action == "add" and map_strategy is None:
            # was not specified! Let's evaluate the default for this species
            # (depends on having rRNA reference or not)
            map_strategy = self.get_default_map_strategy_for_species(kwargs["species"])

        if (map_strategy is not None) and (map_strategy.endswith("-")):
            self.logger.warning(
                (
                    f"\n!!!!WARNING!!!\n map_strategy '{map_strategy}' ends with a trailing dash."
                    " Please ensure map_strategy is escaped with double-quotes, or the shell"
                    " interpretes the chevron in '->' as a redirect."
                )
            )

        kwargs["map_strategy"] = map_strategy

        # populate puck_barcode_file
        if puck_barcode_file is not None:
            if isinstance(puck_barcode_file, str):
                puck_barcode_file = [puck_barcode_file]

            # if there are duplicates, raise error
            if len(puck_barcode_file) != len(set(puck_barcode_file)):
                raise SpacemakeError(
                    "Duplicate files provided for "
                    + "--puck_barcode_file. \n"
                    + f"files provided: {puck_barcode_file}"
                )

        if puck_barcode_file_id is not None:
            if isinstance(puck_barcode_file_id, str):
                puck_barcode_file_id = [puck_barcode_file_id]

            if len(puck_barcode_file_id) != len(set(puck_barcode_file_id)):
                raise SpacemakeError(
                    "Duplicate ids provided for "
                    + "--puck_barcode_file_id. \n"
                    + f"ids provided: {puck_barcode_file_id}"
                )

        # if puck barcode files and id's provided
        if puck_barcode_file_id is not None and puck_barcode_file is not None:
            # checklist
            # check if the lengths are the same
            if len(puck_barcode_file_id) != len(puck_barcode_file):
                raise SpacemakeError(
                    "Unmatching number of arguments provided"
                    + " for --puck_barcode_file and --puck_barcode_file_id.\n"
                    + "The provided number of elements should be the same"
                )

            kwargs["puck_barcode_file_id"] = puck_barcode_file_id
            kwargs["puck_barcode_file"] = puck_barcode_file
        elif puck_barcode_file_id is None and puck_barcode_file is not None:
            # if the user only provided puck_barcode_files
            self.logger.info(
                "No --puck_barcode_file_id provided. Generating" + " ids from filename"
            )

            puck_barcode_file_id = [
                os.path.basename(path).split(".")[0] for path in puck_barcode_file
            ]

            # if duplicates detected here: different files but same basename
            # this can happen if the file extensions are different
            if len(puck_barcode_file_id) != len(set(puck_barcode_file_id)):
                for i in range(len(puck_barcode_file_id)):
                    puck_barcode_file_id[i] = f"{puck_barcode_file_id[i]}_{i}"

            kwargs["puck_barcode_file_id"] = puck_barcode_file_id
            kwargs["puck_barcode_file"] = puck_barcode_file

        else:
            # if no puck barcode files are provided, we check if the puck has barcodes
            puck_name = kwargs.get("puck", None)

            if puck_name is not None:
                puck = self.config.get_puck(puck_name)

                if puck.has_barcodes:
                    kwargs["puck_barcode_file_id"] = [puck_name]
                    kwargs["puck_barcode_file"] = puck.variables["barcodes"]

        if sample_exists:
            new_project = self.df.loc[ix].copy()
            # pd.Series.update will only update values which are not None
            new_project.update(pd.Series(kwargs))
            self.df.loc[ix] = new_project
        else:
            new_project = pd.Series(self.project_df_default_values)
            new_project.name = ix
            new_project.update(kwargs)
            # before addition

            # after addition
            self.df = pd.concat([self.df, pd.DataFrame(new_project).T], axis=0)

        if return_series:
            return (ix, new_project)

    def delete_sample(self, project_id, sample_id):
        """delete_sample.

        :param project_id:
        :param sample_id:
        """
        ix = (project_id, sample_id)

        if self.sample_exists(*ix):
            element = self.df.loc[ix]

            self.logger.info(
                f"Deleting sample: {ix}, with the following"
                + f" with the following variables:\n{element}"
            )

            self.df.drop(ix, inplace=True)
            return element
        else:
            raise ProjectSampleNotFoundError(
                "(project_id, sample_id)", (project_id, sample_id)
            )

    def add_samples_from_yaml(self, projects_yaml_file):
        """add_samples_from_yaml.

        :param projects_yaml_file:
        """
        config = yaml.load(open(projects_yaml_file), Loader=yaml.FullLoader)
        demux_projects = config.get("projects", None)

        if demux_projects is not None:
            # if we have projects in the config file
            # get the samples
            for ip in demux_projects:
                self.add_sample_sheet(ip["sample_sheet"], ip["basecalls_dir"])

        # add additional samples from config.yaml, which have already been demultiplexed.
        for project in config["additional_projects"]:
            self.add_update_sample(**project)

    def get_ix_from_project_sample_list(self, project_id_list=[], sample_id_list=[]):
        """get_ix_from_project_sample_list.

        :param project_id_list:
        :param sample_id_list:
        """

        # raise error if both lists are empty
        if project_id_list == [] and sample_id_list == []:
            raise NoProjectSampleProvidedError()

        # of only one provided use that, if both use intersection
        if project_id_list == []:
            ix = self.df.query("sample_id in @sample_id_list").index
        elif sample_id_list == []:
            ix = self.df.query("project_id in @project_id_list").index
        else:
            ix = self.df.query(
                "project_id in @project_id_list and sample_id in @sample_id_list"
            ).index

        return ix

    def set_variable(self, ix, variable_name, variable_key, keep_old=False):
        """set_variable.

        :param ix:
        :param variable_name:
        :param variable_key:
        :param keep_old:
        """
        variable_name_pl = self.config.main_variables_sg2pl[variable_name]
        self.config.assert_main_variable(variable_name_pl)
        self.config.assert_variable(variable_name_pl, variable_key)

        # get current value
        i_variable = self.df.at[ix, variable_name]

        # if list, we either append or not
        if isinstance(i_variable, list):
            if keep_old:
                # keep the old list as well
                i_variable = list(set(i_variable + variable_key))
            else:
                i_variable = list(set(variable_key))

        # if we do not keep the old, simply set
        else:
            i_variable = variable_key

        if i_variable == [] or i_variable is None:
            raise EmptyConfigVariableError(variable_name)

        self.df.at[ix, variable_name] = i_variable

    def remove_variable(self, ix, variable_name, variable_key):
        """remove_variable.

        :param ix:
        :param variable_name:
        :param variable_key:
        """
        variable_name_pl = self.config.main_variables_sg2pl[variable_name]
        self.config.assert_main_variable(variable_name_pl)
        self.config.assert_variable(variable_name_pl, variable_key)

        if not isinstance(variable_key, list):
            raise ValueError("variable_key has to be a list")

        i_variable = self.df.at[ix, variable_name]

        i_variable = [val for val in i_variable if val not in variable_key]
        if i_variable == [] or i_variable is None:
            raise EmptyConfigVariableError(variable_name)

        self.df.at[ix, variable_name] = i_variable

    def set_remove_variable(
        self,
        variable_name,
        variable_key,
        action,
        project_id_list=[],
        sample_id_list=[],
        keep_old=False,
    ):
        """set_remove_variable.

        :param variable_name:
        :param variable_key:
        :param action:
        :param project_id_list:
        :param sample_id_list:
        :param keep_old:
        """
        self.assert_projects_samples_exist(project_id_list, sample_id_list)

        variable_name_pl = self.config.main_variables_sg2pl[variable_name]
        self.config.assert_main_variable(variable_name_pl)

        ix = self.get_ix_from_project_sample_list(
            project_id_list=project_id_list, sample_id_list=sample_id_list
        )

        if isinstance(variable_key, list):
            for var in variable_key:
                self.config.assert_variable(variable_name_pl, var)
        else:
            self.config.assert_variable(variable_name_pl, variable_key)

        for i, row in self.df.loc[ix, :].iterrows():
            # add/remove variable. if it already exists dont do anything
            if action == "set":
                self.set_variable(i, variable_name, variable_key, keep_old)
            elif action == "remove":
                self.remove_variable(i, variable_name, variable_key)

        return ix.to_list()

    def assert_projects_samples_exist(self, project_id_list=[], sample_id_list=[]):
        """assert_projects_samples_exist.

        :param project_id_list:
        :param sample_id_list:
        """
        for project in project_id_list:
            if project not in self.df.index.get_level_values("project_id"):
                raise ProjectSampleNotFoundError("project_id", project)

        for sample in sample_id_list:
            if sample not in self.df.index.get_level_values("sample_id"):
                raise ProjectSampleNotFoundError("sample_id", sample)

    def merge_samples(
        self,
        merged_project_id,
        merged_sample_id,
        project_id_list=[],
        sample_id_list=[],
        **kwargs,
    ):
        """merge_samples.

        :param merged_project_id:
        :param merged_sample_id:
        :param project_id_list:
        :param sample_id_list:
        :param kwargs:
        """
        # check if projects and samples with these IDs exist
        self.assert_projects_samples_exist(project_id_list, sample_id_list)

        ix = self.get_ix_from_project_sample_list(
            project_id_list=project_id_list, sample_id_list=sample_id_list
        )

        consistent_variables = list(self.config.main_variables_sg2pl.keys())
        consistent_variables.remove("run_mode")

        ix_list = ix.to_list()

        if ix_list == []:
            raise ProjectSampleNotFoundError(
                "(project_id_list, sample_id_list)", (project_id_list, sample_id_list)
            )

        # check for variable inconsistency
        # raise error if variable different between samples
        for variable in consistent_variables:
            if variable in kwargs and variable not in ["species", "barcode_flavor"]:
                # if variable provided from command line, skip
                self.logger.info(f"{variable} provided, skipping deduction...")
                continue

            self.logger.info(
                f"{variable} not provided. deducing from merged samples..."
            )

            variable_val = self.df.loc[ix, variable].to_list()

            if len(set(variable_val)) > 1:
                raise InconsistentVariablesDuringMerge(
                    variable_name=variable, variable_value=variable_val, ix=ix
                )
            else:
                # attach the deduced, consisten variable
                kwargs[variable] = variable_val[0]

        # get puck_barcode_files
        if "puck_barcode_file" not in kwargs or "puck_barcode_file_id" not in kwargs:
            kwargs["puck_barcode_file_id"] = []
            kwargs["puck_barcode_file"] = []

            for _, row in self.df.loc[ix].iterrows():
                if row["puck_barcode_file"] is None:
                    continue
                else:
                    for pbf_id, pbf in zip(
                        row["puck_barcode_file_id"], row["puck_barcode_file"]
                    ):
                        if (
                            pbf_id not in kwargs["puck_barcode_file_id"]
                            and pbf not in kwargs["puck_barcode_file"]
                        ):
                            kwargs["puck_barcode_file_id"].append(pbf_id)
                            kwargs["puck_barcode_file"].append(pbf)

        # after all checks, log that we are merging
        self.logger.info(f"Merging samples {ix_list} together\n")
        variables_to_deduce = ["investigator", "experiment", "sequencing_date"]

        for variable in variables_to_deduce:
            if variable not in kwargs:
                kwargs[variable] = ";".join(self.df.loc[ix, variable].unique())

        # if no run_mode provided, overwrite with user defined one
        if "run_mode" not in kwargs.keys():
            run_mode_lists = [
                set(run_mode) for run_mode in self.df.loc[ix].run_mode.to_list()
            ]

            # join run modes from parent samples
            if len(run_mode_lists) == 1:
                run_mode = run_mode_lists[0]
            else:
                run_mode = run_mode_lists[0].intersection(*run_mode_lists[1:])

            # create a list from the set intersection
            run_mode = list(run_mode)

            # if there are no common elements, throw an error
            if len(run_mode) == 0:
                raise InconsistentVariablesDuringMerge(
                    variable_name="run_mode", variable_value=run_mode_lists, ix=ix_list
                )

            # finally add run mode to arguments
            kwargs["run_mode"] = run_mode

        # set the action to add
        kwargs["action"] = "add"

        sample_added = self.add_update_sample(
            project_id=merged_project_id,
            sample_id=merged_sample_id,
            is_merged=True,
            merged_from=ix.to_list(),
            **kwargs,
        )

        return (sample_added, ix)
