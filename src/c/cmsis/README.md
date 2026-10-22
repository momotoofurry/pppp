# CMSIS 標頭檔（第三方，Apache-2.0）

2026-10-23 下載，使用者在指令中同意從這兩個官方 GitHub repo 下載。只用於 `board_h7.c`（硬體層）的編譯。

| 來源 | 版本 |
|---|---|
| STMicroelectronics/cmsis_device_h7（GitHub 已改名為 `cmsis-device-h7`，自動轉址，repository id 228873983） | tag `v1.10.7`，commit `8f922cdc7cc6de2344e75ddd657889f4ff761790` |
| ARM-software/CMSIS_5 | tag `5.9.0`，commit `2b7495b8535bdcb306dac29b9ded4cfb679d7e5c` |

| 檔案 | 下載網址 | 大小（bytes） | SHA-256 |
|---|---|---|---|
| `st/stm32h753xx.h` | https://raw.githubusercontent.com/STMicroelectronics/cmsis-device-h7/v1.10.7/Include/stm32h753xx.h | 2,118,971 | `4f6def439a9fa94705303fe227d34308048c44bd36263d311aa54cc94f8398f5` |
| `st/stm32h7xx.h` | https://raw.githubusercontent.com/STMicroelectronics/cmsis-device-h7/v1.10.7/Include/stm32h7xx.h | 11,834 | `99ac7d4598e20d9bd74e0e001f0e63c2a8eb0a3584242d9e442be31ceb616cb9` |
| `st/system_stm32h7xx.h` | https://raw.githubusercontent.com/STMicroelectronics/cmsis-device-h7/v1.10.7/Include/system_stm32h7xx.h | 2,422 | `e0f13c2971d34bda571aed454880b3608093cd9a5f7420a763e8c2bda34e826a` |
| `st/system_stm32h7xx.c` | https://raw.githubusercontent.com/STMicroelectronics/cmsis-device-h7/v1.10.7/Source/Templates/system_stm32h7xx.c | 19,751 | `95a8fc5a6d765a78a8b6f0dd1fedc48994096df544e611e951c6c2e4426570e6` |
| `st/LICENSE.md` | https://raw.githubusercontent.com/STMicroelectronics/cmsis-device-h7/v1.10.7/LICENSE.md | 11,348 | `49d37f1f2e5c1f9fc9da194b44ffbfa41f966b7cf446fbab4d1e2b0c1e3d20df` |
| `arm/core_cm7.h` | https://raw.githubusercontent.com/ARM-software/CMSIS_5/5.9.0/CMSIS/Core/Include/core_cm7.h | 138,948 | `e974d0a91752487d0154457cd422c37667328e9ddb7ba4fa2fed479a63577f63` |
| `arm/cmsis_compiler.h` | https://raw.githubusercontent.com/ARM-software/CMSIS_5/5.9.0/CMSIS/Core/Include/cmsis_compiler.h | 9,481 | `b51963d271c1571ca3463654c76aa7ea50c4eac5d0a2710df10414ac64d9e0f8` |
| `arm/cmsis_gcc.h` | https://raw.githubusercontent.com/ARM-software/CMSIS_5/5.9.0/CMSIS/Core/Include/cmsis_gcc.h | 63,374 | `43bfd1fe69fbbc2ca70aaf7d43cc3e20f16e0c7f66e1bdef9b51af6dc14b2617` |
| `arm/cmsis_version.h` | https://raw.githubusercontent.com/ARM-software/CMSIS_5/5.9.0/CMSIS/Core/Include/cmsis_version.h | 1,680 | `184c19fd3ee73632edf35a0b4d49cd48be75fbf49e6ccb19d9db05fa83bea4b3` |
| `arm/mpu_armv7.h` | https://raw.githubusercontent.com/ARM-software/CMSIS_5/5.9.0/CMSIS/Core/Include/mpu_armv7.h | 11,731 | `29206b52ee02290ed6f5a5415ebd4187de802cf176d9b3cb844390d8e5571372` |
| `arm/cachel1_armv7.h` | https://raw.githubusercontent.com/ARM-software/CMSIS_5/5.9.0/CMSIS/Core/Include/cachel1_armv7.h | 12,087 | `2e336a64f60a9c0eaf5a08e2c4845d94da86c3fd84d219d0d0c9f530e63bc9c3` |
| `arm/LICENSE.txt` | https://raw.githubusercontent.com/ARM-software/CMSIS_5/5.9.0/LICENSE.txt | 11,357 | `b40930bbcf80744c86c46a12bc9da056641d722716c378f5659b9e555ef833e1` |

`system_stm32h7xx.c` 只留作參考，沒有編譯（時脈在 `board_h7.c` 的 `board_init()` 設定）。授權見 `st/LICENSE.md`、`arm/LICENSE.txt`。
