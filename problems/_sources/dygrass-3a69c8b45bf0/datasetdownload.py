import gdown, tarfile, pathlib, sys

FILE_ID  = "1sJ90BvpqRC2whhiprDlYpcJaFbYLYTHt"   
ARCHIVE  = "dataset.tar.gz"
TARGET   = pathlib.Path(".")


gdown.download(id=FILE_ID, output=ARCHIVE, quiet=False)  

if not tarfile.is_tarfile(ARCHIVE):
    sys.exit("Download failed: not a valid .tar.gz (check sharing perms or file-ID)")

with tarfile.open(ARCHIVE, "r:gz") as tar:
    tar.extractall(TARGET)
print("✓ dataset ready")



FILE_ID  = "1reaLUDpi4nDDxGOlXGIKI-WK1ZjdV035"   
ARCHIVE  = "delet_edges.tar.gz"

gdown.download(id=FILE_ID, output=ARCHIVE, quiet=False)  

if not tarfile.is_tarfile(ARCHIVE):
    sys.exit("Download failed: not a valid .tar.gz (check sharing perms or file-ID)")

with tarfile.open(ARCHIVE, "r:gz") as tar:
    tar.extractall(TARGET)
print("✓ del_edge ready")