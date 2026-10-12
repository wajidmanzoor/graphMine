project   = "TopoGPU"
author    = "Fan Wang, Hubert Wagner, Rezaul Chowdhury, Chao Chen"
copyright = "2026, Fan Wang"
release   = "2.0.0"

extensions = ["myst_parser"]          # lets you write pages in Markdown
source_suffix = {".rst": "restructuredtext", ".md": "markdown"}
html_theme = "sphinx_rtd_theme"
html_title = "TopoGPU documentation"
html_theme_options = {"navigation_depth": 3, "collapse_navigation": False}
myst_enable_extensions = ["colon_fence", "deflist"]