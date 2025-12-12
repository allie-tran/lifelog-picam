import subprocess
import sys

def header(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)

def run_cmd(cmd):
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True, text=True)
        print(out.strip())
    except Exception as e:
        print("FAILED:", e)

def check_nvidia_smi():
    header("Checking: NVIDIA Driver (nvidia-smi)")
    run_cmd("nvidia-smi")

def check_pytorch():
    header("Checking: PyTorch")
    try:
        import torch
        print("PyTorch version:", torch.__version__)
        print("CUDA available:", torch.cuda.is_available())
        print("CUDA version reported by PyTorch:", torch.version.cuda)
        if torch.cuda.is_available():
            print("GPU name:", torch.cuda.get_device_name(0))
    except Exception as e:
        print("FAILED to import PyTorch:", e)

def check_tensorflow():
    header("Checking: TensorFlow")
    try:
        import tensorflow as tf
        print("TensorFlow version:", tf.__version__)
        print("Is built with CUDA:", tf.test.is_built_with_cuda())
        print("Physical GPUs visible:", tf.config.list_physical_devices('GPU'))
    except Exception as e:
        print("FAILED to import TensorFlow:", e)

def summary():
    header("SUMMARY (quick read)")
    print("• If PyTorch CUDA is True → GPU OK")
    print("• If TensorFlow GPU list is empty → expected (CUDA 12.x unsupported)")
    print("• Any undefined symbol errors → wrong Python/ABI mix")

if __name__ == "__main__":
    check_nvidia_smi()
    check_pytorch()
    check_tensorflow()
    summary()
