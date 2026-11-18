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
1. Download the latest `HillClimbRacingTrainerV2.exe` from [**Releases**](https://github.com/Gunaseelan2008/Hill-Climb-Racing-HackPanel/releases/latest).
2. Start **Hill Climb Racing** on your PC.
3. Run `HillClimbRacingTrainerV2.exe` (Run as Administrator).
4. Enter your desired values for Coins, Diamonds, Fuel, or Boost and click **Set**.
5. Enjoy the game!

---

## 🛠️ Running from Source Code (Developers)
If you prefer to run directly using Python:

1. Clone the repository:
   ```bash
   git clone https://github.com/Gunaseelan2008/Hill-Climb-Racing-HackPanel.git
   cd Hill-Climb-Racing-HackPanel
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the trainer:
   ```bash
   python hill_climb_racing_trainer_V2.py
   ```

---

## 🛡️ Note on Antivirus "False Positives"
Some antivirus engines (like on VirusTotal) may flag game trainers or PyInstaller executables as suspicious because they use Windows memory injection APIs (`ReadProcessMemory` / `WriteProcessMemory`) to modify game values.
Assure that this project is 100% open-source, safe, and contains no malware. You can inspect all source code directly in this repository.

---

## 📜 License
Distributed for educational and personal use. All game copyrights belong to Fingersoft.
