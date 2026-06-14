# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'Module_4 assignment - Flask app db backend with tests'
copyright = '2026, Chris Locricchio'
author = 'Chris Locricchio'
release = '1'

import os
import sys

# Resolve src relative to this file so imports work on Read the Docs and locally.
SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = ['sphinx.ext.autodoc']

# Avoid requiring a live PostgreSQL driver during autodoc on Read the Docs.
autodoc_mock_imports = ['psycopg']

# Document modules in the order they appear in the source files.
autodoc_member_order = 'bysource'

templates_path = ['_templates']
exclude_patterns = []

language = 'en'

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_rtd_theme'


def setup(app):
    """Fail fast if Sphinx cannot locate the Python source tree."""
    if not os.path.isdir(SRC_DIR):
        raise RuntimeError(f"Sphinx source path does not exist: {SRC_DIR}")
