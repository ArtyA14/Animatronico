#!/usr/bin/env python3
"""GUI interface for Springtrap with device selection - centered window."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import sys
import os

import sounddevice as sd


def list_audio_devices():
    """Get list of audio devices with input/output info."""
    devices = []
    for i, dev in enumerate(sd.query_devices()):
        devices.append(
            {
                "index": i,
                "name": dev["name"],
                "host_api": sd.query_hostapis(dev["hostapi"])["name"]
                .replace("Windows ", ""),
                "inputs": dev["max_input_channels"],
                "outputs": dev["max_output_channels"],
                "samplerate": int(dev["default_samplerate"]),
            }
        )
    return devices


def find_device_index(devices, target_name):
    """Find device index by name (case-insensitive)."""
    for dev in devices:
        if target_name.lower() in dev["name"].lower():
            return dev["index"]
    return None


def launch_springtrap(mic_index, output_index):
    """Launch main.py with selected device indices."""
    env = os.environ.copy()
    if mic_index is not None:
        env["SPRINGTRAP_MIC"] = str(mic_index)
    if output_index is not None:
        env["SPRINGTRAP_OUTPUT"] = str(output_index)

    # Launch main.py in a new process
    python_exe = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "Scripts", "python.exe")
    main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")

    try:
        subprocess.Popen(
            [python_exe, main_py] + sys.argv[1:],
            env=env,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        root.destroy()
    except Exception as e:
        messagebox.showerror("Error", f"No se pudo lanzar Springtrap:\n{e}")


def on_launch():
    """Handle launch button click."""
    mic_name = mic_var.get()
    output_name = output_var.get()

    mic_index = find_device_index(devices, mic_name) if mic_name else None
    output_index = find_device_index(devices, output_name) if output_name else None

    if mic_index is None and mic_name:
        messagebox.showwarning(
            "Advertencia", f"No se encontró el dispositivo de entrada: '{mic_name}'"
        )
    elif output_index is None and output_name:
        messagebox.showwarning(
            "Advertencia", f"No se encontró el dispositivo de salida: '{output_name}'"
        )
    else:
        launch_springtrap(mic_index, output_index)


# ---- Main GUI Setup ----
root = tk.Tk()
root.title("Springtrap - Configuración de Audio")
root.resizable(False, False)

# Center the window on screen
root.update_idletasks()
width = 500
height = 300
x = (root.winfo_screenwidth() // 2) - (width // 2)
y = (root.winfo_screenheight() // 2) - (height // 2)
root.geometry(f'{width}x{height}+{x}+{y}')

# Device selection frame
frame_devices = tk.LabelFrame(root, text="Dispositivos de Audio", padx=10, pady=10)
frame_devices.pack(fill="both", expand=True, padx=10, pady=10)

# Left frame: Input devices
frame_input = tk.LabelFrame(frame_devices, text="Micrófono de Entrada", padx=5, pady=5)
frame_input.pack(side="left", fill="both", expand=True, padx=5)

# Right frame: Output devices
frame_output = tk.LabelFrame(frame_devices, text="Altavoz de Salida", padx=5, pady=5)
frame_output.pack(side="right", fill="both", expand=True, padx=5)

# Get devices
devices = list_audio_devices()

# Build input device dropdown
mic_names = [dev["name"] for dev in devices]
mic_var = tk.StringVar(value=mic_names[0] if mic_names else "")

mic_label = tk.Label(frame_input, text="Selecciona el micrófono:")
mic_label.pack(anchor="w")

mic_dropdown = ttk.Combobox(frame_input, textvariable=mic_var, values=mic_names, state="readonly")
mic_dropdown.pack(fill="x", pady=5)

# Build output device dropdown
output_names = [dev["name"] for dev in devices]
output_var = tk.StringVar(value=output_names[0] if output_names else "")

output_label = tk.Label(frame_output, text="Selecciona el altavoz:")
output_label.pack(anchor="w")

output_dropdown = ttk.Combobox(frame_output, textvariable=output_var, values=output_names, state="readonly")
output_dropdown.pack(fill="x", pady=5)

# Launch button
launch_btn = tk.Button(
    root,
    text="🚀 Iniciar Springtrap",
    font=("Arial", 12, "bold"),
    bg="#4CAF50",
    fg="white",
    command=on_launch,
    width=20,
    pady=5,
)
launch_btn.pack(pady=10)

# Handle window close
def on_closing():
    root.destroy()
    sys.exit(0)

root.protocol("WM_DELETE_WINDOW", on_closing)
root.mainloop()
