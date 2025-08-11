# holis_tools

## This repository offers tools to deal with access to holis_data

#### Installing:

```bash
# Clone the repo
cd /dir/of/choice
git clone https://github.com/CBI-PITT/holis_tools.git

# Create a virtual environment
# This assumes that you have miniconda or anaconda installed
conda create -n holis_tools python=3.12 -y

# Activate environment and install zarr_stores
conda activate holis_tools
pip install -e /dir/of/choice/holis_tools
```



##### <u>spool_reader:</u>

###### Description:

This tool enables a .zip file containing a collection of spools files that represents 1 yz strip to be read and formatted as numpy array(s) for downstream processing. Currently the package assumes that the zip file is formatted according to the compression_tools library found here: https://github.com/CBI-PITT/compression_tools/tree/main/compression_tools

###### Usage example:

```python
from compression_tools.alt_zip import alt_zip
from holis_tool.spool_reader import spool_set_interpreter
import numpy as np

# Location of zip file contatining spool files
test_spool_zip = r'/zip/file/writted/using/compression_tools/containing/spool/files.zip'

# Instantiate class to manage spool files
a = spool_set_interpreter(test_spool_zip)

# Extract the 100th spool file only
hundredth_spool_file = a[100]

# assemble all spool files into a complete acquisition strip
b = a.assemble()
```

