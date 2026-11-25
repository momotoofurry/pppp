# Kinova Gen3 實機閉迴路：操作程序與第一次上機檢查表（草稿，2026-11-25）

> 依據：report 35.82–35.92。標【待確認】的項目，要在實驗室對照實機、Kinova 手冊或老師的規定確認後才能照做。
> 範圍：**受試者只有你自己**；其他人參與要先有 IRB 和老師同意。VLA／LLM 不進入這個流程。

## 0. 原則

1. **急停一直在手邊**：實機的急停按鈕（或 Kinova 手把）放在伸手就能按的位置。
   - 【待確認】你一個人當受試者兼操作者時，是否需要第二個人在場、負責按急停。建議要，請和老師確認實驗室規定。
2. **由慢到快、由空到滿**：每一步都通過了，才做下一步。任何一步失敗就停下，回到前一步。
3. **控制電腦先過時間檢查**（第 1 節）。
   - 35.92 在 WSL2 看到每 30 s 約 0.7 s 的中斷，最長 3.4 s。
   - 35.93 查證：
     - 原因沒有完全確定：可能是系統時鐘被校時跳動，也可能是虛擬機真的暫停；
     - 筆電待機喚醒之後就沒有再出現；
     - `assist_ros.py` 已改用 monotonic 時鐘，時鐘跳動不會再誤觸 deadman。
   - Kortex 驅動用的是系統時鐘，所以有原生 Linux 比較保險。
   - **決定（2026-11-25）：用 WSL**，一台筆電做完（見第 1.5 節）。代價是每次上機前都要過 1.1，實驗中出現不明的 deadman 停止就回到 1.1。原生 Linux 的做法留在第 1.6 節備用。

## 1. 上機前（不開手臂電源，在自己電腦就能做）

| # | 檢查 | 指令 | 通過條件 | ☐ |
|---|---|---|---|---|
| 1.1 | 控制電腦的時間穩定性（在 WSL 裡跑） | 先照 1.5 設好電源、`wsl --shutdown` 重開，再 `python3 src/pc/s7_test/loop_jitter.py 300` | **PASS**：300 s 內行程沒有停住超過 0.1 s，系統時鐘也沒有跳動超過 0.05 s。之前的中斷約每 30 s 一次，所以測 300 s 而不是 90 s | ☐ |
| 1.2 | 程式測試 | `modes_test`、`modes_assist_test`、`labeler_test`、`lockrule_test`、`rebase_test` | 都是 ALL OK | ☐ |
| 1.3 | 實機 launch 的假硬體測試 | `bash src/pc/s7_test/kortex_mock.sh /tmp/kortex_mock` | 介面都在；起始移動走短路；關掉控制器時出現「holding」；任務完成 | ☐ |
| 1.4 | Gazebo 預演 | `bash src/pc/s7_test/gz_lock.sh intent /tmp/gz` | 放到目標架子，追蹤誤差最大 < 1 cm | ☐ |

### 1.5 用 WSL 的架構（採用，2026-11-25）

- **一台筆電**：
  - **Windows**：TCU、TrignoBridge、TaskScreen、ExperimentPanel、板子（USB）、`udp_tcp_relay.py --udp 50556`（預設送到本機 50560）。
  - **WSL（Ubuntu-22.04＋ROS 2 Humble）**：Kortex 驅動、`assist_ros.py board`。這就是 Gazebo 預演和假硬體測試用的同一套環境。
- **網路**：筆電用網路線接手臂；不要用 Wi-Fi 控制手臂。
  - 【待確認】WSL 裡能不能連到手臂。驅動在 WSL 裡，要經過 Windows 的網路卡。第 2.1 步要在 **WSL 裡** `ping <手臂 IP>`，不是在 Windows。
  - 連不到的話，在 `C:\Users\kirit\.wslconfig` 的 `[wsl2]` 下加 `networkingMode=mirrored`，`wsl --shutdown` 後再試。
- **Windows 電源設定**（上機前一次）：
  - 插電；
  - 螢幕和睡眠都設成「永不」（插電時）。你懷疑之前的中斷和螢幕關閉有關，這個還沒驗證，所以直接避開：
    ```powershell
    powercfg /change monitor-timeout-ac 0
    ```
    ```powershell
    powercfg /change standby-timeout-ac 0
    ```
  - 電源模式選「最佳效能」；
  - 實驗期間不要讓 Windows Update 重開機，也不要開其他重的程式。
- **每次上機**：`wsl --shutdown` → 開 WSL → 1.1 的 300 s 測試 PASS → 才開手臂電源。
- **實驗中**：`assist_board.csv` 的 `wall` 欄位會記下實際時間。出現 deadman 停止，但橋接程式和板子都正常，就停下來回到 1.1（第 7 節）。

### 1.6 用原生 Linux 時的架構（備用，35.93）

- **兩台電腦**：Trigno 的 TCU 只有 Windows 版，所以不能只用 Linux，也不能用同一台筆電雙系統開機。
  - **Windows**：TCU、TrignoBridge、TaskScreen、ExperimentPanel、板子（USB）、`udp_tcp_relay.py --udp 50556 --to <Linux IP>:50560`。
  - **Linux**（Ubuntu 22.04＋ROS 2 Humble，和測過的版本相同）：Kortex 驅動、`assist_ros.py board --listen 0.0.0.0:50560`。
- **網路**：手臂一條有線網路，Windows 和 Linux 之間一條；不要用 Wi-Fi。防火牆開 TCP 50560（Windows 出、Linux 進）。
- **Linux 設定**：
  - 插電；
  - 關掉睡眠和待機；
  - CPU 調速器設成 performance；
  - 校時用 chrony（漸進調整，不跳動）；
  - 開機後 `loop_jitter.py` 90 s 要 PASS。
- 兩台電腦的時間戳記不能直接相減。延遲用 relay 的 ack 來回時間量；紀錄結束後收在一起。

## 2. 手臂設定（開機，還不跑程式）

| # | 步驟 | 通過條件 | ☐ |
|---|---|---|---|
| 2.1 | 開機，用網路線連控制電腦。IP【待確認：Gen3 出廠預設常見是 192.168.1.10，以實機標籤或 Web App 為準】 | **在 WSL 裡** `ping` 得到（連不到見 1.5） | ☐ |
| 2.2 | 用 Kinova Web App 設定安全限制【待確認：選單名稱與可設定的項目】：關節速度、末端速度上限（程式最快 0.08 m/s，限制設 0.15 m/s 左右）、保護區（桌面、架子後方） | 設定存檔、截圖 | ☐ |
| 2.3 | 確認夾爪是 2F-85，接在手臂上 | Web App 看得到夾爪 | ☐ |
| 2.4 | 手臂放在離起始姿勢近的位置。起始姿勢的關節角度是 [−3, 29, −2, 137, −5, −75, 92]° | 目測，周圍沒有東西 | ☐ |

## 3. 啟動驅動程式

```
ros2 launch kortex_bringup gen3.launch.py robot_ip:=<IP> gripper:=robotiq_2f_85 dof:=7 launch_rviz:=false
```

（和 `gen3_sim.sh` 一樣，只是沒有 `use_fake_hardware:=true`。）

| # | 檢查 | 通過條件 | ☐ |
|---|---|---|---|
| 3.1 | 控制器 | `joint_trajectory_controller`、`joint_state_broadcaster`、`robotiq_gripper_controller` 都是 active | ☐ |
| 3.2 | 連續關節（1、3、5、7）回報的角度範圍【待確認】 | 記下 `/joint_states` 的值：是 ±π 內，還是會超過。兩種情況程式都能處理（35.92 的 `rebase`），但要記錄 | ☐ |
| 3.3 | 故障重置方法【待確認：`fault_controller` 的服務名稱，或用 Web App 清除】 | 會操作 | ☐ |

## 4. 第一次動（手放在急停上）

| # | 步驟 | 指令 | 通過條件 | ☐ |
|---|---|---|---|---|
| 4.1 | 到起始姿勢，慢速 | `python3 src/pc/sim/assist_ros.py start --start-rate 10` | 印出「最大關節變化 N° 在 T s」；沒有關節繞遠路；「measured tool … mm」< 10 mm、「largest joint difference」< 5°。沒到位時程式會印出「NOT taking control」並停止（35.107），這時**不要**重跑硬上，先查驅動和控制器 | ☐ |
| 4.2 | 夾爪開關 | （`start` 會先開夾爪） | 夾爪打開 | ☐ |
| 4.3 | 鍵盤控制，**沒有物體、沒有架子** | `assist_ros.py keys --limit 120` | W／S／A／D 方向對；空白鍵就停；碰到工作空間邊界會停；結束時 holds 是 0 | ☐ |
| 4.4 | 追蹤保護 | 4.3 時用手輕推手臂（或按暫停）【待確認：實機被推時的行為】 | 出現「!! … holding」，放鬆後恢復 | ☐ |
| 4.5 | **快速正反切換**（35.107）：沒有物體，W↔S、A↔D 每 0.3 s 換一次，連續 10 秒 | `assist_ros.py keys`，速度維持預設 | 沒有頓挫或異音；沒有出現 Kinova 的故障狀態；holds 是 0。有頓挫就停，回報（可能要加速度斜坡） | ☐ |

## 5. 場景校正（物體位置必須準）

- 程式裡物體和架子的位置是寫死的（`assist_ros.py` 的 `OBJECTS`、`SHELVES`，基座座標）。
- **夾取的容許誤差只有 1.5 cm**，所以實物位置誤差要 < 1 cm。

| # | 步驟 | 通過條件 | ☐ |
|---|---|---|---|
| 5.1 | 用鍵盤把夾爪中心移到每個物體正前方（預夾取點），記下程式印出的位置 | 和程式的位置差 < 1 cm；不符就移動實物，不要改程式 | ☐ |
| 5.2 | 架子高度與位置同上 | 同上 | ☐ |
| 5.3 | 鍵盤做一次完整的拿和放 | 物體放到目標架子，沒有碰倒其他東西 | ☐ |

## 6. 接上 EMG（板子 `rtl_task_s7f`）

| # | 步驟 | 通過條件 | ☐ |
|---|---|---|---|
| 6.1 | 依 `SOP_自我測試.md` 戴感測器、校正 | 校正完成 | ☐ |
| 6.2 | 橋接程式：`--firmware lda --classes 9 --preset s7 --fwd-pred 1 --udp 50556`＋`report 3`；relay：`udp_tcp_relay.py --udp 50556` | assist 印出「board connected」 | ☐ |
| 6.3 | **deadman 測試**：手臂移動時關掉橋接程式 | 0.5 s 內停，之後不會自己再動 | ☐ |
| 6.3b | **鎖定中斷線**（35.107）：鎖定一個物體、在模式 2 用 W 前進時，拔掉板子的 USB | 0.5 s 內停；插回、橋接程式重連後，**不做新手勢就不會動**；做新手勢後照模式 2 的規則動 | ☐ |
| 6.3c | **偏心夾取**（35.107）：故意在物體偏左或偏右約 2 cm 處夾 | 記錄：夾爪有沒有夾住、手臂有沒有進故障狀態、旁邊的物體有沒有被推動。進故障狀態就停，回報 | ☐ |
| 6.3d | **夾爪回饋**（35.107）：先夾真的物體 3 次、再在沒有物體的地方夾 3 次，`assist_ros.py` 加 `--grip-check` | 在 `task_events.csv` 的 `grip_result` 記下每次的位置（rad）：夾到物體應該明顯小於 0.70、空抓接近 0.80；空抓時印出「!! 空抓」並自動打開。**兩組的位置沒有分開，就把 `grip_check.EMPTY_POS` 改到兩組中間，記在報告裡**；分不開就不要用 `--grip-check` | ☐ |
| 6.4 | `assist_ros.py board`，**沒有物體**，只練方向和停 | 方向對、停得住 | ☐ |
| 6.5 | 完整任務：見下面「6.6 試驗紀錄程式」 | 依實驗設計 | ☐ |

### 6.6 試驗紀錄程式（35.101）

**實驗前一天**：產生當天的試驗清單並 commit（每個物體 4 次、放置的架子平均分配、順序隨機）：
```
python3 src/pc/sim/kinova_trials.py make --scene <場景> --n 24 --practice 2 --seed <當天的種子> --out trials_T00_k<天>.csv
```

**實驗時**開兩個 WSL 終端機：
1. 手臂程式（加上場景和試驗通道）：
   ```
   python3 src/pc/sim/assist_ros.py board --scene <場景> --lock-rule intent --level 0.6 --grip gripper --grip-check --trial-port 50570 --task-events k<天>_task_events.csv --log k<天>_assist_board.csv --events k<天>_board_events.csv --limit 4000
   ```
2. 試驗紀錄（協助者操作）：
   ```
   python3 src/pc/sim/kinova_trials.py run --scene <場景> --list trials_T00_k<天>.csv --events k<天>_task_events.csv --out k<天>_trials.csv
   ```

**每個試驗**：
1. 畫面顯示目標，例如「把【下層中架子的右邊那個】放到【上層左架子】」。
2. 協助者把**上一個物體從上層架子拿下來、放回原位（照記號）**，6 個物體都在原位後按 Enter。這一步一定要做：軟體會把物體位置重設成起點，實物不在原位，軟體就會判斷錯（Gazebo 演練中，沒歸位的物體重疊後被撞飛）。
3. 夾爪張開、手臂回到起點（3 秒），畫面出現「開始！」。
4. 受試者操作。放下後，**協助者回答物體是不是真的站在目標架子上（y／n）**。軟體的「放下」不算證據：Gazebo 演練曾有物體被推走、根本沒被夾到，軟體卻記成成功。
5. 要中止（急停、掉落）：協助者輸入 `x` 再按 Enter，輸入原因。

**新的試驗前，手臂要在模式 1**：在架子裡面（模式 2）時程式會拒絕重設，請受試者先用 S 退出；夾爪還夾著物體時，協助者扶住物體再按 Enter，夾爪才會張開。

**場景**：`crowded` 是模擬用的佈置（中心距 8 cm）。實機要先量 2F-85 手指，決定間距後寫成 JSON（`{"objects": [[x, y, z], ...], "shelves": [[x, y, z], ...]}`），`--scene` 填 JSON 的路徑。Gazebo 演練中，夾中心距 8 cm 的物體時，隔壁的物體被推動了約 1.9 cm。

## 7. 立刻停止的情況

- 手臂的動作和指令方向不符；
- 有關節繞遠路，或速度突然變快；
- 出現「holding」但你沒有碰它；
- 出現 deadman 停止，但橋接程式和板子都正常（代表控制電腦有暫停，回到 1.1）；
- 任何碰撞或異音。

停止後：按急停 → 記下時間和畫面 → 重置故障 → 從第 4 節重新開始。

## 8. 每次要保留的紀錄

- `assist_board.csv`：每 100 ms 的指令、模式、位置、追蹤誤差、實際時間；
- `board_events.csv`、`assist_stdout.txt`；
- 橋接程式的 `mcu.csv`、`ops.csv`；
- Web App 安全設定的截圖；
- 這張檢查表（打勾、日期、異常）。
