from pathlib import Path

import lionscliapp as app

from . import ui
from .constants import PROJECT_DIR


def cmd_gui():
    ui.run(app.ctx["execpath.root"])


def main():
    app.declare_app("aspect-slicer", "0.1.0")
    app.describe_app("Exact-aspect image slicer for print workflows.")
    app.declare_projectdir(PROJECT_DIR)
    app.declare_key("execpath.root", str(Path.cwd()))
    app.describe_key("execpath.root", "Folder where .aspect-slicer data is stored.")
    app.declare_cmd("", cmd_gui)
    app.describe_cmd("", "Open the Aspect Slicer graphical application.")
    app.declare_cmd("gui", cmd_gui)
    app.describe_cmd("gui", "Open the Aspect Slicer graphical application.")
    app.main()


if __name__ == "__main__":
    main()

