from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from rkd_mvp import MVPApp


app = MVPApp()
context = app.context()
app.bootstrap(context)
print(app.run_happy_path(context))

