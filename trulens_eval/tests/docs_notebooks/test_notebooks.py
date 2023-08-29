import os
from os import listdir
import shutil
from typing import Sequence
from unittest import main
from unittest import TestCase

from nbconvert.preprocessors import ExecutePreprocessor
from nbformat import read

from trulens_eval import db_migration


class DocsNotebookTests(TestCase):
    pass


class VariableSettingPreprocessor(ExecutePreprocessor):

    def __init__(
        self, timeout: int, kernel_name: str,
        code_to_run_before_each_cell: Sequence[str]
    ):
        super().__init__(timeout=timeout, kernel_name=kernel_name)
        self.code_to_run_before_each_cell = "\n".join(
            code_to_run_before_each_cell
        ) + "\n"

    def preprocess_cell(self, cell, resources, index, **kwargs):
        if cell["cell_type"] == "code":
            cell["source"] = self.code_to_run_before_each_cell + cell["source"]
        ret = super().preprocess_cell(cell, resources, index, **kwargs)
        return ret


class DBMigrationPreprocessor(VariableSettingPreprocessor):

    def __init__(
        self, timeout: int, kernel_name: str,
        code_to_run_before_each_cell: Sequence[str], db_compat_version: str
    ):
        super().__init__(
            timeout=timeout,
            kernel_name=kernel_name,
            code_to_run_before_each_cell=code_to_run_before_each_cell
        )
        shutil.copyfile(
            f"./release_dbs/{db_compat_version}/default.sqlite",
            "./default.sqlite"
        )

    def preprocess_cell(self, cell, resources, index, **kwargs):
        if 'Tru()' in cell["source"]:
            cell["source"] = cell[
                "source"
            ] + f"\nfrom trulens_eval import Tru\nTru().migrate_database()\n"
        ret = super().preprocess_cell(cell, resources, index, **kwargs)

        return ret


def get_unit_test_for_filename(filename, db_compat_version=None):

    def test(self):
        OPENAI_API_KEY = os.environ['OPENAI_API_KEY']
        HUGGINGFACE_API_KEY = os.environ['HUGGINGFACE_API_KEY']
        PINECONE_API_KEY = os.environ['PINECONE_API_KEY']
        PINECONE_ENV = os.environ['PINECONE_ENV']
        HUGGINGFACEHUB_API_TOKEN = os.environ['HUGGINGFACEHUB_API_TOKEN']

        notebook_preprocessor = VariableSettingPreprocessor
        notebook_preprocessor_kwargs = {
            'timeout':
                600,
            'kernel_name':
                'trulens-llm',
            'code_to_run_before_each_cell':
                [
                    f"import os",
                    f"os.environ['OPENAI_API_KEY']='{OPENAI_API_KEY}'",
                    f"os.environ['HUGGINGFACE_API_KEY']='{HUGGINGFACE_API_KEY}'",
                    f"os.environ['PINECONE_API_KEY']='{PINECONE_API_KEY}'",
                    f"os.environ['PINECONE_ENV']='{PINECONE_ENV}'",
                    f"os.environ['HUGGINGFACEHUB_API_TOKEN']='{HUGGINGFACEHUB_API_TOKEN}'",
                ]
        }
        if db_compat_version is not None:
            notebook_preprocessor = DBMigrationPreprocessor
            notebook_preprocessor_kwargs['db_compat_version'
                                        ] = db_compat_version
        with open(f'./tests/docs_notebooks/notebooks_to_test/{filename}') as f:
            nb = read(f, as_version=4)
            notebook_preprocessor(**notebook_preprocessor_kwargs
                                 ).preprocess(nb, {})

    return test


for filename in listdir('./tests/docs_notebooks/notebooks_to_test/'):
    if filename.endswith('.ipynb'):

        if 'all_tools' in filename or 'llama_index_quickstart' in filename:
            setattr(
                DocsNotebookTests, 'test_' + filename.split('.ipynb')[0],
                get_unit_test_for_filename(filename)
            )
            # If you want to test all versions uncomment and replace the below for loop
            ### for version in db_migration.migration_versions:

            # Run the oldest and latest migrations to keep testing more manageable
            legacy_sqllite_migrations = [db_migration.migration_versions[0],
                            db_migration.migration_versions[-1]]
            sqlalchemy_versions  = [compat_versions.split('sql_alchemy_') for compat_versions in listdir('./release_dbs') if 'sql_alchemy_' in compat_versions]
            sqlalchemy_migrations = [sqlalchemy_versions[0], #sqlalchemy_versions[1], # to add once there are multiple migrations to test
                                     sqlalchemy_versions[-1]]
            migrations_to_test = legacy_sqllite_migrations.extend(sqlalchemy_migrations)
            for version in migrations_to_test:
                test_version_str = version.replace('.', '_')
                setattr(
                    DocsNotebookTests,
                    f"test_db_backwards_compat_{test_version_str}_{filename.split('.ipynb')[0]}",
                    get_unit_test_for_filename(
                        filename, db_compat_version=version
                    )
                )

if __name__ == '__main__':
    main()
