import os
import shutil
import sys

def fix_torch_dll():
    # Paths
    site_packages = sys.modules['site'].getsitepackages()[1]
    # In some envs getsitepackages returns [prefix, site-packages]
    if 'site-packages' not in site_packages:
        site_packages = sys.modules['site'].getsitepackages()[0]
        if 'site-packages' not in site_packages:
             # Fallback
             site_packages = os.path.join(sys.prefix, 'Lib', 'site-packages')

    print(f"Site packages: {site_packages}")
    
    # Source: intel-openmp dll
    # Usually in <prefix>/Library/bin/libiomp5md.dll
    prefix = sys.prefix
    src_dll = os.path.join(prefix, 'Library', 'bin', 'libiomp5md.dll')
    
    if not os.path.exists(src_dll):
        print(f"Source DLL not found at {src_dll}")
        # Try finding it in site-packages/intel_openmp/lib if it exists?
        # But we found it in Library/bin earlier.
        return

    # Destination 1: torch/lib
    torch_dir = os.path.join(site_packages, 'torch')
    if not os.path.exists(torch_dir):
        print(f"Torch dir not found at {torch_dir}")
        return

    torch_lib = os.path.join(torch_dir, 'lib')
    os.makedirs(torch_lib, exist_ok=True)
    
    dst1 = os.path.join(torch_lib, 'libiomp5md.dll')
    print(f"Copying to {dst1}")
    shutil.copy2(src_dll, dst1)
    
    # Destination 2: torch/bin (just in case)
    torch_bin = os.path.join(torch_dir, 'bin')
    os.makedirs(torch_bin, exist_ok=True)
    dst2 = os.path.join(torch_bin, 'libiomp5md.dll')
    print(f"Copying to {dst2}")
    shutil.copy2(src_dll, dst2)
    
    print("Fix complete.")

if __name__ == "__main__":
    fix_torch_dll()
