############################
import sys
print("Python executable:", sys.executable)
print("Current working directory:", sys.path[0])
print("\nsys.path entries:")
for i, p in enumerate(sys.path):
    print(f"  {i}: {p}")
    
# Check if generic directory exists
import os
home_repo = "/opt/lampp/htdocs/test/"  # Replace with actual path
generic_path = os.path.join(home_repo, "generic")
print(f"\nDoes {generic_path} exist? {os.path.exists(generic_path)}")
if os.path.exists(generic_path):
    print(f"Contents: {os.listdir(generic_path)}")


################################

## 1. Wrong path appended Make sure you're appending home_repo (the parent folder), not a subfolder:
# ✓ Correct
import sys
sys.path.append("/absolute/path/to/home_repo")

# ✗ Wrong
sys.path.append("/absolute/path/to/home_repo/projects")

## 2. Running from different directory If you run python projects/somescript.py from outside home_repo, the working directory affects relative paths. Use absolute paths:
import os
script_dir = os.path.dirname(os.path.abspath(__file__))
home_repo = os.path.dirname(script_dir)  # Assuming script is in projects/
sys.path.insert(0, home_repo)

## 3. Naming conflict Check you don't have generic.py or generic/__init__.pyc anywhere else in the path that shadows your module. Look at the beginning of your sys.path list above.

## 4. Import before path setup Ensure sys.path.append() executes before the import statement. Move it to the top of your script or use a bootstrap file.
#Better Solutions (Long-term)

'''# Option A: Use a dedicated bootstrap module'''
# setup.py or bootstrap.py
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HOME_REPO = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, HOME_REPO)

#Then run: python -c "import setup; exec(open('projects/script.py').read())" or adjust your entry point.

'''# Option B: Proper package structure Consider making home_repo itself a proper package:'''
#home_repo/
#├── __init__.py
#├── generic/
#│   └── __init__.py
#│   └── filemanagement.py
#├── projects/
#│   └── your_script.py
#└── data/

#Then install in development mode: pip install -e /path/to/home_repo

'''# Option C: Environment variable Set PYTHONPATH externally:'''
#export PYTHONPATH="/absolute/path/to/home_repo:$PYTHONPATH"
#python projects/somescript.py
