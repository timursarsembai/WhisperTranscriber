import os
import subprocess
import sys
import customtkinter
import faster_whisper

def get_nvidia_dll_paths():
    """Try to find nvidia DLL paths in site-packages."""
    import nvidia.cublas
    import nvidia.cudnn
    
    cublas_bin = os.path.join(nvidia.cublas.__path__[0], 'bin')
    cudnn_bin = os.path.join(nvidia.cudnn.__path__[0], 'bin')
    
    return cublas_bin, cudnn_bin

def build():
    # Путь к customtkinter для включения его json/theme файлов
    ctk_path = os.path.dirname(customtkinter.__file__)
    
    # Путь к faster_whisper для включения assets (VAD модель)
    fw_path = os.path.dirname(faster_whisper.__file__)
    fw_assets = os.path.join(fw_path, "assets")
    
    # DLL paths
    try:
        cublas_bin, cudnn_bin = get_nvidia_dll_paths()
    except ImportError:
        print("Error: could not find nvidia packages. Make sure they are installed.")
        return

    # Form PyInstaller command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--name=WhisperTranscriber", # Better name for EXE
        "--splash=splash.png", # Added splash screen
        # Add customtkinter data
        f"--add-data={ctk_path}{os.pathsep}customtkinter",
        # Add faster_whisper assets (silero_vad.onnx etc.)
        f"--add-data={fw_assets}{os.pathsep}faster_whisper/assets",
        # Add DLLs
        f"--add-binary={cublas_bin}/*.dll{os.pathsep}nvidia/cublas/bin",
        f"--add-binary={cudnn_bin}/*.dll{os.pathsep}nvidia/cudnn/bin",
        # Main file
        "main.py"
    ]

    print(f"Starting build with command: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

if __name__ == "__main__":
    build()
