# 韌體：建置、燒錄、確認

- 板子：**NUCLEO-H753ZI**（STM32H753ZI，Cortex-M7 480 MHz），ST-LINK 的虛擬 COM port 接 PC（921600 baud）。
- `stm32h753/`：板子的專案（STM32CubeMX 產生的時脈、UART、HAL 設定＋CMake）。`CMakeLists.txt` 會編 `emg/*.c`；`emg/` 不在 repo 裡，由建置腳本從 `src/c/` 放進去。
  - `Drivers/` 是 ST 的 HAL 和 Arm 的 CMSIS（授權檔在各自的資料夾裡）。
  - 要改時脈或周邊：用 STM32CubeMX 開 `blink.ioc`。
- EMG 的程式都在 `src/c/`，PC 上用 `src/check_*.py` 和同一份程式逐位元比對。

## 需要的工具（Windows）

STM32CubeCLT，或 VS Code 的 STM32 擴充套件會裝在 `%LOCALAPPDATA%\stm32cube\bundles\`：
- `gnu-tools-for-stm32`（作者用 14.3.1）、`cmake`、`ninja`：建置；
- `programmer`（STM32_Programmer_CLI 2.23.0）：燒錄、讀回。

## 建置

在 Git Bash：

```bash
bash firmware/build_fw.sh src/c out_fw          # 目前的 src/c
```

輸出 `blink.elf`、`blink.map`、`blink.bin`（flash 映像）和 md5。工具不在預設位置時，設 `STM32_BUNDLES`。

### 重建板子上的凍結版本 `rtl_task_s7f`

```bash
git worktree add ../s7f rtl_task_s7f
bash firmware/build_fw.sh ../s7f/src/c out_s7f
```

應該得到 26,056 bytes、md5 `4d60a4f38b54c83d341f5f33c355bd9e`。2026-11-25 用這個腳本重建，和板子上讀回的內容**逐位元相同**。

注意：目前的 `src/c` 比 s7f 多了 35.95 的「提早換指令」程式碼（預設關閉），所以直接編 `src/c` 得到的映像和 s7f 不同。

## 燒錄

PowerShell（`$cli` 是 STM32_Programmer_CLI.exe 的路徑）：

```powershell
& $cli -c port=SWD mode=UR reset=HWrst -w out_fw\blink.elf -v -hardRst
```

**燒錄前先備份**板子上的程式（可以回復）：

```powershell
& $cli -c port=SWD mode=UR -u 0x08000000 0x100000 backup_bank1.bin
```

完整的流程（備份、確認舊版本、燒錄、讀回比對）見 `src/pc/s7_test/flash_s7b.ps1`（裡面的路徑要改成自己的）。

## 確認板子上是哪個版本

讀回 flash 開頭、和映像比 md5（不會改到板子）：

```powershell
& $cli -c port=SWD mode=UR -u 0x08000000 26056 board.bin
(Get-FileHash board.bin -Algorithm MD5).Hash
```

## 版本紀錄

| 版本 | git | 內容 |
|---|---|---|
| `rtl_task_s7f` | tag `rtl_task_s7f`（37ac42a） | S7：類別遮罩、閘門 0.5 模式 2、k 5、停止 k 2、停止事件、範圍標籤、掉封包時送停止（35.77–35.85） |

更早的版本（隨機森林 v2、`pilot-freeze-4／5`、9 類）見 report 第 18–28 節和 35.80。
