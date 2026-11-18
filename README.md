# Hill Climb Racing HackPanel 🎮🚗

A modern, high-performance Trainer / Hack Panel for **Hill Climb Racing** (PC Edition - `HillClimbRacing.exe`).

[![Download Standalone EXE](https://img.shields.io/badge/Download-Standalone%20EXE%20(v2.0)-brightgreen?style=for-the-badge&logo=windows)](https://github.com/Gunaseelan2008/Hill-Climb-Racing-HackPanel/releases/latest)

---

## ✨ Features
- 💰 **Unlimited Coins & Diamonds**: Edit coin and diamond values with real-time in-game synchronization.
- ⛽ **Infinite Fuel**: Automatically freezes fuel values in real-time with background thread protection.
- 🚀 **Boost Modification**: Multi-level pointer resolution for boost customization.
- ⌨️ **Global In-Game Hotkeys**: Toggle mods on-the-fly while racing without switching windows.
- 🎨 **Modern Dark UI**: Sleek glassmorphism-styled interface with native Windows 11/10 dark titlebar support.
- ⚡ **Standalone Executable**: No Python or external installation required for end-users!

---

## 🚀 How to Use (Pre-built Executable)
1. Download the latest `HillClimbRacingTrainerV2.exe` from [**GitHub Releases**](https://github.com/Gunaseelan2008/Hill-Climb-Racing-HackPanel/releases/latest) or via [**Direct Download (v2.0)**](https://github.com/Gunaseelan2008/Hill-Climb-Racing-HackPanel/releases/download/v2.0/HillClimbRacingTrainerV2.exe).
2. Start **Hill Climb Racing** on your PC.
3. Run `HillClimbRacingTrainerV2.exe` (Run as Administrator).
4. Enter your desired values for Coins, Diamonds, Fuel, or Boost and click **Set**.
5. Enjoy the game!

> **Binary Verification (v2.0)**:  
> **File**: `HillClimbRacingTrainerV2.exe` (20.7 MB)  
> **SHA-256**: `a2775e4737b2d18b2e9b99423b137bc8d847413d9b4f8def8e27e0eacdcdbd4b`

---

## 🛠️ Running from Source Code (Developers)
If you prefer not to run precompiled binaries, you can run directly using Python:

1. Clone the repository:
   ```bash
   git clone https://github.com/Gunaseelan2008/Hill-Climb-Racing-HackPanel.git
   cd Hill-Climb-Racing-HackPanel
   ```
2. Install pinned dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the trainer:
   ```bash
   python hill_climb_racing_trainer_V2.py
   ```

---

## 🛡️ Antivirus Notice & Disclaimer
Some antivirus engines (such as scans on VirusTotal) may flag game trainers or PyInstaller executables as suspicious due to heuristic detection or the use of Windows memory APIs (`OpenProcess`, `ReadProcessMemory`, `WriteProcessMemory`) required to modify game values.

While the complete Python source code is provided in this repository for full transparency and code audit, users should exercise their own judgment when running third-party executables. If you prefer not to run precompiled binaries, you are encouraged to review the source code and run the trainer directly from Python using the instructions above.

---

## 📜 License
Distributed for educational and personal use. All game copyrights belong to Fingersoft.
