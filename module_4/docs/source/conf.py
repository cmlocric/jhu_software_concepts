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

sys.path.insert(0, os.path.abspath(r"C:\Users\hz98yb\Training_Files\jhu_software_concepts\module_4\src"))

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = ['sphinx.ext.autodoc']

templates_path = ['_templates']
exclude_patterns = []

language = "'en'"

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_rtd_theme'
html_static_path = [r"C:\Users\hz98yb\Training_Files\jhu_software_concepts\module_4\docs\build\html\_static"]
